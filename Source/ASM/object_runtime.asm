; ============================================================================
; Объектный runtime M72 и ROM-дескрипторы аппаратных спрайтов.
;
; Координаты объектов сохраняются в нативной системе видеочипа M72:
; X относительно якоря 320, Y относительно нижней линии 384. Составной sprite
; описан шестью байтами World ROM `(signed dx, signed dy, code, attr)`.
; FT812 получает отдельный PALETTED4444 bitmap на каждую исходную cell 16x16;
; сами pixels поднимаются on-demand из полного sprite ROM через cache.
; ============================================================================

RTYPE_OBJECT_BASE          EQU #C000
RTYPE_OBJECT_COUNT         EQU 96
RTYPE_OBJECT_REC_SIZE      EQU #40
RTYPE_OBJECT_BYTES         EQU RTYPE_OBJECT_COUNT * RTYPE_OBJECT_REC_SIZE
RTYPE_OBJECT_SCRATCH       EQU #4300        ; один резидентный снимок 64 байта
RTYPE_OBJECT_WORK_BASE     EQU #4340        ; 58 байт, всегда видимы при bank CALL
RTYPE_OBJECT_FREE_QUEUE    EQU #D900        ; 96 индексов FIFO `$03A6/$03EC`
RTYPE_OBJECT_FREE_HEAD     EQU #D960
RTYPE_OBJECT_FREE_TAIL     EQU #D961
RTYPE_OBJECT_FREE_COUNT    EQU #D962
RTYPE_OBJECT_SERIAL        EQU #D963        ; word, порядок вставки
RTYPE_RESOURCE_TYPES       EQU #D970        ; 16 bytes, `$FF` = свободный slot
RTYPE_RESOURCE_REFS        EQU #D980        ; 16 bytes, счётчик владельцев
RTYPE_RNG_A                EQU #D990        ; три byte состояния `$EDE9`
RTYPE_RNG_B                EQU #D991
RTYPE_RNG_C                EQU #D992
RTYPE_CLEANUP_ACTIVE       EQU #D993        ; byte `$2FC4`
RTYPE_PROJECTILE_COUNT     EQU #D994        ; word, phase seed `$E601`
RTYPE_ACTIVE_PLAYER        EQU #D996        ; `$2F20`: 0=P1, nonzero=P2
RTYPE_TRANSITION_FLAGS     EQU #D997        ; `$2F44/$2F45`, два bytes
RTYPE_TRANSITION_SOUND_INDEX EQU #D999      ; `$2FC5`
RTYPE_LAST_SOUND_COMMAND   EQU #D99A        ; host-visible выход task `$0303`
; Второй M72 palette-bank: 15 управляющих записей по 12 bytes. Храним их
; отдельно от resource allocator, поскольку `$5526/$5596/$FBED` меняют tile
; palette slots, а acquire/release объектов управляет sprite palettes.
RTYPE_PALETTE_BANK2_RECORDS EQU #DB00
RTYPE_PALETTE_RECORD_SIZE   EQU 12
RTYPE_PALETTE_RECORD_COUNT  EQU 16

; ---------------------------------------------------------------------------
; Живой список scheduler-a `$03A6/$03EC`.
;
; Старая первая трансляция обходила 94 physical slots отдельно для
; каждого из 71 type. Даже пустой кадр тратил 230 тысяч Z80-
; инструкций и превращал 57 Hz в «слайд-шоу». Здесь хранятся два
; однобайтных указателя на каждую из 96 записей. Порядок точно
; `(priority, -serial)`: меньший priority идёт раньше, а новая запись
; равного priority вставляется перед старой, как `JAE` в ROM.
RTYPE_SCHED_NEXT          EQU #DA00        ; 96 bytes, `$FF` = конец
RTYPE_SCHED_PREV          EQU #DA60        ; 96 bytes, `$FF` = начало
RTYPE_SCHED_HEAD          EQU #DAC0        ; первый active index
RTYPE_SCHED_TAIL          EQU #DAC1        ; последний active index
RTYPE_SCHED_NULL          EQU #FF

; Bank #0A/#0B отображаются в CPU slot2 `$8000…$BFFF`. Поэтому ни один
; общий temporary не может жить во второй странице Core: прямой `LD ($81xx)`
; во время bank CALL читал бы/перезаписывал машинный код выбранного банка.
; После начала gameplay титульная копия sprite RAM `$4300…$46FF` больше не
; используется; `$4300…$433F` занимает object scratch, а следующие 58 байт
; являются настоящим резидентным work-блоком для Core и обоих code banks.
RTypeObjects_CurrentIndex          EQU RTYPE_OBJECT_WORK_BASE + 0
RTypeObjects_ParentIndex           EQU RTYPE_OBJECT_WORK_BASE + 1
RTypeObjects_ScanIndex             EQU RTYPE_OBJECT_WORK_BASE + 2
RTypeObjects_DesiredType           EQU RTYPE_OBJECT_WORK_BASE + 3
RTypeObjects_MotionRemaining       EQU RTYPE_OBJECT_WORK_BASE + 4
RTypeObjects_MotionCommand         EQU RTYPE_OBJECT_WORK_BASE + 5
RTypeObjects_ParticleJitter        EQU RTYPE_OBJECT_WORK_BASE + 6
RTypeObjects_RomCursor             EQU RTYPE_OBJECT_WORK_BASE + 7
RTypeObjects_NewParticleVelocities EQU RTYPE_OBJECT_WORK_BASE + 9
RTypeObjects_FormationCommandIndex EQU RTYPE_OBJECT_WORK_BASE + 11
RTypeObjects_FormationMovement     EQU RTYPE_OBJECT_WORK_BASE + 12
RTypeObjects_FormationParentX      EQU RTYPE_OBJECT_WORK_BASE + 14
RTypeObjects_FormationParentY      EQU RTYPE_OBJECT_WORK_BASE + 16
RTypeObjects_FormationParentScript EQU RTYPE_OBJECT_WORK_BASE + 18
RTypeObjects_FormationParentPhase  EQU RTYPE_OBJECT_WORK_BASE + 20
RTypeObjects_ProjectileVelocityTable EQU RTYPE_OBJECT_WORK_BASE + 22
RTypeObjects_ProjectileSourceX       EQU RTYPE_OBJECT_WORK_BASE + 24
RTypeObjects_ProjectileSourceY       EQU RTYPE_OBJECT_WORK_BASE + 26
RTypeObjects_ProjectileDirection     EQU RTYPE_OBJECT_WORK_BASE + 28
RTypePlayerNativeX                    EQU RTYPE_OBJECT_WORK_BASE + 29
RTypePlayerNativeY                    EQU RTYPE_OBJECT_WORK_BASE + 31
RTypeSprite_RomCursor                 EQU RTYPE_OBJECT_WORK_BASE + 33
RTypeSprite_Descriptor                EQU RTYPE_OBJECT_WORK_BASE + 35
RTypeSprite_AnchorX                   EQU RTYPE_OBJECT_WORK_BASE + 37
RTypeSprite_AnchorY                   EQU RTYPE_OBJECT_WORK_BASE + 39
RTypeSprite_AnchorPlusDy              EQU RTYPE_OBJECT_WORK_BASE + 41
RTypeSprite_BaseX                     EQU RTYPE_OBJECT_WORK_BASE + 43
RTypeSprite_BaseY                     EQU RTYPE_OBJECT_WORK_BASE + 45
RTypeSprite_Code                      EQU RTYPE_OBJECT_WORK_BASE + 47
RTypeSprite_Attr                      EQU RTYPE_OBJECT_WORK_BASE + 49
RTypeSprite_VertexX                   EQU RTYPE_OBJECT_WORK_BASE + 51
RTypeSprite_Width                     EQU RTYPE_OBJECT_WORK_BASE + 53
RTypeSprite_Height                    EQU RTYPE_OBJECT_WORK_BASE + 54
RTypeSprite_CellX                     EQU RTYPE_OBJECT_WORK_BASE + 55
RTypeSprite_CellY                     EQU RTYPE_OBJECT_WORK_BASE + 56
RTypeSprite_Palette                   EQU RTYPE_OBJECT_WORK_BASE + 57
; Stage-controller `$A22E` позже меняет этот word на `$A3B3/$A523`.
; Он резидентный: части `$915B` читают его при отображённом bank #0C.
RTypeWorldStageControllerHandler      EQU RTYPE_OBJECT_WORK_BASE + 58
; Защитные счётчики live scheduler-a принадлежат транслятору и размещены вне
; sprite/palette scratch. Наложение на #437C…#437F запрещено: там live state
; target palette reader-а, и его порча превращает descriptor cells в мусор.
RTypeScheduler_UpdateRemaining        EQU RTypePySchedulerUpdateRemaining
RTypeScheduler_InsertRemaining        EQU RTypePySchedulerInsertRemaining
RTypeScheduler_RebuildIndex           EQU RTypePySchedulerRebuildIndex
RTypeScheduler_RepairCount            EQU RTypePySchedulerRepairCount
RTYPE_OBJECT_WORK_SIZE                EQU 60

; Общая часть 64-байтной записи. Остальные поля сохраняются за конкретным
; handler в тех же offsets, которые использует исходная V30-логика.
RTYPE_OBJ_TYPE             EQU #00          ; 0 = запись свободна
RTYPE_OBJ_FLAGS            EQU #01
RTYPE_OBJ_X                EQU #02          ; native anchor X, word
RTYPE_OBJ_Y                EQU #04          ; native anchor Y, word
RTYPE_OBJ_DESCRIPTOR       EQU #06          ; World ROM address, word
RTYPE_OBJ_PALETTE          EQU #08          ; живой resource/palette slot 0…15
RTYPE_OBJ_RESOURCE         EQU #09          ; тип ресурса, нужен при освобождении
RTYPE_OBJ_PRIORITY         EQU #0A          ; scheduler priority, word
RTYPE_OBJ_SERIAL           EQU #0C          ; порядок вставки, word
RTYPE_OBJ_STATE            EQU #0E
RTYPE_OBJ_SUBSTATE         EQU #0F
RTYPE_OBJ_X_FRACTION       EQU #10
RTYPE_OBJ_Y_FRACTION       EQU #11
RTYPE_OBJ_X_VELOCITY       EQU #12          ; signed Q8, word
RTYPE_OBJ_Y_VELOCITY       EQU #14          ; signed Q8, word
RTYPE_OBJ_SCRIPT           EQU #16          ; корень списка motion streams
RTYPE_OBJ_SCRIPT_PTR       EQU #18          ; текущий byte stream
RTYPE_OBJ_SCRIPT_COMMANDS  EQU #1A
RTYPE_OBJ_MOTION_PHASE     EQU #1B          ; word: parent может передать `$AA8F`
RTYPE_OBJ_TIMER            EQU #1D          ; word

RTYPE_OBJ_RED_FLYER        EQU 1
RTYPE_OBJ_PALETTE_CYCLE    EQU 2
RTYPE_OBJ_PARTICLE_OWNER   EQU 3
RTYPE_OBJ_BG_PARTICLE      EQU 4
RTYPE_OBJ_CLEANUP_TIMER    EQU 5
RTYPE_OBJ_FORMATION_PARENT EQU 6
RTYPE_OBJ_FORMATION_CHILD  EQU 7
RTYPE_OBJ_GROUND_WALKER    EQU 8
RTYPE_OBJ_ENEMY_PROJECTILE EQU 9
RTYPE_OBJ_TERRAIN_BOUND    EQU 10
RTYPE_OBJ_TARGETING_80E3   EQU 11
RTYPE_OBJ_TARGETING_FLASH  EQU 12
RTYPE_OBJ_TARGETING_SHOT   EQU 13
RTYPE_OBJ_LARGE_TERRAIN    EQU 14
RTYPE_OBJ_LARGE_CHILD      EQU 15
RTYPE_OBJ_TERRAIN_AWARE    EQU 16
RTYPE_OBJ_ANIMATED_86A6    EQU 17
RTYPE_OBJ_TERRAIN_MOD_PARENT EQU 18
RTYPE_OBJ_TERRAIN_MOD_CHILD  EQU 19
RTYPE_OBJ_TERRAIN_MOD_SHOT   EQU 20
RTYPE_OBJ_HANDLER_60BA       EQU 21
RTYPE_OBJ_HANDLER_60BA_SHOT  EQU 22
RTYPE_OBJ_HANDLER_60BA_CHILD EQU 23
RTYPE_OBJ_DOB_ROOT           EQU 24
RTYPE_OBJ_DOB_BACK           EQU 25
RTYPE_OBJ_DOB_BODY           EQU 26
RTYPE_OBJ_DOB_ANCHOR         EQU 27
RTYPE_OBJ_DOB_TENTACLE       EQU 28
RTYPE_OBJ_DOB_ORB            EQU 29
RTYPE_OBJ_DOB_ORB_TRAIL      EQU 30
RTYPE_OBJ_DOB_DEBRIS         EQU 31
RTYPE_OBJ_DOB_EXP_F280       EQU 32
RTYPE_OBJ_DOB_EXP_EF00       EQU 33
RTYPE_OBJ_DOB_EXP_FE00       EQU 34
RTYPE_OBJ_ENEMY_6F89         EQU 35
RTYPE_OBJ_SPAWNER_875D       EQU 36
RTYPE_OBJ_SPAWNER_875D_CHILD EQU 37
RTYPE_OBJ_ENEMY_7D68         EQU 38
RTYPE_OBJ_CHILD_8D85         EQU 39
RTYPE_OBJ_MULTIPART_915B_PARENT EQU 40
RTYPE_OBJ_MULTIPART_915B_CHILD  EQU 41
RTYPE_OBJ_RADIAL_95F1           EQU 42
RTYPE_OBJ_TIMED_CONTROL_F3C1     EQU 43
RTYPE_OBJ_TERRAIN_ENEMY_696E     EQU 44
RTYPE_OBJ_ENEMY_8F5E             EQU 45
RTYPE_OBJ_ENEMY_8469             EQU 46
RTYPE_OBJ_STRAIGHT_SHOT_E6AB     EQU 47
RTYPE_OBJ_ENEMY_8561             EQU 48
RTYPE_OBJ_ENEMY_5CEA             EQU 49
RTYPE_OBJ_ENEMY_5EED             EQU 50
RTYPE_OBJ_ENEMY_7182             EQU 51
RTYPE_OBJ_ENEMY_7294             EQU 52
RTYPE_OBJ_PROJECTILE_7435        EQU 53
RTYPE_OBJ_STAGE_OBJECT_8C12      EQU 54
RTYPE_OBJ_FIXED_LARGE_6E9B       EQU 55
RTYPE_OBJ_FORMATION_78_PARENT    EQU 56
RTYPE_OBJ_FORMATION_78_CHILD     EQU 57
RTYPE_OBJ_FINAL_SPAWNER_9660     EQU 58
RTYPE_OBJ_FINAL_PROJECTILE_96E9  EQU 59
RTYPE_OBJ_A71D_CONTROLLER        EQU 60
RTYPE_OBJ_A71D_BODY              EQU 61
RTYPE_OBJ_A71D_ATTACHMENT        EQU 62
RTYPE_OBJ_A71D_DEBRIS            EQU 63
RTYPE_OBJ_B7FB_ROOT               EQU 64
RTYPE_OBJ_B7FB_SEGMENT            EQU 65
RTYPE_OBJ_B7FB_RANDOM_SPAWNER     EQU 66
RTYPE_OBJ_B7FB_RANDOM_CHILD       EQU 67
RTYPE_OBJ_B7FB_MISSILE_SPAWNER    EQU 68
RTYPE_OBJ_B7FB_MISSILE            EQU 69
RTYPE_OBJ_B7FB_CORE               EQU 70
RTYPE_OBJ_B7FB_CORE_CHILD         EQU 71
RTYPE_OBJ_FINAL_STREAM_FB53       EQU 72
RTYPE_OBJ_FINAL_RESET_EE3C        EQU 73
RTYPE_OBJ_FINAL_SEQUENCE_EEB5     EQU 74
RTYPE_OBJ_STAGE_CONTROLLER        EQU 75
RTYPE_OBJ_B1D8_ROOT               EQU 76
RTYPE_OBJ_B1D8_CHILD              EQU 77
RTYPE_OBJ_C0_FINAL_SPRITE         EQU 78
RTYPE_OBJ_C0_TERRAIN_CHILD        EQU 79

RTYPE_OBJECT_BANK1_PAGE    EQU #0A
RTYPE_OBJECT_BANK2_PAGE    EQU #0B
RTYPE_OBJECT_BANK3_PAGE    EQU #0C
RTYPE_OBJECT_BANK4_PAGE    EQU #0D
RTYPE_COLLISION_BANK_PAGE  EQU #E5

; Эти входы обязаны оставаться в постоянно отображённой части Core ниже
; `$8000`: object-bank выполняется прямо в slot2 и не видит вторую страницу
; Core. Размещаем их до крупных dispatch-таблиц, чтобы рост обработчиков не
; превращал штатный CALL в переход на случайные байты текущего банка.
;
; Bank #0D вызывает уже доказанные автоматы bank #0C. Обычные trampolines
; восстанавливают Core page и потому здесь непригодны: RET оказался бы в
; unmapped `$8xxx`. Эти два входа намеренно восстанавливают именно bank #0D.
RTypeObjectBank4_SpawnMultipart915B:
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                CALL RTypeBank3_InitMultipart915B
                LD   A, RTYPE_OBJECT_BANK4_PAGE
                SetPage2_A
                RET
RTypeObjectBank4_SpawnEnemy5EED:
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                CALL RTypeBank3_InitEnemy5EED
                LD   A, RTYPE_OBJECT_BANK4_PAGE
                SetPage2_A
                RET

; Последовательно прочитать word по служебному ROM cursor и сдвинуть его на 2.
; Функция вызывается из всех четырёх object-bank и поэтому также резидентна.
RTypeObjects_ReadWordNext:
                LD   HL, (RTypeObjects_RomCursor)
                INC  HL
                INC  HL
                LD   (RTypeObjects_RomCursor), HL
                DEC  HL
                DEC  HL
                JP   RTypeWorldRom_ReadWord

; Поля `$20…` зависят от типа. Имена ниже документируют только те записи,
; где соответствующий handler действительно владеет этим offset.
RTYPE_OBJ_FIRE_COUNTER     EQU #20          ; Red Flyer common `$F63A`
RTYPE_OBJ_FIRE_A           EQU #22
RTYPE_OBJ_FIRE_B           EQU #24
RTYPE_OBJ_PROJECTILE_SCRIPT EQU #26
RTYPE_OBJ_CYCLE_PALETTE    EQU #20          ; PaletteCycle `$FBED`
RTYPE_OBJ_CYCLE_FIRST      EQU #22
RTYPE_OBJ_CYCLE_SECOND     EQU #24
RTYPE_OBJ_CYCLE_REMAINING  EQU #26
RTYPE_OBJ_CYCLE_MODE       EQU #28
RTYPE_OBJ_CYCLE_MASK       EQU #2A
RTYPE_OBJ_CYCLE_PHASE      EQU #2C
RTYPE_OBJ_FB_STREAM        EQU #20          ; `$FB53`: current 8-byte record
RTYPE_OBJ_FB_ELAPSED       EQU #22          ; cumulative timeline counter
RTYPE_OBJ_FINAL_TIMER      EQU #20          ; `$EE3C`: восемь pass до reset
RTYPE_OBJ_FINAL_TABLE      EQU #20          ; `$EF1E`: ES pointer `$88E8`
RTYPE_OBJ_FINAL_CADENCE    EQU #22          ; `$0030`, затем `$0040/$FFFF`
RTYPE_OBJ_FINAL_LIFETIME   EQU #24          ; `$0560` общей сцены
; `$A22E/$B0E1/$C0A9`: один невидимый target-type, но независимые поля.
; KIND не является приблизительным state: bank #0D выбирает буквальный ROM
; автомат, а остальные offsets сохраняют его собственные counters/pointers.
RTYPE_OBJ_CTRL_KIND         EQU #20
RTYPE_OBJ_CTRL_PHASE        EQU #21
RTYPE_OBJ_CTRL_COUNTER      EQU #22
RTYPE_OBJ_CTRL_TIMER        EQU #24
RTYPE_OBJ_CTRL_POINTER      EQU #26
RTYPE_OBJ_CTRL_AUX          EQU #28
RTYPE_OBJ_CTRL_AUX2         EQU #2A
RTYPE_OBJ_CTRL_AUX3         EQU #2C
RTYPE_OBJ_CTRL_DAMAGE       EQU #2E
RTYPE_OBJ_CTRL_HP           EQU #2F
RTYPE_OBJ_CTRL_EXIT_TIMER   EQU #30
RTYPE_OBJ_CTRL_FLAGS        EQU #32
RTYPE_OBJ_CTRL_POINTER2     EQU #34
RTYPE_OBJ_CTRL_AUX4         EQU #36
RTYPE_OBJ_CTRL_AUX5         EQU #38
; `$B1D8/$B1FA`: root использует те же offsets, что V30 record. Child хранит
; индекс root вместо непереносимого near-pointer BP.
RTYPE_OBJ_B1_VX             EQU #20
RTYPE_OBJ_B1_VY             EQU #22
RTYPE_OBJ_B1_TARGET_TIMER   EQU #24
RTYPE_OBJ_B1_LIFETIME       EQU #26
RTYPE_OBJ_B1_DAMAGE         EQU #2E
RTYPE_OBJ_B1_HP             EQU #2F
RTYPE_OBJ_B1_ANIM_RELOAD    EQU #10
RTYPE_OBJ_B1_ANIM_TIMER     EQU #12
RTYPE_OBJ_B1_ATTACK_FLAG    EQU #30
RTYPE_OBJ_B1_SELECTED_CHILD EQU #32
RTYPE_OBJ_B1_PREVIOUS_CHILD EQU #34
RTYPE_OBJ_B1_NEAREST        EQU #36
RTYPE_OBJ_B1_REMAINING      EQU #38
RTYPE_OBJ_B1_FLASH_PALETTE  EQU #3C
RTYPE_OBJ_B1_FLASH_TIMER    EQU #3D
RTYPE_OBJ_B1_EXIT_TIMER     EQU #3E
RTYPE_OBJ_B1_CHILD_ROOT     EQU #20
RTYPE_OBJ_B1_CHILD_DX       EQU #22
RTYPE_OBJ_B1_CHILD_DY       EQU #24
RTYPE_OBJ_B1_CHILD_WOBBLE_X EQU #26
RTYPE_OBJ_B1_CHILD_WOBBLE_Y EQU #28
RTYPE_OBJ_B1_CHILD_PHASE    EQU #2A
RTYPE_OBJ_B1_CHILD_DAMAGE   EQU #2E
RTYPE_OBJ_B1_CHILD_HP       EQU #2F
RTYPE_OBJ_B1_CHILD_DELAY    EQU #30
; `$983B`: четыре финальные формы используют готовый motion stream.
RTYPE_OBJ_C0_OWNER          EQU #20
RTYPE_OBJ_C0_FORM           EQU #21
RTYPE_OBJ_C0_MOTION_ROOT    EQU #22
RTYPE_OBJ_C0_LIFETIME       EQU #24
RTYPE_OBJ_C0_TERRAIN_OWNER  EQU #20
RTYPE_OBJ_C0_TERRAIN_TIMER  EQU #22
RTYPE_OBJ_OWNER_REMAINING  EQU #20          ; ParticleController `$E4A5`
RTYPE_OBJ_OWNER_VELOCITIES EQU #22
RTYPE_OBJ_OWNER_CADENCE    EQU #24
RTYPE_OBJ_OWNER_COUNTER    EQU #26
RTYPE_OBJ_OWNER_SLOTS      EQU #28          ; четыре palette slots
RTYPE_OBJ_FORM_SEQUENCE    EQU #20          ; FormationParent `$5DC8`
RTYPE_OBJ_FORM_REMAINING   EQU #22
RTYPE_OBJ_FORM_INDEX       EQU #24
RTYPE_OBJ_FORM_TIMER       EQU #26
RTYPE_OBJ_FORM_PHASE       EQU #28
RTYPE_OBJ_WALKER_SECONDARY EQU #2C
RTYPE_OBJ_WALKER_ANIM_PTR  EQU #2E
RTYPE_OBJ_WALKER_ANIM_TIMER EQU #30
RTYPE_OBJ_PROJECTILE_PHASE EQU #2C          ; word = spawn ordinal * 8
RTYPE_OBJ_PROJECTILE_BURST EQU #2E          ; word, `$E686`
RTYPE_OBJ_PROJECTILE_BORN  EQU #30          ; sampled frame, защита immediate pass
RTYPE_OBJ_TERRAIN_PICKUP_INDEX EQU #20       ; `$55E9`: high command nibble
RTYPE_OBJ_TERRAIN_PICKUP_TYPE  EQU #21
RTYPE_OBJ_TERRAIN_PICKUP_PHASE EQU #22
RTYPE_OBJ_TARGET_X          EQU #20          ; `$80E3` tracking target
RTYPE_OBJ_TARGET_Y          EQU #22
RTYPE_OBJ_PREVIOUS_TARGET_X EQU #24
RTYPE_OBJ_PREVIOUS_TARGET_Y EQU #26
RTYPE_OBJ_RETARGET_COUNTER  EQU #28
RTYPE_OBJ_ANIMATION_OFFSET  EQU #2A
RTYPE_OBJ_FLASH_PALETTE     EQU #2B
RTYPE_OBJ_ATTACK_DELAY      EQU #2C
RTYPE_OBJ_ACTIVATION_TIMER  EQU #2E
RTYPE_OBJ_ATTACK_TIMER      EQU #30
RTYPE_OBJ_FLASH_TIMER       EQU #32
RTYPE_OBJ_TARGET_HP         EQU #34          ; word, `$80E3` difficulty-zero `$1E`
RTYPE_OBJ_FLASH_ROOT        EQU #20          ; `$83DF` launch effect
RTYPE_OBJ_FLASH_SEQUENCE    EQU #22
RTYPE_OBJ_FLASH_DELAY       EQU #24
RTYPE_OBJ_LARGE_COOLDOWN_RELOAD EQU #20
RTYPE_OBJ_LARGE_COOLDOWN        EQU #22
RTYPE_OBJ_LARGE_STATE_TIMER     EQU #24
RTYPE_OBJ_LARGE_ANIMATION       EQU #26
RTYPE_OBJ_LARGE_OPEN_BASE       EQU #28
RTYPE_OBJ_LARGE_SHOOT_BASE      EQU #2A
RTYPE_OBJ_LARGE_FLASH_PALETTE   EQU #2C
RTYPE_OBJ_LARGE_FLASH_TIMER     EQU #2D
RTYPE_OBJ_LARGE_HP              EQU #2E          ; byte, literal 6
RTYPE_OBJ_LARGE_EXPLOSION_PTR   EQU #20
RTYPE_OBJ_LARGE_EXPLOSION_TIMER EQU #22
RTYPE_OBJ_SEEK_DIRECTION_FLAGS  EQU #2C
RTYPE_OBJ_SEEK_DIRECTION_COUNT  EQU #2D
RTYPE_OBJ_SEEK_DIRECTION_MASK   EQU #2F
RTYPE_OBJ_SEEK_REVERSE          EQU #31
RTYPE_OBJ_SEEK_ESCAPE_COUNTER   EQU #32
RTYPE_OBJ_ANIMATED_DESCRIPTOR_BASE EQU #2C
RTYPE_OBJ_MOD_RECORD_POINTER  EQU #20
RTYPE_OBJ_MOD_CHILD_COUNT     EQU #22
RTYPE_OBJ_MOD_TIMER           EQU #24
RTYPE_OBJ_MOD_CENTER_DEAD     EQU #26
RTYPE_OBJ_MOD_BUILD_PATH      EQU #27
RTYPE_OBJ_MOD_ERASE_PATH      EQU #29
RTYPE_OBJ_MOD_PATH_ORIGIN     EQU #2B
RTYPE_OBJ_MOD_BUILD_CURSOR    EQU #2D
RTYPE_OBJ_MOD_ERASE_CURSOR    EQU #2F
RTYPE_OBJ_MOD_ORDINAL         EQU #2C
RTYPE_OBJ_MOD_LOCAL_TIMER     EQU RTYPE_PY_MOD_LOCAL_TIMER_OFFSET
RTYPE_OBJ_MOD_HP              EQU RTYPE_PY_MOD_HP_OFFSET ; отдельный byte, не старший byte timer
RTYPE_OBJ_MOD_SHOT_SLOT_PHASE EQU #2C
RTYPE_OBJ_MOD_SHOT_BURST      EQU #2E
RTYPE_OBJ_60_PHASE             EQU #20
RTYPE_OBJ_60_FIRE_RELOAD       EQU #22
RTYPE_OBJ_60_FIRE_COUNTER      EQU #24
RTYPE_OBJ_60_FACING            EQU #26
RTYPE_OBJ_60_TIMER             EQU #27
RTYPE_OBJ_60_NEXT_STATE        EQU #29
RTYPE_OBJ_60_NEXT_TIMER        EQU #2A
RTYPE_OBJ_60_LANDING_TABLE     EQU #2C
RTYPE_OBJ_60_FLASH_PALETTE     EQU #2E
RTYPE_OBJ_60_FLASH_TIMER       EQU #2F
RTYPE_OBJ_60_HP                EQU #30          ; word, difficulty-zero `$1E`
RTYPE_OBJ_60_CHILD_DIRECTION   EQU #20
RTYPE_OBJ_60_CHILD_TURN_RELOAD EQU #22
RTYPE_OBJ_60_CHILD_MOVE_TIMER  EQU #24
RTYPE_OBJ_60_CHILD_LIFE_TIMER  EQU #26
RTYPE_OBJ_60_CHILD_OVERLAY     EQU #2A
RTYPE_OBJ_60_CHILD_OVERLAY_X   EQU #2C
RTYPE_OBJ_60_CHILD_OVERLAY_Y   EQU #2E
RTYPE_OBJ_60_EXPLOSION_PTR     EQU #20
RTYPE_OBJ_60_EXPLOSION_TIMER   EQU #22
RTYPE_OBJ_DOB_ROOT_TIMEOUT      EQU #20
RTYPE_OBJ_DOB_ROOT_ANCHORS      EQU #22
RTYPE_OBJ_DOB_ROOT_END_TIMER    EQU #24
RTYPE_OBJ_DOB_ROOT_DEFEATED     EQU #26
RTYPE_OBJ_DOB_ROOT_BODY_DEAD    EQU #27
RTYPE_OBJ_DOB_TIMER             EQU #20
RTYPE_OBJ_DOB_FLASH_PALETTE     EQU #22
RTYPE_OBJ_DOB_FLASH_TIMER       EQU #23
RTYPE_OBJ_DOB_DEATH_POINTER     EQU #24
RTYPE_OBJ_DOB_HP                EQU #26
RTYPE_OBJ_DOB_ANCHOR_PATH       EQU #20
RTYPE_OBJ_DOB_ANCHOR_ACTIVATE   EQU #22
RTYPE_OBJ_DOB_ANCHOR_TIMEOUT    EQU #24
RTYPE_OBJ_DOB_ANCHOR_TILE       EQU #26
RTYPE_OBJ_DOB_FIXED_DESCRIPTOR  EQU #20
RTYPE_OBJ_DOB_SCRIPT_START      EQU #22
RTYPE_OBJ_DOB_SCRIPT_POINTER    EQU #24
RTYPE_OBJ_DOB_INTRO_TIMER       EQU #26
RTYPE_OBJ_DOB_CLEANUP_TIMER     EQU #28
RTYPE_OBJ_DOB_STEP_TIMER        EQU #2A
RTYPE_OBJ_DOB_TIP               EQU #2C
RTYPE_OBJ_DOB_FIRE_COUNTER      EQU #2D
RTYPE_OBJ_DOB_FIRE_A            EQU #2F
RTYPE_OBJ_DOB_FIRE_B            EQU #31
RTYPE_OBJ_DOB_PROJECTILE_SCRIPT EQU #33
RTYPE_OBJ_DOB_ORB_TRAIL_TIMER   EQU #20
RTYPE_OBJ_DOB_ORB_STRAIGHT      EQU #22
RTYPE_OBJ_DOB_ORB_ACCELERATION  EQU #24
RTYPE_OBJ_DOB_ORB_ACCEL_TIMER   EQU #26
RTYPE_OBJ_DOB_ORB_ORIGIN_X      EQU #27
RTYPE_OBJ_DOB_ORB_ORIGIN_Y      EQU #29
RTYPE_OBJ_DOB_ORB_PHASE         EQU #2B
RTYPE_OBJ_DOB_ORB_PARENT        EQU #2D
RTYPE_OBJ_DOB_EXP_POINTER       EQU #20
RTYPE_OBJ_DOB_EXP_TIMER         EQU #22
RTYPE_OBJ_DOB_DEBRIS_TERRAIN_TIMER EQU #24
RTYPE_OBJ_DOB_DEBRIS_PATH       EQU #26
RTYPE_OBJ_6F_PRIMARY_X           EQU #20
RTYPE_OBJ_6F_PRIMARY_Y           EQU #22
RTYPE_OBJ_6F_SECONDARY_X         EQU #24
RTYPE_OBJ_6F_SECONDARY_Y         EQU #26
RTYPE_OBJ_6F_DESCRIPTOR_TABLE    EQU #28
RTYPE_OBJ_6F_TARGET_DIRECTION    EQU #2A
RTYPE_OBJ_6F_WAIT_VALUE          EQU #2C
RTYPE_OBJ_6F_ANIMATION           EQU #2E
RTYPE_OBJ_6F_FLASH_PALETTE       EQU #30
RTYPE_OBJ_6F_FLASH_TIMER         EQU #31
RTYPE_OBJ_6F_PREVIOUS_DAMAGE     EQU #32
RTYPE_OBJ_6F_HP                  EQU #34
RTYPE_OBJ_87_SCRIPT_POINTER      EQU #20
RTYPE_OBJ_87_COUNTER             EQU #22
RTYPE_OBJ_87_SPAWN_RELOAD        EQU #24
RTYPE_OBJ_87_SPAWN_TIMER         EQU #26
RTYPE_OBJ_87_DELAY_RELOAD        EQU #28
RTYPE_OBJ_87_DELAY_TIMER         EQU #2A
RTYPE_OBJ_87_TARGET_Y            EQU #2C
RTYPE_OBJ_87_LIFE                EQU #2E
RTYPE_OBJ_87_CHILD_PARENT        EQU #20
RTYPE_OBJ_87_CHILD_DELAY         EQU #21
RTYPE_OBJ_87_CHILD_OSCILLATOR    EQU #23
RTYPE_OBJ_87_CHILD_ANIMATION     EQU #24
RTYPE_OBJ_87_CHILD_DESCRIPTOR    EQU #26
RTYPE_OBJ_87_CHILD_TARGET_Y      EQU #28
RTYPE_OBJ_7D_VARIANT              EQU #20
RTYPE_OBJ_7D_ANIMATION_SEED       EQU #22
RTYPE_OBJ_7D_FLASH_PALETTE        EQU #24
RTYPE_OBJ_7D_FLASH_TIMER          EQU #25
RTYPE_OBJ_7D_HP                   EQU #26
RTYPE_OBJ_8D_FIRE_COUNTER         EQU #20
RTYPE_OBJ_8D_FIRE_A               EQU #22
RTYPE_OBJ_8D_FIRE_B               EQU #24
RTYPE_OBJ_8D_PROJECTILE_SCRIPT    EQU #26
RTYPE_OBJ_8D_ANIMATION            EQU #28
RTYPE_OBJ_8D_TARGET_PLAYER_NEXT   EQU #2A
RTYPE_OBJ_8D_FIXED_DESCRIPTOR     EQU #2B
RTYPE_OBJ_8D_FLASH_PALETTE        EQU #2C
RTYPE_OBJ_8D_FLASH_TIMER          EQU #2D
RTYPE_OBJ_8D_HP                   EQU #2E
RTYPE_OBJ_91_MOTION_ROOT          EQU #20
RTYPE_OBJ_91_BASE_TIMER           EQU #22
RTYPE_OBJ_91_SEQUENCE             EQU #24
RTYPE_OBJ_91_PRIORITY_VALUE       EQU #26
RTYPE_OBJ_91_CLEANUP_ORDINAL      EQU #28
RTYPE_OBJ_91_HEAD                 EQU #2A
RTYPE_OBJ_91_PREVIOUS             EQU #20
RTYPE_OBJ_91_CHILD_PRIORITY       EQU #21
RTYPE_OBJ_91_CLEANUP_COUNTER      EQU #23
RTYPE_OBJ_91_PULSE_TIMER          EQU #25
RTYPE_OBJ_91_PULSE_RELOAD         EQU #27
RTYPE_OBJ_91_PULSE                EQU #29
RTYPE_OBJ_91_FLASH_PALETTE        EQU #2B
RTYPE_OBJ_91_HP                   EQU #2C
RTYPE_OBJ_F3_TIMER                EQU #10
RTYPE_OBJ_F3_SOUND_COMMAND        EQU #12
RTYPE_OBJ_69_FLASH_PALETTE        EQU #28
RTYPE_OBJ_69_FLASH_TIMER          EQU #29
RTYPE_OBJ_69_HP                   EQU #2A
RTYPE_OBJ_8F_DIRECTION            EQU #20
RTYPE_OBJ_8F_NEXT_DIRECTION       EQU #21
RTYPE_OBJ_8F_TURN_TIMER           EQU #22          ; word: `$001F…$0000`
RTYPE_OBJ_8F_TURN_TABLE           EQU #24          ; ROM pair выбранной дуги
RTYPE_OBJ_84_PAUSE_TIMER          EQU #28          ; word: 8 pass после стены
RTYPE_OBJ_85_ANIMATION_BIAS       EQU #20          ; word, `$FAC1` даёт 0
RTYPE_OBJ_85_HP                   EQU #2F          ; byte, difficulty-zero `$1E`
RTYPE_OBJ_85_FIRE_RELOAD          EQU #30
RTYPE_OBJ_85_SHOT_VELOCITY        EQU #32
RTYPE_OBJ_85_FIRE_COUNTER         EQU #34
RTYPE_OBJ_85_SHOT_Y_PHASE         EQU #36          ; word: 0,2,4,6,8
RTYPE_OBJ_85_FLASH_PALETTE        EQU #3E
RTYPE_OBJ_85_FLASH_TIMER          EQU #3F
RTYPE_OBJ_5C_RANDOM_DELAY         EQU #28          ; `$EDE9&$1F + $30`
RTYPE_OBJ_5C_FIRE_RELOAD          EQU #30
RTYPE_OBJ_5C_SHOT_VELOCITY        EQU #32
RTYPE_OBJ_5C_FIRE_COUNTER         EQU #34
RTYPE_OBJ_5E_DIRECTION            EQU #20
RTYPE_OBJ_5E_SPEED_OFFSET         EQU #22
RTYPE_OBJ_5E_TURN_CLOCKWISE       EQU #24
RTYPE_OBJ_5E_MIRRORED             EQU #25
RTYPE_OBJ_5E_FLASH_PALETTE        EQU #26
RTYPE_OBJ_5E_FLASH_TIMER          EQU #27
RTYPE_OBJ_5E_HP                   EQU #28          ; word, initial 10
RTYPE_OBJ_71_DIRECTION            EQU #28
RTYPE_OBJ_71_TURN_RELOAD          EQU #2A
RTYPE_OBJ_71_TURN_COUNTER         EQU #2C
RTYPE_OBJ_71_ACTIVE_TIMER         EQU #2E
RTYPE_OBJ_72_DIRECTION            EQU #28
RTYPE_OBJ_72_ANIMATION            EQU #2A          ; word: 0,6,$0C,$12,$18
RTYPE_OBJ_72_FLASH_PALETTE        EQU #2C
RTYPE_OBJ_72_FLASH_TIMER          EQU #2D
RTYPE_OBJ_72_HP                   EQU #2E          ; word, initial 2
; `$7435` сохраняет common `$E601` phase/burst/born в `$2C/$2E/$30`.
; Дополнительная задержка terrain probe занимает следующий свободный byte.
RTYPE_OBJ_74_TERRAIN_DELAY        EQU #32
RTYPE_OBJ_8C_TERRAIN_PATH         EQU #20
RTYPE_OBJ_8C_TIMER                EQU #22
RTYPE_OBJ_8C_PHASE                EQU #24
RTYPE_OBJ_6E_HP                   EQU #2F          ; byte, literal `$C8`
RTYPE_OBJ_78_MOTION_ROOT          EQU #20
RTYPE_OBJ_78_SEQUENCE             EQU #22
RTYPE_OBJ_78_TIMER                EQU #24
RTYPE_OBJ_78_NEXT_PRIORITY        EQU #26
RTYPE_OBJ_78_HEAD                 EQU #28
RTYPE_OBJ_78_PREVIOUS             EQU #20
RTYPE_OBJ_78_LOGICAL_PRIORITY     EQU #22
RTYPE_OBJ_78_MOTION_TIMER         EQU #24
RTYPE_OBJ_78_DELAY                EQU #26
RTYPE_OBJ_78_STATE_FLAG           EQU #28
RTYPE_OBJ_78_FLASH_PALETTE        EQU #29
RTYPE_OBJ_78_FLASH_TIMER          EQU #2A
RTYPE_OBJ_78_HP                   EQU #2B
RTYPE_OBJ_78_ANIMATION_SEED       EQU #2C
RTYPE_OBJ_78_DESCRIPTOR_BASE      EQU #2E
RTYPE_OBJ_96_PERIOD                EQU #20
RTYPE_OBJ_96_TIMER                 EQU #22
RTYPE_OBJ_96_DESCRIPTOR_BASE       EQU #20
RTYPE_OBJ_A7_SELECTOR              EQU #20
RTYPE_OBJ_A7_COMPLETED             EQU #22
RTYPE_OBJ_A7_ARRIVED               EQU #23
RTYPE_OBJ_A7_ADVANCE               EQU #24
RTYPE_OBJ_A7_EXIT_TIMER            EQU #26
RTYPE_OBJ_A7_BODY_CONTROLLER       EQU #20
RTYPE_OBJ_A7_BODY_KIND             EQU #21
RTYPE_OBJ_A7_BODY_BIT              EQU #22
RTYPE_OBJ_A7_BODY_ROUTE_LIST       EQU #24
RTYPE_OBJ_A7_BODY_MOTION_POINTER   EQU #26
RTYPE_OBJ_A7_BODY_MOTION_TIMER     EQU #28
RTYPE_OBJ_A7_BODY_PHASE            EQU #2A
RTYPE_OBJ_A7_BODY_FLASH_TIMER      EQU #2B
RTYPE_OBJ_A7_BODY_ALT_PALETTE      EQU #2C
RTYPE_OBJ_A7_BODY_FIRE_RELOAD      EQU #2D
RTYPE_OBJ_A7_BODY_FIRE_TIMER       EQU #2E
RTYPE_OBJ_A7_BODY_DEBRIS_ROOT      EQU #30
RTYPE_OBJ_A7_BODY_DEBRIS_POINTER   EQU #32
RTYPE_OBJ_A7_BODY_DEBRIS_TIMER     EQU #34
RTYPE_OBJ_A7_BODY_PAIR_TIMER       EQU #36
RTYPE_OBJ_A7_BODY_HP               EQU #38
RTYPE_OBJ_A7_ATTACHMENT_SOURCE     EQU #28
RTYPE_OBJ_A7_ATTACHMENT_DX         EQU #2A
RTYPE_OBJ_A7_ATTACHMENT_DY         EQU #2C
RTYPE_OBJ_A7_ATTACHMENT_ORIENTATION EQU #2E
RTYPE_OBJ_A7_ATTACHMENT_ALT_PALETTE EQU #30
RTYPE_OBJ_A7_DEBRIS_GRAVITY        EQU #20
RTYPE_OBJ_A7_DEBRIS_PHASE_OFFSET   EQU #22
RTYPE_OBJ_B7_ROOT_TIMER             EQU #20
RTYPE_OBJ_B7_ROOT_DEFEATED          EQU #22
RTYPE_OBJ_B7_ROOT_EXIT_TIMER        EQU #24
RTYPE_OBJ_B7_SEGMENT_ROOT           EQU #20
RTYPE_OBJ_B7_SEGMENT_THRESHOLD      EQU #22
RTYPE_OBJ_B7_SEGMENT_TIMER          EQU #24
RTYPE_OBJ_B7_SEGMENT_REVERSE        EQU #26
RTYPE_OBJ_B7_SEGMENT_DAMAGE         EQU #27
RTYPE_OBJ_B7_RANDOM_ROOT            EQU #20
RTYPE_OBJ_B7_RANDOM_TIMER           EQU #22
RTYPE_OBJ_B7_RANDOM_X_POINTER       EQU #24
RTYPE_OBJ_B7_RANDOM_CADENCE         EQU #26
RTYPE_OBJ_B7_RANDOM_RELOAD          EQU #28
RTYPE_OBJ_B7_RANDOM_RAMP            EQU #2A
RTYPE_OBJ_B7_CHILD_ROOT             EQU #20
RTYPE_OBJ_B7_CHILD_ANIMATED         EQU #21
RTYPE_OBJ_B7_CHILD_HP               EQU #22
RTYPE_OBJ_B7_MSPAWNER_ROOT          EQU #20
RTYPE_OBJ_B7_MSPAWNER_TIMER         EQU #22
RTYPE_OBJ_B7_MSPAWNER_POINTER       EQU #24
RTYPE_OBJ_B7_MISSILE_ROOT           EQU #20
RTYPE_OBJ_B7_MISSILE_TIMER          EQU #22
RTYPE_OBJ_B7_MISSILE_HP             EQU #24
RTYPE_OBJ_B7_CORE_ROOT              EQU #20
RTYPE_OBJ_B7_CORE_TIMER             EQU #22
RTYPE_OBJ_B7_CORE_PHASE             EQU #24
RTYPE_OBJ_B7_CORE_FLASH_PALETTE     EQU #26
RTYPE_OBJ_B7_CORE_FLASH_TIMER       EQU #27
RTYPE_OBJ_B7_CORE_HP                EQU #28

RTYPE_TERRAIN_SCRIPT       EQU 0
RTYPE_TERRAIN_AIR_STEP     EQU 1
RTYPE_TERRAIN_LAND         EQU 2
RTYPE_TERRAIN_WALK         EQU 3
RTYPE_TERRAIN_TURN         EQU 4
RTYPE_TERRAIN_PICKUP       EQU 5
RTYPE_TERRAIN_SPEED        EQU 6
RTYPE_TARGETING_TRACKING    EQU 0
RTYPE_TARGETING_ATTACK      EQU 1
RTYPE_LARGE_BOOTSTRAP       EQU 0
RTYPE_LARGE_MOVE            EQU 1
RTYPE_LARGE_WAIT            EQU 2
RTYPE_LARGE_OPEN            EQU 3
RTYPE_LARGE_SHOOT           EQU 4
RTYPE_LARGE_CLOSE           EQU 5
RTYPE_LARGE_CHILD_RISE      EQU 0
RTYPE_LARGE_CHILD_FALL      EQU 1
RTYPE_LARGE_CHILD_EXPLOSION EQU 2
RTYPE_60_STATE_610D         EQU 0
RTYPE_60_STATE_61E3         EQU 1
RTYPE_60_STATE_652F         EQU 2
RTYPE_60_STATE_62BD         EQU 3
RTYPE_60_STATE_6243         EQU 4
RTYPE_60_STATE_631B         EQU 5
RTYPE_60_STATE_6392         EQU 6
RTYPE_60_STATE_6374         EQU 7
RTYPE_60_STATE_638C         EQU 8
RTYPE_60_STATE_6380         EQU 9
RTYPE_60_STATE_6459         EQU 10
RTYPE_60_STATE_657C         EQU 11
RTYPE_60_AUX_FLIGHT         EQU 0
RTYPE_60_AUX_HOMING         EQU 1
RTYPE_60_AUX_EXPLOSION_WAIT EQU 2
RTYPE_60_AUX_EXPLOSION      EQU 3
RTYPE_DOB_ROOT_SPAWN        EQU 0
RTYPE_DOB_ROOT_ACTIVE       EQU 1
RTYPE_DOB_ROOT_END          EQU 2
RTYPE_DOB_BODY_INTRO        EQU 0
RTYPE_DOB_BODY_EMERGE       EQU 1
RTYPE_DOB_BODY_ACTIVE       EQU 2
RTYPE_DOB_BODY_DEATH        EQU 3
RTYPE_DOB_ANCHOR_WAIT       EQU 0
RTYPE_DOB_ANCHOR_ACTIVE     EQU 1
RTYPE_DOB_ANCHOR_ERASE      EQU 2
RTYPE_DOB_TENTACLE_INTRO    EQU 0
RTYPE_DOB_TENTACLE_ACTIVE   EQU 1
RTYPE_DOB_TENTACLE_CLEANUP  EQU 2
RTYPE_DOB_TENTACLE_EXP_WAIT EQU 3
RTYPE_DOB_TENTACLE_EXPLODE  EQU 4
RTYPE_DOB_ORB_STRAIGHT      EQU 0
RTYPE_DOB_ORB_CURVE         EQU 1
RTYPE_DOB_BACK_ACTIVE       EQU 0
RTYPE_DOB_BACK_EXP_WAIT     EQU 2
RTYPE_DOB_BACK_EXPLODE      EQU 3
RTYPE_6F_WAITING            EQU 0
RTYPE_6F_MOVING             EQU 1
RTYPE_87_CHILD_WAVY         EQU 0
RTYPE_87_CHILD_AIMED        EQU 1
RTYPE_7D_APPROACH           EQU 0
RTYPE_7D_RISE               EQU 1
RTYPE_7D_OPEN               EQU 2
RTYPE_7D_HOLD               EQU 3
RTYPE_7D_CLOSE              EQU 4
RTYPE_7D_RETREAT            EQU 5
RTYPE_8D_SCRIPTED           EQU 0
RTYPE_8D_TERMINAL           EQU 1
RTYPE_8D_ACTIVE             EQU 2
RTYPE_91_FIRST              EQU 0
RTYPE_91_SECOND             EQU 1
RTYPE_91_MAIN               EQU 2
RTYPE_91_HIT                EQU 3
RTYPE_91_LATE               EQU 4
RTYPE_91_TERMINAL           EQU 5
RTYPE_78_FIRST              EQU 0
RTYPE_78_MAIN               EQU 1
RTYPE_78_TERMINAL           EQU 2
RTYPE_78_MAIN_FOLLOW        EQU 3
RTYPE_78_TERMINAL_FOLLOW    EQU 4
RTYPE_78_ESCAPE             EQU 5
RTYPE_A7_CONTROLLER_SPAWN   EQU 0
RTYPE_A7_CONTROLLER_ACTIVE  EQU 1
RTYPE_A7_CONTROLLER_EXIT    EQU 2
RTYPE_A7_BODY_ACTIVE        EQU 0
RTYPE_A7_BODY_DEBRIS        EQU 1
RTYPE_A7_DEBRIS_PAIRED      EQU 0
RTYPE_A7_DEBRIS_FALLING     EQU 1
RTYPE_B7_ROOT_ACTIVE         EQU 0
RTYPE_B7_ROOT_EXIT           EQU 1
RTYPE_B7_CORE_ACTIVE         EQU 0
RTYPE_B7_CORE_EXPLODING      EQU 1
RTYPE_B7_CORE_CHILD_OUT      EQU 0
RTYPE_B7_CORE_CHILD_RETURN   EQU 1

RTYPE_WALKER_FALLING       EQU 0
RTYPE_WALKER_LANDING       EQU 1
RTYPE_WALKER_TURNING       EQU 2
RTYPE_WALKER_SCRIPTED      EQU 3
RTYPE_WALKER_EDGE          EQU 4
RTYPE_WALKER_WALKING       EQU 5

RTYPE_WORLD_ROM_BASE_PAGE  EQU RTYPE_TARGET_PACK_BASE_PAGE + (RTYPE_TARGET_WORLD_OFFSET >> 14)

; Полностью очистить 96 исходных записей и построить FIFO свободных slots.
; Два первых индекса соответствуют постоянным sentinels `$0540/$0580` и не
; выдаются allocator-ом, поэтому начальная очередь содержит ровно 2…95.
RTypeObjects_Reset:
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                XOR  A
                LD   HL, RTYPE_OBJECT_BASE
                LD   DE, RTYPE_OBJECT_BASE + 1
                LD   BC, RTYPE_OBJECT_BYTES - 1
                LD   (HL), A
                LDIR
                LD   HL, RTYPE_OBJECT_FREE_QUEUE
                LD   A, 2
                LD   B, RTYPE_OBJECT_COUNT - 2
.free:         LD   (HL), A
                INC  HL
                INC  A
                DJNZ .free
                XOR  A
                LD   (RTYPE_OBJECT_FREE_HEAD), A
                LD   (RTYPE_OBJECT_SERIAL), A
                LD   (RTYPE_OBJECT_SERIAL + 1), A
                ; Ordered scheduler starts empty.  Link arrays are filled
                ; with `$FF`, so a stale physical slot can never become a
                ; live successor after Reset.
                DEC  A                           ; A=$FF
                LD   (RTYPE_SCHED_HEAD), A
                LD   (RTYPE_SCHED_TAIL), A
                LD   HL, RTYPE_SCHED_NEXT
                LD   DE, RTYPE_SCHED_NEXT + 1
                LD   BC, RTYPE_OBJECT_COUNT * 2 - 1
                LD   (HL), A
                LDIR
                LD   A, RTYPE_OBJECT_COUNT - 2
                LD   (RTYPE_OBJECT_FREE_TAIL), A
                LD   (RTYPE_OBJECT_FREE_COUNT), A
                ; В resource manager свободный type помечается `$FF`, тогда
                ; как reference counters действительно обнуляются.
                LD   HL, RTYPE_RESOURCE_TYPES
                LD   DE, RTYPE_RESOURCE_TYPES + 1
                LD   BC, 15
                LD   (HL), #FF
                LDIR
                XOR  A
                LD   HL, RTYPE_RESOURCE_REFS
                LD   DE, RTYPE_RESOURCE_REFS + 1
                LD   BC, 15
                LD   (HL), A
                LDIR
                CALL RTypeRng_Reset
                XOR  A
                LD   (RTYPE_CLEANUP_ACTIVE), A
                LD   (RTYPE_PROJECTILE_COUNT), A
                LD   (RTYPE_PROJECTILE_COUNT + 1), A
                LD   (RTYPE_ACTIVE_PLAYER), A
                LD   (RTYPE_TRANSITION_FLAGS), A
                LD   (RTYPE_TRANSITION_FLAGS + 1), A
                LD   (RTYPE_TRANSITION_SOUND_INDEX), A
                LD   (RTYPE_LAST_SOUND_COMMAND), A
                ; Титульный renderer оставлял в `$4340+` sprite-RAM bytes.
                ; Перед первым event очищаем все bank-visible temporaries и
                ; устанавливаем исходные native координаты R-9 из oracle.
                LD   HL, RTYPE_OBJECT_WORK_BASE
                LD   DE, RTYPE_OBJECT_WORK_BASE + 1
                LD   BC, RTYPE_OBJECT_WORK_SIZE - 1
                LD   (HL), A
                LDIR
                LD   HL, #01CB
                LD   (RTypePlayerNativeX), HL
                LD   HL, #0110
                LD   (RTypePlayerNativeY), HL
                JP   RTypePalette_Reset

; Взять следующую 64-байтную запись из буквальной FIFO. Результат A=индекс,
; Carry=0. При исчерпании всех 94 игровых записей возвращается Carry=1.
RTypeObjects_Take:
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   A, (RTYPE_OBJECT_FREE_COUNT)
                OR   A
                SCF
                RET  Z
                DEC  A
                LD   (RTYPE_OBJECT_FREE_COUNT), A
                LD   A, (RTYPE_OBJECT_FREE_HEAD)
                LD   E, A
                INC  A
                CP   RTYPE_OBJECT_COUNT
                JR   C, .headReady
                XOR  A
.headReady:    LD   (RTYPE_OBJECT_FREE_HEAD), A
                LD   D, 0
                LD   HL, RTYPE_OBJECT_FREE_QUEUE
                ADD  HL, DE
                LD   A, (HL)
                PUSH AF
                CALL RTypeObjects_RecordAddress
                ; `$03A6` переиспользует физическую 64-байтовую запись. Два
                ; дробных байта Q8 не принадлежат allocator-у и потому могут
                ; пережить освобождение. Обычные initializer-ы их обнуляют,
                ; но projectile `$E601` дословно наследует остаток своего
                ; нового slot. Снимаем residue до очистки записи, чтобы этот
                ; аппаратно наблюдаемый эффект FIFO не потерялся.
                PUSH HL
                LD   DE, RTYPE_OBJ_X_FRACTION
                ADD  HL, DE
                LD   A, (HL)
                LD   (RTypeObjects_TakenXFraction), A
                INC  HL
                LD   A, (HL)
                LD   (RTypeObjects_TakenYFraction), A
                POP  HL
                XOR  A
                LD   (HL), A
                PUSH HL
                POP  DE
                INC  DE
                LD   BC, RTYPE_OBJECT_REC_SIZE - 1
                LDIR
                POP  AF
                OR   A                           ; успешный путь, Carry=0
                RET

; A=индекс 2…95: вернуть запись в хвост FIFO и сделать type=0. Повторное
; освобождение безопасно отсекается по уже нулевому type записи.
RTypeObjects_Release:
                CP   2
                RET  C
                CP   RTYPE_OBJECT_COUNT
                RET  NC
                LD   (.released), A
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   A, (.released)
                CALL RTypeObjects_RecordAddress
                LD   A, (HL)
                OR   A
                RET  Z
                ; Сначала вырезаем запись из ordered list.  Remove намеренно
                ; не затирает NEXT самой удалённой записи: scheduler считывает
                ; этот successor уже после handler-a, как live linked-list ROM.
                LD   A, (.released)
                CALL RTypeScheduler_Remove
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   A, (.released)
                CALL RTypeObjects_RecordAddress
                LD   (HL), 0
                LD   A, (RTYPE_OBJECT_FREE_TAIL)
                LD   E, A
                LD   D, 0
                LD   HL, RTYPE_OBJECT_FREE_QUEUE
                ADD  HL, DE
                LD   A, (.released)
                LD   (HL), A
                LD   A, E
                INC  A
                CP   RTYPE_OBJECT_COUNT
                JR   C, .tailReady
                XOR  A
.tailReady:    LD   (RTYPE_OBJECT_FREE_TAIL), A
                LD   A, (RTYPE_OBJECT_FREE_COUNT)
                INC  A
                LD   (RTYPE_OBJECT_FREE_COUNT), A
                RET
.released:     DEFB 0
RTypeObjects_TakenXFraction:
                DEFB 0
RTypeObjects_TakenYFraction:
                DEFB 0

; A=index. Вырезать active record из двусвязного scheduler-list.
; Unlinked запись (например host-test, записавший type вручную)
; распознаётся по `prev=$FF && head!=index` и не портит list.
RTypeScheduler_Remove:
                LD   (.index), A
                LD   E, A
                LD   D, 0
                LD   HL, RTYPE_SCHED_PREV
                ADD  HL, DE
                LD   A, (HL)
                LD   (.prev), A
                CP   RTYPE_SCHED_NULL
                JR   NZ, .member
                LD   A, (RTYPE_SCHED_HEAD)
                LD   B, A
                LD   A, (.index)
                CP   B
                RET  NZ
.member:       LD   E, A                         ; E пока не используется
                LD   A, (.index)
                LD   E, A
                LD   D, 0
                LD   HL, RTYPE_SCHED_NEXT
                ADD  HL, DE
                LD   A, (HL)
                LD   (.next), A

                LD   A, (.prev)
                CP   RTYPE_SCHED_NULL
                JR   NZ, .linkPrevious
                LD   A, (.next)
                LD   (RTYPE_SCHED_HEAD), A
                JR   .previousDone
.linkPrevious: LD   E, A
                LD   D, 0
                LD   HL, RTYPE_SCHED_NEXT
                ADD  HL, DE
                LD   A, (.next)
                LD   (HL), A
.previousDone: LD   A, (.next)
                CP   RTYPE_SCHED_NULL
                JR   NZ, .linkNext
                LD   A, (.prev)
                LD   (RTYPE_SCHED_TAIL), A
                RET
.linkNext:     LD   E, A
                LD   D, 0
                LD   HL, RTYPE_SCHED_PREV
                ADD  HL, DE
                LD   A, (.prev)
                LD   (HL), A
                RET
.index:        DEFB 0
.prev:         DEFB RTYPE_SCHED_NULL
.next:         DEFB RTYPE_SCHED_NULL

; A=индекс записи. Результат HL=#C000+index*64, страница #09 уже должна быть
; отображена вызывающим. Вычисление сохраняет точный 64-байтный шаг M72.
RTypeObjects_RecordAddress:
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                LD   DE, RTYPE_OBJECT_BASE
                ADD  HL, DE
                RET

; A=индекс: скопировать запись из page #09 в резидентный scratch. ROM-reader
; после этого может свободно переключать slot3, не разрушая IX объекта.
RTypeObjects_LoadScratch:
                LD   (RTypeObjects_ScratchIndex), A
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   A, (RTypeObjects_ScratchIndex)
                CALL RTypeObjects_RecordAddress
                LD   DE, RTYPE_OBJECT_SCRATCH
                LD   BC, RTYPE_OBJECT_REC_SIZE
                LDIR
                LD   A, (RTypeObjects_ScratchIndex)
                RET

; A=индекс: сохранить изменённый scratch обратно в 64-байтную запись.
RTypeObjects_StoreScratch:
                LD   (RTypeObjects_ScratchIndex), A
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   A, (RTypeObjects_ScratchIndex)
                CALL RTypeObjects_RecordAddress
                XOR  A
                LD   (RTypeObjects_StoreNewRecord), A
                LD   A, (HL)                     ; old physical type
                OR   A
                JR   NZ, .copy
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE)
                OR   A
                JR   Z, .copy
                ; Первая публикация взятого FIFO-slot: выдать monotonic
                ; serial и вставить запись в live scheduler.  Переход handler-a
                ; внутри того же slot сюда не попадает и сохраняет serial.
                LD   HL, (RTYPE_OBJECT_SERIAL)
                INC  HL
                LD   (RTYPE_OBJECT_SERIAL), HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SERIAL), HL
                LD   A, 1
                LD   (RTypeObjects_StoreNewRecord), A
                LD   A, (RTypeObjects_ScratchIndex)
                CALL RTypeObjects_RecordAddress
.copy:
                EX   DE, HL
                LD   HL, RTYPE_OBJECT_SCRATCH
                LD   BC, RTYPE_OBJECT_REC_SIZE
                LDIR
                LD   A, (RTypeObjects_StoreNewRecord)
                OR   A
                JR   Z, .done
                LD   A, (RTypeObjects_ScratchIndex)
                CALL RTypeScheduler_Insert
.done:
                LD   A, (RTypeObjects_ScratchIndex)
                RET
RTypeObjects_ScratchIndex:
                DEFB 0
RTypeObjects_StoreNewRecord:
                DEFB 0

; A=index новой physical record. Вставить её по unsigned
; `(priority, -serial)`. Вставка сканирует только active list и
; выполняется один раз при allocation, а не 71×94 раз за кадр.
RTypeScheduler_Insert:
                LD   (.index), A
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   A, (.index)
                CALL RTypeObjects_RecordAddress
                LD   DE, RTYPE_OBJ_PRIORITY
                ADD  HL, DE
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                LD   (.priority), DE
                INC  HL
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                LD   (.serial), DE

                LD   A, (.index)
                LD   E, A
                LD   D, 0
                LD   HL, RTYPE_SCHED_NEXT
                ADD  HL, DE
                LD   (HL), RTYPE_SCHED_NULL
                LD   HL, RTYPE_SCHED_PREV
                ADD  HL, DE
                LD   (HL), RTYPE_SCHED_NULL

                LD   A, (RTYPE_SCHED_HEAD)
                CP   RTYPE_SCHED_NULL
                JP   Z, .empty
                LD   (.cursor), A
.find:         LD   A, RTYPE_OBJECT_COUNT
                LD   (RTypeScheduler_InsertRemaining), A
.findNext:     LD   A, (RTypeScheduler_InsertRemaining)
                OR   A
                JP   Z, RTypeScheduler_Rebuild
                DEC  A
                LD   (RTypeScheduler_InsertRemaining), A
                LD   A, (.cursor)
                CP   RTYPE_OBJECT_COUNT
                JP   NC, RTypeScheduler_Rebuild
                CALL RTypeObjects_RecordAddress
                LD   DE, RTYPE_OBJ_PRIORITY
                ADD  HL, DE
                LD   E, (HL)
                INC  HL
                LD   D, (HL)                     ; DE=cursor priority
                LD   HL, (.priority)
                OR   A
                SBC  HL, DE
                JR   C, .insertBefore
                JR   NZ, .next
                ; Equal priority: larger/newer serial is linked first.
                LD   A, (.cursor)
                CALL RTypeObjects_RecordAddress
                LD   DE, RTYPE_OBJ_SERIAL
                ADD  HL, DE
                LD   E, (HL)
                INC  HL
                LD   D, (HL)                     ; DE=cursor serial
                LD   HL, (.serial)
                OR   A
                SBC  HL, DE
                JP   NC, .insertBefore           ; new serial is strictly larger
.next:         LD   A, (.cursor)
                LD   E, A
                LD   D, 0
                LD   HL, RTYPE_SCHED_NEXT
                ADD  HL, DE
                LD   A, (HL)
                CP   RTYPE_SCHED_NULL
                JR   Z, .append
                LD   (.cursor), A
                JR   .findNext

.insertBefore: LD   A, (.cursor)
                LD   E, A
                LD   D, 0
                LD   HL, RTYPE_SCHED_PREV
                ADD  HL, DE
                LD   A, (HL)
                LD   (.previous), A

                LD   A, (.index)
                LD   E, A
                LD   D, 0
                LD   HL, RTYPE_SCHED_NEXT
                ADD  HL, DE
                LD   A, (.cursor)
                LD   (HL), A
                LD   HL, RTYPE_SCHED_PREV
                ADD  HL, DE
                LD   A, (.previous)
                LD   (HL), A

                LD   A, (.cursor)
                LD   E, A
                LD   D, 0
                LD   HL, RTYPE_SCHED_PREV
                ADD  HL, DE
                LD   A, (.index)
                LD   (HL), A
                LD   A, (.previous)
                CP   RTYPE_SCHED_NULL
                JR   NZ, .linkPrevious
                LD   A, (.index)
                LD   (RTYPE_SCHED_HEAD), A
                RET
.linkPrevious: LD   E, A
                LD   D, 0
                LD   HL, RTYPE_SCHED_NEXT
                ADD  HL, DE
                LD   A, (.index)
                LD   (HL), A
                RET

.append:       LD   A, (RTYPE_SCHED_TAIL)
                LD   (.previous), A
                LD   E, A
                LD   D, 0
                LD   HL, RTYPE_SCHED_NEXT
                ADD  HL, DE
                LD   A, (.index)
                LD   (HL), A
                LD   E, A
                LD   D, 0
                LD   HL, RTYPE_SCHED_PREV
                ADD  HL, DE
                LD   A, (.previous)
                LD   (HL), A
                LD   A, (.index)
                LD   (RTYPE_SCHED_TAIL), A
                RET

.empty:        LD   A, (.index)
                LD   (RTYPE_SCHED_HEAD), A
                LD   (RTYPE_SCHED_TAIL), A
                RET
.index:        DEFB 0
.cursor:       DEFB RTYPE_SCHED_NULL
.previous:     DEFB RTYPE_SCHED_NULL
.priority:     DEFW 0
.serial:       DEFW 0

; Восстановить ordered list только из живых physical records. Штатная
; трансляция сюда не попадает; процедура является fail-safe против порчи
; NEXT/PREV, которая иначе навсегда оставляет Z80 внутри RecordAddress.
RTypeScheduler_Rebuild:
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   A, (RTypeScheduler_RepairCount)
                INC  A
                LD   (RTypeScheduler_RepairCount), A
                LD   A, RTYPE_SCHED_NULL
                LD   (RTYPE_SCHED_HEAD), A
                LD   (RTYPE_SCHED_TAIL), A
                LD   HL, RTYPE_SCHED_NEXT
                LD   DE, RTYPE_SCHED_NEXT + 1
                LD   BC, RTYPE_OBJECT_COUNT * 2 - 1
                LD   (HL), A
                LDIR
                LD   A, 2
.record:       LD   (RTypeScheduler_RebuildIndex), A
                CALL RTypeObjects_RecordAddress
                LD   A, (HL)
                OR   A
                JR   Z, .advance
                LD   A, (RTypeScheduler_RebuildIndex)
                CALL RTypeScheduler_Insert
.advance:      LD   A, (RTypeScheduler_RebuildIndex)
                INC  A
                CP   RTYPE_OBJECT_COUNT
                JR   C, .record
                RET

; A=resource type. Вернуть существующий palette slot, увеличив refs, либо
; занять первый `$FF` slot. Carry=1 и A=$FF означает буквальный отказ `$51EE`.
RTypeResources_Acquire:
                LD   (.resourceType), A
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   HL, RTYPE_RESOURCE_TYPES
                LD   C, 0
.findExisting: LD   A, (HL)
                LD   B, A
                LD   A, (.resourceType)
                CP   B
                JR   Z, .retain
                INC  HL
                INC  C
                LD   A, C
                CP   16
                JR   C, .findExisting
                LD   HL, RTYPE_RESOURCE_TYPES
                LD   C, 0
.findFree:     LD   A, (HL)
                CP   #FF
                JR   Z, .claim
                INC  HL
                INC  C
                LD   A, C
                CP   16
                JR   C, .findFree
                LD   A, #FF
                SCF
                RET
.claim:        LD   A, (.resourceType)
                LD   (HL), A
                LD   A, C
                LD   E, A
                LD   D, 0
                LD   HL, RTYPE_RESOURCE_REFS
                ADD  HL, DE
                LD   (HL), 1
                LD   A, (.resourceType)
                CALL RTypePalette_LoadSprite
                LD   A, (RTypePaletteWorkSlot)
                OR   A
                RET
.retain:       LD   A, C
                LD   E, A
                LD   D, 0
                LD   HL, RTYPE_RESOURCE_REFS
                ADD  HL, DE
                INC  (HL)
                LD   A, C
                OR   A
                RET
.resourceType: DEFB 0

; A=palette slot: уменьшить refs и вернуть type в `$FF` после последнего
; владельца. Значения `$FF` и 16…255, как в оригинале, игнорируются.
RTypeResources_Release:
                CP   16
                RET  NC
                LD   E, A
                LD   D, 0
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   HL, RTYPE_RESOURCE_REFS
                ADD  HL, DE
                LD   A, (HL)
                OR   A
                RET  Z
                DEC  (HL)
                RET  NZ
                LD   HL, RTYPE_RESOURCE_TYPES
                ADD  HL, DE
                LD   (HL), #FF
                RET

; Очистить 15 управляющих записей второго M72 palette-bank. Сами 16-КБ
; ARGB4444 palette types неизменяемы и уже лежат в общей странице stage PAK;
; здесь хранится только живое состояние `$2DF4` для event/fade автоматов.
RTypePalette_Reset:
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   HL, RTYPE_PALETTE_BANK2_RECORDS
                LD   DE, RTYPE_PALETTE_BANK2_RECORDS + 1
                LD   BC, RTYPE_PALETTE_RECORD_COUNT * RTYPE_PALETTE_RECORD_SIZE - 1
                XOR  A
                LD   (HL), A
                LDIR
                RET

; DE=offset варианта внутри общей palette-страницы. Результат HL указывает
; на 32-byte ARGB4444 type, а DMA source page уже подготовлена. Умножение
; type*32 выполняется пятью сдвигами и не требует runtime-конвертации RGB.
RTypePalette_SourcePointer:
                LD   A, (RTypePaletteWorkType)
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, DE
                LD   DE, (RTypeTargetPaletteResourcePtr)
                ADD  HL, DE
                LD   A, (RTypeTargetPaletteResourcePage)
                LD   (RTypeFT_DmaSourcePage), A
                RET

; A=resource type, C=palette slot. Первый acquire немедленно переносит ровно
; 32 bytes готовой sprite palette через TS DMA; повторный acquire того же type
; только увеличивает refs и не занимает полосу FT812 повторно.
RTypePalette_LoadSprite:
                LD   (RTypePaletteWorkType), A
                LD   A, C
                LD   (RTypePaletteWorkSlot), A
                LD   DE, RTYPE_TARGET_PAL_SPRITE
                CALL RTypePalette_SourcePointer
                PUSH HL
                LD   A, (RTypePaletteWorkSlot)
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                LD   DE, RTYPE_WORLD_SPRITE_PALETTE_RAMG & #FFFF
                ADD  HL, DE
                EX   DE, HL
                POP  HL
                LD   BC, RTYPE_TARGET_PAL_TYPE_BYTES
                LD   A, (RTYPE_WORLD_SPRITE_PALETTE_RAMG >> 16) & #FF
                JP   RTypeFT_WriteMemDMA

; A=tile palette type, C=slot, DE=fade/cadence mask. Управляющая запись
; совпадает с `$54E4`: active type, gradual mode, mask и threshold `$1F`.
; Цветовые значения уже предвычислены; текущая реализация сразу отдаёт FT812
; конечный RGB, сохраняя при этом точное состояние автомата для последующего
; покомпонентного convergence без изменения формата PAK.
RTypePalette_SetTile:
                LD   (RTypePaletteWorkType), A
                LD   A, C
                LD   (RTypePaletteWorkSlot), A
                LD   (RTypePaletteWorkMask), DE
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   A, (RTypePaletteWorkSlot)
                LD   L, A
                LD   H, 0
                LD   D, H
                LD   E, L
                ADD  HL, HL
                ADD  HL, DE
                ADD  HL, HL
                ADD  HL, HL                     ; slot * 12
                LD   DE, RTYPE_PALETTE_BANK2_RECORDS
                ADD  HL, DE
                LD   A, (RTypePaletteWorkType)
                LD   (HL), A
                INC  HL
                LD   (HL), #80                   ; bit15 active
                INC  HL
                XOR  A
                LD   (HL), A                     ; changed count пересчитает fade
                INC  HL
                LD   (HL), A
                INC  HL
                INC  A
                LD   (HL), A                     ; gradual mode = 1
                INC  HL
                XOR  A
                LD   (HL), A
                INC  HL
                LD   (HL), A                     ; dirty = 0 до первого шага
                INC  HL
                LD   (HL), A
                INC  HL
                LD   DE, (RTypePaletteWorkMask)
                LD   (HL), E
                INC  HL
                LD   (HL), D
                INC  HL
                LD   (HL), #1F
                INC  HL
                LD   (HL), 0

                LD   DE, RTYPE_TARGET_PAL_TILE_OPAQUE
                CALL RTypePalette_SourcePointer
                PUSH HL
                CALL RTypePalette_TileDestination
                POP  HL
                LD   BC, RTYPE_TARGET_PAL_TYPE_BYTES
                LD   A, (RTYPE_WORLD_TILE_PALETTE_RAMG >> 16) & #FF
                CALL RTypeFT_WriteMemDMA

                LD   DE, RTYPE_TARGET_PAL_TILE_ALPHA
                CALL RTypePalette_SourcePointer
                PUSH HL
                CALL RTypePalette_TileDestination
                LD   BC, 512
                EX   DE, HL
                ADD  HL, BC
                EX   DE, HL
                POP  HL
                LD   BC, RTYPE_TARGET_PAL_TYPE_BYTES
                LD   A, (RTYPE_WORLD_TILE_PALETTE_RAMG >> 16) & #FF
                JP   RTypeFT_WriteMemDMA

; Вернуть DE=начало opaque tile-slot в RAM_G.
RTypePalette_TileDestination:
                LD   A, (RTypePaletteWorkSlot)
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                LD   DE, RTYPE_WORLD_TILE_PALETTE_RAMG & #FFFF
                ADD  HL, DE
                EX   DE, HL
                RET

; `$EDD9`: фиксированный seed `$03_01_05`. Состояние лежит рядом с object
; manager в page #09 и не зависит от того, какую pack-страницу оставил slot3.
RTypeRng_Reset:
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   A, 5
                LD   (RTYPE_RNG_A), A
                LD   A, 1
                LD   (RTYPE_RNG_B), A
                LD   A, 3
                LD   (RTYPE_RNG_C), A
                RET

; `$EDE9`: newA=oldB+oldC, newB=oldA, newC=oldB. Возврат HL содержит
; `newA | oldC<<8`, ровно как AX исходного V30 и Python oracle.
RTypeRng_Next:
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   A, (RTYPE_RNG_A)
                LD   D, A                        ; old A
                LD   A, (RTYPE_RNG_B)
                LD   E, A                        ; old B
                LD   A, (RTYPE_RNG_C)
                LD   H, A                        ; old C / high результата
                ADD  A, E
                LD   L, A                        ; new A / low результата
                LD   (RTYPE_RNG_A), A
                LD   A, D
                LD   (RTYPE_RNG_B), A
                LD   A, E
                LD   (RTYPE_RNG_C), A
                RET

; Прочитать byte из 64-КБ сегмента ES World ROM. Вход HL — исходный 16-битный
; адрес ROM; выход A — byte. Старшие два бита H выбирают одну из четырёх
; pack-страниц, младшие 14 бит превращаются в адрес slot3 #C000…#FFFF.
RTypeWorldRom_ReadByte:
                LD   A, H
                AND  #C0
                RLCA
                RLCA
                ADD  A, RTYPE_WORLD_ROM_BASE_PAGE
                SetPage3_A
                LD   A, H
                AND  #3F
                OR   #C0
                LD   H, A
                LD   A, (HL)
                RET

; HL=ROM address. Вернуть little-endian word в DE; чтение каждого byte
; отображает страницу заново, поэтому слово корректно и на границе #3FFF.
RTypeWorldRom_ReadWord:
                LD   (.wordAddress), HL
                CALL RTypeWorldRom_ReadByte
                LD   E, A
                LD   HL, (.wordAddress)
                INC  HL
                CALL RTypeWorldRom_ReadByte
                LD   D, A
                RET
.wordAddress:  DEFW 0

; BC=native object X, DE=native object Y. Вернуть HL=foreground tile code
; `$0000…$0FFF` по буквальной адресной арифметике `$1E6C`. Функция читает
; живую ring-карту page #07 после текущего scroll-интегратора, то есть именно
; тот collision-domain, который видят object handlers этого VBlank.
RTypeTerrain_ForegroundCode:
                LD   (RTypeTerrain_ObjectX), BC
                LD   (RTypeTerrain_ObjectY), DE
                LD   HL, (RTypeWorldFgScrollQ8 + 1)
                LD   A, L
                AND  7
                LD   (RTypeTerrain_Subcolumn), A
                SRL  H
                RR   L
                LD   A, L
                AND  #FC
                LD   L, A
                LD   H, 0                       ; `(scroll_x >> 1) & $00FC`
                LD   DE, #1020
                ADD  HL, DE
                LD   (RTypeTerrain_Address), HL
                LD   HL, (RTypeTerrain_ObjectX)
                LD   A, (RTypeTerrain_Subcolumn)
                LD   E, A
                LD   D, 0
                ADD  HL, DE
                LD   DE, -#0140
                ADD  HL, DE                     ; unsigned wrap сохраняется
                SRL  H
                RR   L
                LD   A, L
                AND  #FC
                LD   L, A                       ; `(horizontal >> 1) & $FFFC`
                LD   DE, (RTypeTerrain_Address)
                ADD  HL, DE
                LD   A, H
                AND  #10
                LD   H, A                       ; ring column mask `$10FF`
                LD   (RTypeTerrain_Address), HL

                LD   HL, (RTypeWorldFgYScrollQ8 + 1)
                LD   A, L
                AND  7
                LD   (RTypeTerrain_Subrow), A
                ; `(scroll_y << 5) & $3F00`: после сдвига low byte всегда 0,
                ; high byte равен младшим шести битам `scroll_y >> 3`.
                SRL  H
                RR   L
                SRL  H
                RR   L
                SRL  H
                RR   L
                LD   A, L
                AND  #3F
                LD   D, A
                LD   E, 0
                LD   HL, (RTypeTerrain_Address)
                ADD  HL, DE
                LD   (RTypeTerrain_Address), HL

                LD   HL, #017F
                LD   A, (RTypeTerrain_Subrow)
                LD   E, A
                LD   D, 0
                ADD  HL, DE
                LD   DE, (RTypeTerrain_ObjectY)
                OR   A
                SBC  HL, DE
                JR   NC, .verticalReady
                LD   HL, 0                       ; отрицательный vertical clamp
.verticalReady:
                LD   A, L
                AND  #F8
                LD   L, A
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL                     ; `(vertical & $FFF8) << 5`
                LD   DE, (RTypeTerrain_Address)
                ADD  HL, DE
                LD   A, H
                AND  #3F
                LD   H, A
                LD   (RTypeTerrain_Address), HL   ; byte offset `$0000..$3FFF`
                LD   A, H
                OR   #C0
                LD   H, A
                LD   A, RTYPE_WORLD_FG_MAP_PAGE
                SetPage3_A
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                LD   A, D
                AND  #0F
                LD   H, A
                LD   L, E
                RET

RTypeTerrain_ObjectX:    DEFW 0
RTypeTerrain_ObjectY:    DEFW 0
RTypeTerrain_Address:    DEFW 0
RTypeTerrain_Subcolumn:  DEFB 0
RTypeTerrain_Subrow:     DEFB 0

; BC=native object X, DE=native object Y. `$1EB5` повторяет ту же ring-
; арифметику, что `$1E6C`, но использует background X/Y scroll и page #08.
; Дублирование здесь намеренное: foreground handler обязан оставить page #07,
; background handler — page #08, а объектный hot path не платит за косвенные
; указатели и повторное отображение страницы после каждого промежуточного шага.
RTypeTerrain_BackgroundCode:
                LD   (RTypeTerrain_ObjectX), BC
                LD   (RTypeTerrain_ObjectY), DE
                LD   HL, (RTypeWorldBgScrollQ8 + 1)
                LD   A, L
                AND  7
                LD   (RTypeTerrain_Subcolumn), A
                SRL  H
                RR   L
                LD   A, L
                AND  #FC
                LD   L, A
                LD   H, 0                       ; `(background_x >> 1) & $00FC`
                LD   DE, #1020
                ADD  HL, DE
                LD   (RTypeTerrain_Address), HL
                LD   HL, (RTypeTerrain_ObjectX)
                LD   A, (RTypeTerrain_Subcolumn)
                LD   E, A
                LD   D, 0
                ADD  HL, DE
                LD   DE, -#0140
                ADD  HL, DE
                SRL  H
                RR   L
                LD   A, L
                AND  #FC
                LD   L, A
                LD   DE, (RTypeTerrain_Address)
                ADD  HL, DE
                LD   A, H
                AND  #10
                LD   H, A
                LD   (RTypeTerrain_Address), HL

                LD   HL, (RTypeWorldBgYScrollQ8 + 1)
                LD   A, L
                AND  7
                LD   (RTypeTerrain_Subrow), A
                SRL  H
                RR   L
                SRL  H
                RR   L
                SRL  H
                RR   L
                LD   A, L
                AND  #3F
                LD   D, A
                LD   E, 0
                LD   HL, (RTypeTerrain_Address)
                ADD  HL, DE
                LD   (RTypeTerrain_Address), HL

                LD   HL, #017F
                LD   A, (RTypeTerrain_Subrow)
                LD   E, A
                LD   D, 0
                ADD  HL, DE
                LD   DE, (RTypeTerrain_ObjectY)
                OR   A
                SBC  HL, DE
                JR   NC, .verticalReady
                LD   HL, 0
.verticalReady:
                LD   A, L
                AND  #F8
                LD   L, A
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                LD   DE, (RTypeTerrain_Address)
                ADD  HL, DE
                LD   A, H
                AND  #3F
                OR   #C0
                LD   H, A
                LD   A, RTYPE_WORLD_BG_MAP_PAGE
                SetPage3_A
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                LD   A, D
                AND  #0F
                LD   H, A
                LD   L, E
                RET

; Прочитать следующий byte через локальный ROM cursor descriptor-ридера.
RTypeSprite_ReadNext:
                LD   HL, (RTypeSprite_RomCursor)
                INC  HL
                LD   (RTypeSprite_RomCursor), HL
                DEC  HL
                JP   RTypeWorldRom_ReadByte

; HL=адрес шестибайтного descriptor. Разобрать signed offsets, code, attr и
; вычислить базовую нативную позицию из сохранённых anchor X/Y.
RTypeSprite_ReadDescriptor:
                LD   (RTypeSprite_RomCursor), HL
                CALL RTypeSprite_ReadNext
                LD   L, A
                LD   H, 0
                BIT  7, L
                JR   Z, .dxReady
                DEC  H
.dxReady:      LD   DE, (RTypeSprite_AnchorX)
                ADD  HL, DE
                LD   DE, -320
                ADD  HL, DE
                LD   (RTypeSprite_BaseX), HL
                CALL RTypeSprite_ReadNext
                LD   L, A
                LD   H, 0
                BIT  7, L
                JR   Z, .dyReady
                DEC  H
.dyReady:      LD   DE, (RTypeSprite_AnchorY)
                ADD  HL, DE
                LD   (RTypeSprite_AnchorPlusDy), HL
                CALL RTypeSprite_ReadNext
                LD   E, A
                CALL RTypeSprite_ReadNext
                LD   D, A
                LD   (RTypeSprite_Code), DE
                CALL RTypeSprite_ReadNext
                LD   E, A
                CALL RTypeSprite_ReadNext
                LD   D, A
                LD   (RTypeSprite_Attr), DE
                LD   A, D
                AND  #C0
                RLCA
                RLCA
                LD   B, A                        ; log2 width
                LD   A, 1
.width:        LD   C, A
                LD   A, B
                OR   A
                LD   A, C
                JR   Z, .widthReady
.widthShift:   ADD  A, A
                DJNZ .widthShift
.widthReady:   LD   (RTypeSprite_Width), A
                LD   A, D
                AND  #30
                RRCA
                RRCA
                RRCA
                RRCA
                LD   B, A                        ; log2 height
                LD   A, 1
.height:       LD   C, A
                LD   A, B
                OR   A
                LD   A, C
                JR   Z, .heightReady
.heightShift:  ADD  A, A
                DJNZ .heightShift
.heightReady:  LD   (RTypeSprite_Height), A
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL                     ; 16 * descriptor.height
                EX   DE, HL
                LD   HL, 384
                OR   A
                SBC  HL, DE
                LD   DE, (RTypeSprite_AnchorPlusDy)
                OR   A
                SBC  HL, DE
                LD   (RTypeSprite_BaseY), HL
                RET

; HL=descriptor address: загрузить все sprite chunks, затрагиваемые его
; составными cells. В update-пути это выполняется до FT_CMD_Start, поэтому
; CMD_INFLATE никогда не разрывает строящийся display list.
RTypeSprite_PrepareDescriptor:
                LD   (RTypeSprite_Descriptor), HL
                XOR  A
                LD   (RTypeSprite_AnchorX), A
                LD   (RTypeSprite_AnchorX + 1), A
                LD   (RTypeSprite_AnchorY), A
                LD   (RTypeSprite_AnchorY + 1), A
                CALL RTypeSprite_ReadDescriptor
                XOR  A
                LD   (RTypeSprite_CellX), A
.column:       XOR  A
                LD   (RTypeSprite_CellY), A
.row:          CALL RTypeSprite_CellCode
                ; Backend сгенерирован непосредственно из Python cell-loop:
                ; в cache попадает ровно текущий code, без chunk-вытеснения.
                CALL RTypeSpriteCache_LoadCell
                RET  C
                LD   A, (RTypeSprite_CellY)
                INC  A
                LD   (RTypeSprite_CellY), A
                LD   B, A
                LD   A, (RTypeSprite_Height)
                CP   B
                JR   NZ, .row
                LD   A, (RTypeSprite_CellX)
                INC  A
                LD   (RTypeSprite_CellX), A
                LD   B, A
                LD   A, (RTypeSprite_Width)
                CP   B
                JR   NZ, .column
                OR   A
                RET

; Рассчитать исходный cell code с учётом flip. Возвращает HL=code&$0FFF.
RTypeSprite_CellCode:
                LD   A, (RTypeSprite_CellX)
                LD   B, A
                LD   A, (RTypeSprite_Attr + 1)
                AND  #08
                JR   Z, .sourceXReady
                LD   A, (RTypeSprite_Width)
                DEC  A
                SUB  B
                LD   B, A
.sourceXReady: LD   A, B
                ADD  A, A
                ADD  A, A
                ADD  A, A
                LD   C, A                        ; source_x * 8
                LD   A, (RTypeSprite_CellY)
                LD   B, A
                LD   A, (RTypeSprite_Attr + 1)
                AND  #04
                JR   Z, .sourceYReady
                LD   A, (RTypeSprite_Height)
                DEC  A
                SUB  B
                LD   B, A
.sourceYReady: LD   A, C
                ADD  A, B
                LD   E, A
                LD   D, 0
                LD   HL, (RTypeSprite_Code)
                ADD  HL, DE
                LD   A, H
                AND  #0F
                LD   H, A
                RET

; HL=signed native X. Вернуть BC=round(X*64/3), то есть VERTEX_FORMAT-3
; units для physical масштаба 384→1024. Видимый диапазон -512…767 читается
; из постоянной 2.5-КБ таблицы page #00; арифметика оставлена лишь защитным
; путём для полностью ушедших за экран служебных координат.
RTypeSprite_NativeXToVertex:
                LD   DE, -RTYPE_VERTEX_X_FIRST
                ADD  HL, DE
                LD   A, H
                CP   RTYPE_VERTEX_X_COUNT >> 8
                JR   NC, .tableMiss
                ADD  HL, HL
                LD   DE, RTypeVertexXTable
                ADD  HL, DE
                LD   C, (HL)
                INC  HL
                LD   B, (HL)
                RET
.tableMiss:    LD   DE, RTYPE_VERTEX_X_FIRST
                ADD  HL, DE                     ; восстановить signed native X
                BIT  7, H
                JR   Z, .positive
                ; Модуль signed word считаем через NOT+1. Последовательность
                ; `SUB low / XOR A / SBC high` здесь неверна: XOR уничтожает
                ; borrow от младшего байта и даёт ошибку для большинства X.
                LD   A, L
                CPL
                LD   L, A
                LD   A, H
                CPL
                LD   H, A
                INC  HL
                CALL .unsigned
                LD   A, C
                CPL
                LD   C, A
                LD   A, B
                CPL
                LD   B, A
                INC  BC
                RET
.positive:     CALL .unsigned
                RET
.unsigned:     ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                INC  HL
                LD   DE, 0                       ; unsigned quotient
                XOR  A                           ; remainder 0…2
                LD   B, 16
.divide:       ADD  HL, HL
                RLA
                SLA  E
                RL   D
                CP   3
                JR   C, .nextBit
                SUB  3
                INC  E                           ; установить младший quotient bit
.nextBit:      DJNZ .divide
                LD   B, D
                LD   C, E
                RET

; HL=signed native Y. Вернуть BC=Y*24. Основной диапазон -256…511 также
; предвычислен; старое умножение остаётся только для невидимого overflow.
RTypeSprite_NativeYToVertex:
                LD   DE, -RTYPE_VERTEX_Y_FIRST
                ADD  HL, DE
                LD   A, H
                CP   RTYPE_VERTEX_Y_COUNT >> 8
                JR   NC, .tableMiss
                ADD  HL, HL
                LD   DE, RTypeVertexYTable
                ADD  HL, DE
                LD   C, (HL)
                INC  HL
                LD   B, (HL)
                RET
.tableMiss:    LD   DE, RTYPE_VERTEX_Y_FIRST
                ADD  HL, DE                     ; восстановить signed native Y
                LD   D, H
                LD   E, L
                ADD  HL, HL                      ; x2
                ADD  HL, HL                      ; x4
                ADD  HL, HL                      ; x8
                ADD  HL, HL                      ; x16
                EX   DE, HL                      ; DE=x16, HL=исходное значение
                ADD  HL, HL                      ; x2
                ADD  HL, HL                      ; x4
                ADD  HL, HL                      ; x8
                ADD  HL, DE                      ; x24
                LD   B, H
                LD   C, L
                RET

; HL=descriptor, BC=anchor X, DE=anchor Y, A=palette slot. Нарисовать все
; cells напрямую из on-demand cache. Вызывающий обязан подготовить descriptor
; в update; защитный cache lookup здесь обычно является дешёвым hit.
RTypeSprite_DrawDescriptor:
                LD   (RTypeSprite_Descriptor), HL
                LD   (RTypeSprite_AnchorX), BC
                LD   (RTypeSprite_AnchorY), DE
                LD   (RTypeSprite_Palette), A
                CALL RTypeSprite_ReadDescriptor
                FT_ColorRGB 255, 255, 255
                LD   A, (RTypeSprite_Attr + 1)
                AND  #08
                JR   NZ, .flipX
                FT_BitmapTransformA 96
                FT_BitmapTransformC 0
                JR   .xTransformReady
.flipX:        FT_BitmapTransformA -96
                FT_BitmapTransformC 4095
.xTransformReady:
                LD   A, (RTypeSprite_Attr + 1)
                AND  #04
                JR   NZ, .flipY
                FT_BitmapTransformE 85
                FT_BitmapTransformF 0
                JR   .yTransformReady
.flipY:        FT_BitmapTransformE -85
                FT_BitmapTransformF 4095
.yTransformReady:
                FT_BitmapTransformB 0
                FT_BitmapTransformD 0
                LD   A, (RTypeSprite_Palette)
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL                     ; palette * 32 bytes
                LD   DE, RTYPE_WORLD_SPRITE_PALETTE_RAMG & #FFFF
                ADD  HL, DE
                LD   E, L
                LD   D, H
                LD   C, (RTYPE_WORLD_SPRITE_PALETTE_RAMG >> 16) & #FF
                LD   B, #2A                     ; PALETTE_SOURCE dynamic
                CALL FT.Coprocessor.Command_BCDE
                FT_BitmapLayout FT_PALETTED4444, 16, 16
                FT_BitmapSize FT_NEAREST, FT_BORDER, FT_BORDER, 43, 49
                FT_Begin FT_BITMAPS
                XOR  A
                LD   (RTypeSprite_CellX), A
.column:       ; X одинаков для всех cells одного столбца. Старая версия
                ; заново выполняла 16-шаговое деление в каждой строке.
                LD   A, (RTypeSprite_CellX)
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL                     ; cell_x * 16 native
                LD   DE, (RTypeSprite_BaseX)
                ADD  HL, DE
                CALL RTypeSprite_NativeXToVertex
                LD   (RTypeSprite_VertexX), BC
                ; Y масштабируется точно на 24 единицы VERTEX_FORMAT-3 за
                ; native pixel, поэтому между 16px строками достаточно +384.
                LD   HL, (RTypeSprite_BaseY)
                CALL RTypeSprite_NativeYToVertex
                LD   (RTypeSprite_AnchorPlusDy), BC
                XOR  A
                LD   (RTypeSprite_CellY), A
.row:          CALL RTypeSprite_EmitCell
                LD   HL, (RTypeSprite_AnchorPlusDy)
                LD   DE, 16 * 24
                ADD  HL, DE
                LD   (RTypeSprite_AnchorPlusDy), HL
                LD   A, (RTypeSprite_CellY)
                INC  A
                LD   (RTypeSprite_CellY), A
                LD   B, A
                LD   A, (RTypeSprite_Height)
                CP   B
                JR   NZ, .row
                LD   A, (RTypeSprite_CellX)
                INC  A
                LD   (RTypeSprite_CellX), A
                LD   B, A
                LD   A, (RTypeSprite_Width)
                CP   B
                JR   NZ, .column
                FT_End
                RET

; Выдать BITMAP_SOURCE и VERTEX2F одной cell текущего descriptor.
RTypeSprite_EmitCell:
                CALL RTypeSprite_CellCode
                CALL RTypeSpriteCache_LoadCell
                RET  C
                ; absolute slot * 256 в RAM_G #0C0000…#0FFFFF.
                LD   A, H
                ADD  A, (RTYPE_PY_SPRITE_CACHE_RAMG >> 16) & #FF
                LD   D, L
                LD   E, 0
                LD   C, A
                LD   B, #01                     ; BITMAP_SOURCE dynamic
                CALL FT.Coprocessor.Command_BCDE
                LD   BC, (RTypeSprite_VertexX)
                LD   DE, (RTypeSprite_AnchorPlusDy)
                JP   FT.Coprocessor.Vertex2f

; Очистить резидентный снимок перед конструированием новой записи. Нельзя
; полагаться только на очищенную page #09: scratch мог содержать предыдущий
; объект, а initializer заполняет лишь принадлежащие ему offsets.
RTypeObjects_ClearScratch:
                XOR  A
                LD   HL, RTYPE_OBJECT_SCRATCH
                LD   DE, RTYPE_OBJECT_SCRATCH + 1
                LD   BC, RTYPE_OBJECT_REC_SIZE - 1
                LD   (HL), A
                LDIR
                RET

; Выделить новую запись и сделать её текущей. Carry=1 означает исчерпание
; 94 игровых slots; успешный путь возвращает A=индекс и чистый scratch.
RTypeObjects_New:
                CALL RTypeObjects_Take
                RET  C
                LD   (RTypeObjects_CurrentIndex), A
                PUSH AF
                CALL RTypeObjects_ClearScratch
                POP  AF
                OR   A
                RET

RTypeObjects_CommitCurrent:
                LD   A, (RTypeObjects_CurrentIndex)
                JP   RTypeObjects_StoreScratch

; ---------------------------------------------------------------------------
; Постоянно видимые helpers для object banks.
;
; Slot2 `$8000…$BFFF` на время bank-handler-а содержит page #0A…#0D, а не
; вторую страницу Core. Поэтому любая процедура, которую bank вызывает
; напрямую, обязана физически лежать ниже `$8000`. Этот блок намеренно стоит
; перед trampolines: рост диспетчера/scheduler-а больше не может незаметно
; превратить, например, `CALL RTypeProjectile_AddQ8X` в прыжок по тому же
; адресу внутри object_bank3. Проверка сборки отдельно контролирует эту
; границу для всех четырёх bank-файлов.

; Интерпретатор `$F5C1`. Carry=1 означает конец списка streams; обычный
; возврат после смены stream или двух movement commands очищает Carry.
RTypeObjects_ScriptedMotion:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT_COMMANDS)
                LD   (RTypeObjects_MotionRemaining), A
.command:      LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT_PTR)
                CALL RTypeWorldRom_ReadByte
                LD   (RTypeObjects_MotionCommand), A
                BIT  7, A
                JR   Z, .movement
                AND  #1F
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOTION_PHASE), A
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOTION_PHASE + 1), A
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT_PTR)
                INC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT_PTR), HL
                JR   .command                     ; phase не расходует command
.movement:     LD   A, (RTypeObjects_MotionCommand)
                BIT  6, A
                JR   Z, .positiveX
                BIT  5, A
                JR   Z, .vertical
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                JR   .vertical
.positiveX:    BIT  5, A
                JR   Z, .vertical
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                INC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
.vertical:     LD   A, (RTypeObjects_MotionCommand)
                BIT  4, A
                JR   Z, .positiveY
                BIT  3, A
                JR   Z, .endFlag
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL
                JR   .endFlag
.positiveY:    BIT  3, A
                JR   Z, .endFlag
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                INC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL
.endFlag:      LD   A, (RTypeObjects_MotionCommand)
                BIT  2, A
                JR   Z, .advance
.nextStream:   LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT)
                INC  HL
                INC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT), HL
                CALL RTypeWorldRom_ReadWord
                LD   A, D
                OR   E
                JR   NZ, .streamWord
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT)
                INC  HL
                INC  HL
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT), DE
                EX   DE, HL
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT_PTR), DE
                SCF
                RET
.streamWord:   LD   A, D
                CP   #F0
                JR   NZ, .selectStream
                LD   A, E
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT_COMMANDS), A
                JR   .nextStream
.selectStream: LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT_PTR), DE
                OR   A
                RET
.advance:      LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT_PTR)
                INC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT_PTR), HL
                LD   HL, RTypeObjects_MotionRemaining
                DEC  (HL)
                JP   NZ, .command
                OR   A
                RET

; Общая `$F63A` часть. Z означает кадр projectile request; counter при
; равенстве fire_a намеренно не сбрасывается, при достижении fire_b становится
; нулём. Вызывающий по Z немедленно создаёт и исполняет `$E601`.
RTypeObjects_AdvanceFireCounter:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FIRE_COUNTER)
                INC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FIRE_COUNTER), HL
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FIRE_A)
                OR   A
                SBC  HL, DE
                RET  Z
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FIRE_COUNTER)
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FIRE_B)
                OR   A
                SBC  HL, DE
                JR   C, .noTrigger
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FIRE_COUNTER), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FIRE_COUNTER + 1), A
                RET                              ; Z=1: upper-limit trigger
.noTrigger:    OR   1                            ; NZ
                RET

; Классифицировать signed HL для углового `$1D89`: A=0 при HL<0, A=1 при
; 0…$3F, A=2 при HL>=$40. Пороговые неравенства различают 16 направлений.
RTypeDirection_Classify:
                BIT  7, H
                JR   Z, .nonNegative
                XOR  A
                RET
.nonNegative:  LD   A, H
                OR   A
                JR   NZ, .large
                LD   A, L
                CP   #40
                JR   NC, .large
                LD   A, 1
                RET
.large:        LD   A, 2
                RET

; Source/target берутся из резидентных слов. Возврат A — byte offset
; `$00,$04…$3C` в таблице пар signed Q8 velocities.
RTypeDirection_Offset:
                LD   HL, (RTypeObjects_ProjectileSourceY)
                LD   DE, 8
                ADD  HL, DE
                LD   DE, (RTypePlayerNativeY)
                OR   A
                SBC  HL, DE
                JR   C, .targetBelow
                LD   HL, (RTypeObjects_ProjectileSourceY)
                LD   DE, 8
                OR   A
                SBC  HL, DE
                LD   DE, (RTypePlayerNativeY)
                OR   A
                SBC  HL, DE
                JP   NC, .targetAbove
                LD   HL, (RTypeObjects_ProjectileSourceX)
                LD   DE, (RTypePlayerNativeX)
                OR   A
                SBC  HL, DE
                LD   A, #30
                RET  NC
                LD   A, #10
                RET

.targetBelow:  LD   HL, (RTypeObjects_ProjectileSourceX)
                LD   DE, 8
                ADD  HL, DE
                LD   DE, (RTypePlayerNativeX)
                OR   A
                SBC  HL, DE
                JR   C, .belowRight
                LD   HL, (RTypeObjects_ProjectileSourceX)
                LD   DE, 8
                OR   A
                SBC  HL, DE
                LD   DE, (RTypePlayerNativeX)
                OR   A
                SBC  HL, DE
                JR   NC, .belowLeft
                XOR  A
                RET
.belowRight:   LD   HL, (RTypePlayerNativeX)
                LD   DE, (RTypeObjects_ProjectileSourceX)
                OR   A
                SBC  HL, DE
                PUSH HL
                LD   HL, (RTypePlayerNativeY)
                LD   DE, (RTypeObjects_ProjectileSourceY)
                OR   A
                SBC  HL, DE
                EX   DE, HL
                POP  HL
                OR   A
                SBC  HL, DE
                LD   DE, #0020
                ADD  HL, DE
                CALL RTypeDirection_Classify
                OR   A
                JR   Z, .belowRightNegative
                CP   1
                JR   Z, .belowRightMiddle
                LD   A, #0C
                RET
.belowRightNegative:
                LD   A, #04
                RET
.belowRightMiddle:
                LD   A, #08
                RET
.belowLeft:    LD   HL, (RTypeObjects_ProjectileSourceX)
                LD   DE, (RTypePlayerNativeX)
                OR   A
                SBC  HL, DE
                PUSH HL
                LD   HL, (RTypePlayerNativeY)
                LD   DE, (RTypeObjects_ProjectileSourceY)
                OR   A
                SBC  HL, DE
                EX   DE, HL
                POP  HL
                OR   A
                SBC  HL, DE
                LD   DE, #0020
                ADD  HL, DE
                CALL RTypeDirection_Classify
                OR   A
                JR   Z, .belowLeftNegative
                CP   1
                JR   Z, .belowLeftMiddle
                LD   A, #34
                RET
.belowLeftNegative:
                LD   A, #3C
                RET
.belowLeftMiddle:
                LD   A, #38
                RET

.targetAbove:  LD   HL, (RTypeObjects_ProjectileSourceX)
                LD   DE, 8
                ADD  HL, DE
                LD   DE, (RTypePlayerNativeX)
                OR   A
                SBC  HL, DE
                JR   C, .aboveRight
                LD   HL, (RTypeObjects_ProjectileSourceX)
                LD   DE, 8
                OR   A
                SBC  HL, DE
                LD   DE, (RTypePlayerNativeX)
                OR   A
                SBC  HL, DE
                JR   NC, .aboveLeft
                LD   A, #20
                RET
.aboveRight:   LD   HL, (RTypePlayerNativeX)
                LD   DE, (RTypeObjects_ProjectileSourceX)
                OR   A
                SBC  HL, DE
                PUSH HL
                LD   HL, (RTypeObjects_ProjectileSourceY)
                LD   DE, (RTypePlayerNativeY)
                OR   A
                SBC  HL, DE
                EX   DE, HL
                POP  HL
                OR   A
                SBC  HL, DE
                LD   DE, #0020
                ADD  HL, DE
                CALL RTypeDirection_Classify
                OR   A
                JR   Z, .aboveRightNegative
                CP   1
                JR   Z, .aboveRightMiddle
                LD   A, #14
                RET
.aboveRightNegative:
                LD   A, #1C
                RET
.aboveRightMiddle:
                LD   A, #18
                RET
.aboveLeft:    LD   HL, (RTypeObjects_ProjectileSourceX)
                LD   DE, (RTypePlayerNativeX)
                OR   A
                SBC  HL, DE
                PUSH HL
                LD   HL, (RTypeObjects_ProjectileSourceY)
                LD   DE, (RTypePlayerNativeY)
                OR   A
                SBC  HL, DE
                EX   DE, HL
                POP  HL
                OR   A
                SBC  HL, DE
                LD   DE, #0020
                ADD  HL, DE
                CALL RTypeDirection_Classify
                OR   A
                JR   Z, .aboveLeftNegative
                CP   1
                JR   Z, .aboveLeftMiddle
                LD   A, #2C
                RET
.aboveLeftNegative:
                LD   A, #24
                RET
.aboveLeftMiddle:
                LD   A, #28
                RET

; `$F63A -> $E601`: сохранить source, выделить A000-record и выполнить его
; первый Q8 pass немедленно, потому что новый priority строго позже текущего.
RTypeObjects_SpawnProjectileFromCurrent:
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
                LD   A, RTYPE_OBJ_ENEMY_PROJECTILE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                ; Только `$E601` просит allocator сохранить Q8 residue нового
                ; физического slot. Это важно после первого оборота FIFO.
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
                CALL RTypeObjects_UpdateEnemyProjectileCore
                CALL RTypeObjects_CommitCurrent
.restore:      LD   A, (RTypeObjects_ParentIndex)
                LD   (RTypeObjects_CurrentIndex), A
                JP   RTypeObjects_LoadScratch

RTypeObjects_UpdateEnemyProjectile:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PROJECTILE_BORN)
                LD   DE, (FrameCounter)
                OR   A
                SBC  HL, DE
                RET  Z                           ; immediate pass уже сделан source-ом
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PROJECTILE_BURST)
                LD   A, H
                OR   L
                JR   NZ, RTypeProjectile_UpdateBurst

RTypeObjects_UpdateEnemyProjectileCore:
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY)
                CALL RTypeProjectile_AddQ8X
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY)
                CALL RTypeProjectile_AddQ8Y
                LD   HL, (FrameCounter)
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PROJECTILE_PHASE)
                ADD  HL, DE
                LD   A, L
                AND  #18
                LD   B, A
                SRL  A
                LD   C, A
                LD   A, B
                SRL  A
                SRL  A
                ADD  A, C
                LD   L, A
                LD   H, 0
                LD   DE, #84AE
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                CALL RTypeSprite_PrepareDescriptor
                LD   A, (FrameCounter)
                INC  A
                AND  1
                RET  NZ
                LD   BC, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                CALL RTypeTerrain_ForegroundCode
                LD   DE, #0DFC
                OR   A
                SBC  HL, DE
                JR   C, .burst
                LD   BC, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                CALL RTypeTerrain_BackgroundCode
                LD   DE, #07D0
                OR   A
                SBC  HL, DE
                JR   C, .burst
                CALL RTypeProjectile_InsideBounds
                RET  NC
                JP   RTypeProjectile_Remove
.burst:        LD   HL, #000A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PROJECTILE_BURST), HL
                RET

; `$E686`: локальный десятикадровый распад projectile. Resource `$56` всё
; время остаётся захваченным; descriptor идёт по убывающему timer и только
; после кадра с timer=1 запись возвращается в FIFO.
RTypeProjectile_UpdateBurst:
                LD   A, L
                AND  #0E
                LD   L, A
                LD   H, 0
                LD   D, H
                LD   E, L
                ADD  HL, HL
                ADD  HL, DE                       ; `(timer & $0E) * 3`
                LD   DE, #8490
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                CALL RTypeSprite_PrepareDescriptor
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PROJECTILE_BURST)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PROJECTILE_BURST), HL
                LD   A, H
                OR   L
                RET  NZ
                JP   RTypeProjectile_Remove

RTypeProjectile_AddQ8X:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_FRACTION)
                LD   L, A
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   H, A
                ADD  HL, DE
                LD   A, L
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_FRACTION), A
                LD   A, H
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), A
                LD   HL, RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X + 1
                JR   RTypeProjectile_AddQ8High
RTypeProjectile_AddQ8Y:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_FRACTION)
                LD   L, A
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   H, A
                ADD  HL, DE
                LD   A, L
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_FRACTION), A
                LD   A, H
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), A
                LD   HL, RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y + 1
RTypeProjectile_AddQ8High:
                LD   C, 0
                BIT  7, D
                JR   Z, .signReady
                DEC  C
.signReady:    LD   A, (HL)
                ADC  A, C
                LD   (HL), A
                RET

RTypeProjectile_InsideBounds:
                CALL RTypeWalker_InsideBounds
                RET

RTypeProjectile_Remove:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                SCF
                RET

; Carry=0 только внутри unsigned native rectangle `$1D6B`.
RTypeWalker_InsideBounds:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, #012C
                OR   A
                SBC  HL, DE
                JR   C, .outside
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, #02D4
                OR   A
                SBC  HL, DE
                JR   NC, .outside
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   DE, #007C
                OR   A
                SBC  HL, DE
                JR   C, .outside
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   DE, #0194
                OR   A
                SBC  HL, DE
                JR   NC, .outside
                OR   A
                RET
.outside:      SCF
                RET

; Один вход тяжёлого `$F493/$F548/$F578` collision-dispatcher-а. Весь scan,
; таблицы и подсчёт Wave живут в свободной page #E5; resident Core платит
; только за два переключения slot2 и не раздувает кадр FT812.
RTypeCollision_Update:
                LD   A, RTYPE_COLLISION_BANK_PAGE
                SetPage2_A
                CALL RTypeCollisionBank_Update
                LD   A, CorePage + 1
                SetPage2_A
                RET

; Вызвать damage-handler из другого object bank и вернуться именно в #E5.
; Вход: A=damage, B=page #0A…#0D, HL=адрес bank-local процедуры. Обычный
; CALL здесь невозможен: после remap его return address указывал бы на код
; с тем же `$8000…$BFFF` адресом, но уже в чужой физической странице.
RTypeCollision_CallBank:
                PUSH AF
                LD   A, B
                SetPage2_A
                POP  AF
                LD   DE, .backToCollision
                PUSH DE
                JP   (HL)
.backToCollision:
                LD   A, RTYPE_COLLISION_BANK_PAGE
                SetPage2_A
                RET

; Bank #0A вызывает packed-BCD scorer, который физически лежит в page #E5.
; Возврат идёт через резидентную метку, затем восстанавливается именно #0A:
; обычный collision trampoline вернул бы Core и потерял bank-local RET.
RTypeObjectBank1_AwardScore:
                PUSH AF
                LD   A, RTYPE_COLLISION_BANK_PAGE
                SetPage2_A
                POP  AF
                LD   DE, .backToBank1
                PUSH DE
                JP   RTypeCollision_AwardScore
.backToBank1:  LD   A, RTYPE_OBJECT_BANK1_PAGE
                SetPage2_A
                RET

; Вызовы bank #0A из резидентного кода. Page2 всегда возвращается к #06 до
; RET, поэтому FT command buffer и оставшаяся половина Core.bin снова видны
; главному циклу. Банк работает при DI и свободно переключает только slot3.
RTypeObjectBank1_InitTerrainBound:
                LD   A, RTYPE_OBJECT_BANK1_PAGE
                SetPage2_A
                CALL RTypeBank1_InitTerrainBound
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank1_UpdateTerrainBound:
                LD   A, RTYPE_OBJECT_BANK1_PAGE
                SetPage2_A
                CALL RTypeBank1_UpdateTerrainBound
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank1_InitTargeting80E3:
                LD   A, RTYPE_OBJECT_BANK1_PAGE
                SetPage2_A
                CALL RTypeBank1_InitTargeting80E3
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank1_UpdateTargeting80E3:
                LD   A, RTYPE_OBJECT_BANK1_PAGE
                SetPage2_A
                CALL RTypeBank1_UpdateTargeting80E3
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank1_UpdateTargetingFlash:
                LD   A, RTYPE_OBJECT_BANK1_PAGE
                SetPage2_A
                CALL RTypeBank1_UpdateTargetingFlash
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank1_UpdateTargetingShot:
                LD   A, RTYPE_OBJECT_BANK1_PAGE
                SetPage2_A
                CALL RTypeBank1_UpdateTargetingShot
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank1_InitLargeTerrain:
                LD   A, RTYPE_OBJECT_BANK1_PAGE
                SetPage2_A
                CALL RTypeBank1_InitLargeTerrain
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank1_UpdateLargeTerrain:
                LD   A, RTYPE_OBJECT_BANK1_PAGE
                SetPage2_A
                CALL RTypeBank1_UpdateLargeTerrain
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank1_UpdateLargeChild:
                LD   A, RTYPE_OBJECT_BANK1_PAGE
                SetPage2_A
                CALL RTypeBank1_UpdateLargeChild
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank1_InitTerrainAware:
                LD   A, RTYPE_OBJECT_BANK1_PAGE
                SetPage2_A
                CALL RTypeBank1_InitTerrainAware
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank1_UpdateTerrainAware:
                LD   A, RTYPE_OBJECT_BANK1_PAGE
                SetPage2_A
                CALL RTypeBank1_UpdateTerrainAware
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank1_InitAnimated86A6:
                LD   A, RTYPE_OBJECT_BANK1_PAGE
                SetPage2_A
                CALL RTypeBank1_InitAnimated86A6
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank1_UpdateAnimated86A6:
                LD   A, RTYPE_OBJECT_BANK1_PAGE
                SetPage2_A
                CALL RTypeBank1_UpdateAnimated86A6
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank1_InitTerrainModifier:
                LD   A, RTYPE_OBJECT_BANK1_PAGE
                SetPage2_A
                CALL RTypeBank1_InitTerrainModifier
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank1_UpdateTerrainModifierParent:
                LD   A, RTYPE_OBJECT_BANK1_PAGE
                SetPage2_A
                CALL RTypeBank1_UpdateTerrainModifierParent
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank1_UpdateTerrainModifierChild:
                LD   A, RTYPE_OBJECT_BANK1_PAGE
                SetPage2_A
                CALL RTypeBank1_UpdateTerrainModifierChild
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank1_UpdateTerrainModifierShot:
                LD   A, RTYPE_OBJECT_BANK1_PAGE
                SetPage2_A
                CALL RTypeBank1_UpdateTerrainModifierShot
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank1_InitHandler60BA:
                LD   A, RTYPE_OBJECT_BANK1_PAGE
                SetPage2_A
                CALL RTypeBank1_InitHandler60BA
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank1_UpdateHandler60BA:
                LD   A, RTYPE_OBJECT_BANK1_PAGE
                SetPage2_A
                CALL RTypeBank1_UpdateHandler60BA
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank1_UpdateHandler60BAShot:
                LD   A, RTYPE_OBJECT_BANK1_PAGE
                SetPage2_A
                CALL RTypeBank1_UpdateHandler60BAShot
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank1_UpdateHandler60BAChild:
                LD   A, RTYPE_OBJECT_BANK1_PAGE
                SetPage2_A
                CALL RTypeBank1_UpdateHandler60BAChild
                LD   A, CorePage + 1
                SetPage2_A
                RET

; Второй code bank целиком принадлежит Dobkeratops. Trampolines однообразны
; намеренно: никакой boss handler не должен случайно оставить #0B в slot2.
RTypeObjectBank2_InitDobkeratops:
                LD   A, RTYPE_OBJECT_BANK2_PAGE
                SetPage2_A
                CALL RTypeBank2_InitDobkeratops
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank2_UpdateDobRoot:
                LD   A, RTYPE_OBJECT_BANK2_PAGE
                SetPage2_A
                CALL RTypeBank2_UpdateDobRoot
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank2_UpdateDobBack:
                LD   A, RTYPE_OBJECT_BANK2_PAGE
                SetPage2_A
                CALL RTypeBank2_UpdateDobBack
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank2_UpdateDobBody:
                LD   A, RTYPE_OBJECT_BANK2_PAGE
                SetPage2_A
                CALL RTypeBank2_UpdateDobBody
                LD   A, CorePage + 1
                SetPage2_A
                RET

; Weapon layer вызывает этот вход с уже загруженным body scratch. Отдельный
; trampoline нужен также host-oracle: он проверяет same-pass запись root flag,
; не подменяя реальный banked вызов прямой записью в тестовую память.
RTypeObjectBank2_BeginDobBodyDeath:
                LD   A, RTYPE_OBJECT_BANK2_PAGE
                SetPage2_A
                CALL RTypeBank2_DobBodyBeginDeath
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank2_UpdateDobAnchor:
                LD   A, RTYPE_OBJECT_BANK2_PAGE
                SetPage2_A
                CALL RTypeBank2_UpdateDobAnchor
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank2_UpdateDobTentacle:
                LD   A, RTYPE_OBJECT_BANK2_PAGE
                SetPage2_A
                CALL RTypeBank2_UpdateDobTentacle
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank2_UpdateDobOrb:
                LD   A, RTYPE_OBJECT_BANK2_PAGE
                SetPage2_A
                CALL RTypeBank2_UpdateDobOrb
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank2_UpdateDobOrbTrail:
                LD   A, RTYPE_OBJECT_BANK2_PAGE
                SetPage2_A
                CALL RTypeBank2_UpdateDobOrbTrail
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank2_UpdateDobDebris:
                LD   A, RTYPE_OBJECT_BANK2_PAGE
                SetPage2_A
                CALL RTypeBank2_UpdateDobDebris
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank2_UpdateDobExplosion:
                LD   A, RTYPE_OBJECT_BANK2_PAGE
                SetPage2_A
                CALL RTypeBank2_UpdateDobExplosion
                LD   A, CorePage + 1
                SetPage2_A
                RET

; Bank #0C начинает последовательный перенос Stage 2. Как и остальные
; trampolines, он меняет только slot2 и восстанавливает вторую страницу Core.
RTypeObjectBank3_InitEnemy6F89:
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                CALL RTypeBank3_InitEnemy6F89
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank3_UpdateEnemy6F89:
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                CALL RTypeBank3_UpdateEnemy6F89
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank3_InitSpawner875D:
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                CALL RTypeBank3_InitSpawner875D
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank3_UpdateSpawner875D:
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                CALL RTypeBank3_UpdateSpawner875D
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank3_UpdateSpawner875DChild:
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                CALL RTypeBank3_UpdateSpawner875DChild
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank3_InitEnemy7D68:
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                CALL RTypeBank3_InitEnemy7D68
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank3_UpdateEnemy7D68:
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                CALL RTypeBank3_UpdateEnemy7D68
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank3_UpdateChild8D85:
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                CALL RTypeBank3_UpdateChild8D85
                LD   A, CorePage + 1
                SetPage2_A
                RET

; A=weapon damage, scratch уже содержит текущую запись. Эти входы позже
; напрямую использует общий player/weapon collision layer.
RTypeObjectBank3_DamageEnemy7D68:
                PUSH AF
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                POP  AF
                CALL RTypeBank3_DamageEnemy7D68
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank3_DamageChild8D85:
                PUSH AF
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                POP  AF
                CALL RTypeBank3_DamageChild8D85
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank3_InitMultipart915B:
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                CALL RTypeBank3_InitMultipart915B
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank3_UpdateMultipart915BParent:
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                CALL RTypeBank3_UpdateMultipart915BParent
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank3_UpdateMultipart915BChild:
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                CALL RTypeBank3_UpdateMultipart915BChild
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank3_UpdateRadial95F1:
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                CALL RTypeBank3_UpdateRadial95F1
                LD   A, CorePage + 1
                SetPage2_A
                RET

; Player-contact main-part entry: scratch/current index уже выбраны collision
; layer-ом. В остальных пяти states исходный handler ничего не делает.
RTypeObjectBank3_ContactMultipart915BChild:
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                CALL RTypeBank3_ContactMultipart915BChild
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank3_InitTerrainEnemy696E:
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                CALL RTypeBank3_InitTerrainEnemy696E
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank3_UpdateTerrainEnemy696E:
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                CALL RTypeBank3_UpdateTerrainEnemy696E
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank3_DamageTerrainEnemy696E:
                PUSH AF
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                POP  AF
                CALL RTypeBank3_DamageTerrainEnemy696E
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank3_InitEnemy8F5E:
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                CALL RTypeBank3_InitEnemy8F5E
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank3_UpdateEnemy8F5E:
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                CALL RTypeBank3_UpdateEnemy8F5E
                LD   A, CorePage + 1
                SetPage2_A
                RET

; A=weapon damage. У `$8F5E` ровно одна единица прочности, поэтому любой
; ненулевой hit сразу заменяет текущую запись штатным `$E7BE`.
RTypeObjectBank3_DamageEnemy8F5E:
                PUSH AF
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                POP  AF
                CALL RTypeBank3_DamageEnemy8F5E
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank3_InitEnemy8469:
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                CALL RTypeBank3_InitEnemy8469
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank3_UpdateEnemy8469:
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                CALL RTypeBank3_UpdateEnemy8469
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank3_DamageEnemy8469:
                PUSH AF
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                POP  AF
                CALL RTypeBank3_DamageEnemy8469
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank3_InitEnemy8561:
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                CALL RTypeBank3_InitEnemy8561
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank3_UpdateEnemy8561:
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                CALL RTypeBank3_UpdateEnemy8561
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank3_UpdateStraightShotE6AB:
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                CALL RTypeBank3_UpdateStraightShotE6AB
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank3_DamageEnemy8561:
                PUSH AF
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                POP  AF
                CALL RTypeBank3_DamageEnemy8561
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank3_InitEnemy5CEA:
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                CALL RTypeBank3_InitEnemy5CEA
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank3_UpdateEnemy5CEA:
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                CALL RTypeBank3_UpdateEnemy5CEA
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank3_DamageEnemy5CEA:
                PUSH AF
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                POP  AF
                CALL RTypeBank3_DamageEnemy5CEA
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank3_InitEnemy5EED:
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                CALL RTypeBank3_InitEnemy5EED
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank3_UpdateEnemy5EED:
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                CALL RTypeBank3_UpdateEnemy5EED
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank3_DamageEnemy5EED:
                PUSH AF
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                POP  AF
                CALL RTypeBank3_DamageEnemy5EED
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank3_InitEnemy7182:
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                CALL RTypeBank3_InitEnemy7182
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank3_UpdateEnemy7182:
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                CALL RTypeBank3_UpdateEnemy7182
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank3_DamageEnemy7182:
                PUSH AF
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                POP  AF
                CALL RTypeBank3_DamageEnemy7182
                LD   A, CorePage + 1
                SetPage2_A
                RET

; `$7294/$72D2` и его специальный `$7435` находятся в том же bank #0C.
; Отдельные trampolines обязательны: scheduler всегда возвращает slot2 на
; вторую страницу Core, даже если дочерний projectile удалился в этом pass.
RTypeObjectBank3_InitEnemy7294:
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                CALL RTypeBank3_InitEnemy7294
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank3_UpdateEnemy7294:
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                CALL RTypeBank3_UpdateEnemy7294
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank3_UpdateProjectile7435:
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                CALL RTypeBank3_UpdateProjectile7435
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank3_DamageEnemy7294:
                PUSH AF
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                POP  AF
                CALL RTypeBank3_DamageEnemy7294
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank3_DamageProjectile7435:
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                CALL RTypeBank3_DamageProjectile7435
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank3_InitStageObject8C12:
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                CALL RTypeBank3_InitStageObject8C12
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank3_UpdateStageObject8C12:
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                CALL RTypeBank3_UpdateStageObject8C12
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank3_InitFixedLarge6E9B:
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                CALL RTypeBank3_InitFixedLarge6E9B
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank3_UpdateFixedLarge6E9B:
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                CALL RTypeBank3_UpdateFixedLarge6E9B
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank3_DamageFixedLarge6E9B:
                PUSH AF
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                POP  AF
                CALL RTypeBank3_DamageFixedLarge6E9B
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank3_InitFormation78F8:
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                CALL RTypeBank3_InitFormation78F8
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank3_UpdateFormation78Parent:
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                CALL RTypeBank3_UpdateFormation78Parent
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank3_UpdateFormation78Child:
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                CALL RTypeBank3_UpdateFormation78Child
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank3_DamageFormation78Child:
                PUSH AF
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                POP  AF
                CALL RTypeBank3_DamageFormation78Child
                LD   A, CorePage + 1
                SetPage2_A
                RET

; Финальный spawner `$9660` и его уязвимый child `$96E9` живут в bank #0C.
; Trampoline каждый раз восстанавливает resident page #06: это обязательно,
; потому что следующий scheduler compare исполняется сразу после RET.
RTypeObjectBank3_InitFinalSpawner9660:
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                CALL RTypeBank3_InitFinalSpawner9660
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank3_UpdateFinalSpawner9660:
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                CALL RTypeBank3_UpdateFinalSpawner9660
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank3_UpdateFinalProjectile96E9:
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                CALL RTypeBank3_UpdateFinalProjectile96E9
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank3_DamageFinalProjectile96E9:
                PUSH AF
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                POP  AF
                CALL RTypeBank3_DamageFinalProjectile96E9
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank3_InitMultipartA71D:
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                CALL RTypeBank3_InitMultipartA71D
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank3_UpdateMultipartA71DController:
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                CALL RTypeBank3_UpdateMultipartA71DController
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank3_UpdateMultipartA71DBody:
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                CALL RTypeBank3_UpdateMultipartA71DBody
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank3_DamageMultipartA71DBody:
                PUSH AF
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                POP  AF
                CALL RTypeBank3_DamageMultipartA71DBody
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank3_UpdateMultipartA71DAttachment:
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                CALL RTypeBank3_UpdateMultipartA71DAttachment
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank3_UpdateMultipartA71DDebris:
                LD   A, RTYPE_OBJECT_BANK3_PAGE
                SetPage2_A
                CALL RTypeBank3_UpdateMultipartA71DDebris
                LD   A, CorePage + 1
                SetPage2_A
                RET

; Bank #0D: late Stage-7 boss `$B7FB`. Макрос здесь развёрнут вручную, чтобы
; каждое имя оставалось доступно machine-oracle и комментарии показывали
; обязательное восстановление resident page #06.
RTypeObjectBank4_InitBossB7FB:
                LD   A, RTYPE_OBJECT_BANK4_PAGE
                SetPage2_A
                CALL RTypeBank4_InitBossB7FB
                LD   A, CorePage + 1
                SetPage2_A
                RET
RTypeObjectBank4_UpdateBossB7FBRoot:
                LD   A, RTYPE_OBJECT_BANK4_PAGE
                SetPage2_A
                CALL RTypeBank4_UpdateBossB7FBRoot
                LD   A, CorePage + 1
                SetPage2_A
                RET
RTypeObjectBank4_UpdateBossB7FBSegment:
                LD   A, RTYPE_OBJECT_BANK4_PAGE
                SetPage2_A
                CALL RTypeBank4_UpdateBossB7FBSegment
                LD   A, CorePage + 1
                SetPage2_A
                RET
RTypeObjectBank4_DamageBossB7FBSegment:
                PUSH AF
                LD   A, RTYPE_OBJECT_BANK4_PAGE
                SetPage2_A
                POP  AF
                CALL RTypeBank4_DamageBossB7FBSegment
                LD   A, CorePage + 1
                SetPage2_A
                RET
RTypeObjectBank4_UpdateBossB7FBRandomSpawner:
                LD   A, RTYPE_OBJECT_BANK4_PAGE
                SetPage2_A
                CALL RTypeBank4_UpdateBossB7FBRandomSpawner
                LD   A, CorePage + 1
                SetPage2_A
                RET
RTypeObjectBank4_UpdateBossB7FBRandomChild:
                LD   A, RTYPE_OBJECT_BANK4_PAGE
                SetPage2_A
                CALL RTypeBank4_UpdateBossB7FBRandomChild
                LD   A, CorePage + 1
                SetPage2_A
                RET
RTypeObjectBank4_DamageBossB7FBRandomChild:
                PUSH AF
                LD   A, RTYPE_OBJECT_BANK4_PAGE
                SetPage2_A
                POP  AF
                CALL RTypeBank4_DamageBossB7FBRandomChild
                LD   A, CorePage + 1
                SetPage2_A
                RET
RTypeObjectBank4_UpdateBossB7FBMissileSpawner:
                LD   A, RTYPE_OBJECT_BANK4_PAGE
                SetPage2_A
                CALL RTypeBank4_UpdateBossB7FBMissileSpawner
                LD   A, CorePage + 1
                SetPage2_A
                RET
RTypeObjectBank4_UpdateBossB7FBMissile:
                LD   A, RTYPE_OBJECT_BANK4_PAGE
                SetPage2_A
                CALL RTypeBank4_UpdateBossB7FBMissile
                LD   A, CorePage + 1
                SetPage2_A
                RET
RTypeObjectBank4_DamageBossB7FBMissile:
                PUSH AF
                LD   A, RTYPE_OBJECT_BANK4_PAGE
                SetPage2_A
                POP  AF
                CALL RTypeBank4_DamageBossB7FBMissile
                LD   A, CorePage + 1
                SetPage2_A
                RET
RTypeObjectBank4_UpdateBossB7FBCore:
                LD   A, RTYPE_OBJECT_BANK4_PAGE
                SetPage2_A
                CALL RTypeBank4_UpdateBossB7FBCore
                LD   A, CorePage + 1
                SetPage2_A
                RET
RTypeObjectBank4_DamageBossB7FBCore:
                PUSH AF
                LD   A, RTYPE_OBJECT_BANK4_PAGE
                SetPage2_A
                POP  AF
                CALL RTypeBank4_DamageBossB7FBCore
                LD   A, CorePage + 1
                SetPage2_A
                RET
RTypeObjectBank4_UpdateBossB7FBCoreChild:
                LD   A, RTYPE_OBJECT_BANK4_PAGE
                SetPage2_A
                CALL RTypeBank4_UpdateBossB7FBCoreChild
                LD   A, CorePage + 1
                SetPage2_A
                RET

; Event initializer `$5526/$5596` использует один bank entry и сам различает
; handlers по RTypeWorldLastHandler.
RTypeObjectBank4_InitPaletteControl:
                LD   A, RTYPE_OBJECT_BANK4_PAGE
                SetPage2_A
                CALL RTypeBank4_InitPaletteControl
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank4_InitFinalStreamFB10:
                LD   A, RTYPE_OBJECT_BANK4_PAGE
                SetPage2_A
                CALL RTypeBank4_InitFinalStreamFB10
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank4_UpdateFinalStreamFB53:
                LD   A, RTYPE_OBJECT_BANK4_PAGE
                SetPage2_A
                CALL RTypeBank4_UpdateFinalStreamFB53
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank4_InitFinalResetEE0B:
                LD   A, RTYPE_OBJECT_BANK4_PAGE
                SetPage2_A
                CALL RTypeBank4_InitFinalResetEE0B
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank4_InitFinalSequenceEEAB:
                LD   A, RTYPE_OBJECT_BANK4_PAGE
                SetPage2_A
                CALL RTypeBank4_InitFinalSequenceEEAB
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank4_UpdateFinalResetEE3C:
                LD   A, RTYPE_OBJECT_BANK4_PAGE
                SetPage2_A
                CALL RTypeBank4_UpdateFinalResetEE3C
                LD   A, CorePage + 1
                SetPage2_A
                RET

RTypeObjectBank4_UpdateFinalSequenceEEB5:
                LD   A, RTYPE_OBJECT_BANK4_PAGE
                SetPage2_A
                CALL RTypeBank4_UpdateFinalSequenceEEB5
                LD   A, CorePage + 1
                SetPage2_A
                RET

; Четыре оставшихся stage events входят в один bank #0D dispatcher. Отдельные
; имена update нужны host-oracle; каждый RET обязательно возвращает page #06.
RTypeObjectBank4_InitStageControllers:
                LD   A, RTYPE_OBJECT_BANK4_PAGE
                SetPage2_A
                CALL RTypeBank4_InitStageControllers
                LD   A, CorePage + 1
                SetPage2_A
                RET
RTypeObjectBank4_UpdateStageController:
                LD   A, RTYPE_OBJECT_BANK4_PAGE
                SetPage2_A
                CALL RTypeBank4_UpdateStageController
                LD   A, CorePage + 1
                SetPage2_A
                RET
RTypeObjectBank4_UpdateBossB1D8Root:
                LD   A, RTYPE_OBJECT_BANK4_PAGE
                SetPage2_A
                CALL RTypeBank4_UpdateBossB1D8Root
                LD   A, CorePage + 1
                SetPage2_A
                RET
RTypeObjectBank4_UpdateBossB1D8Child:
                LD   A, RTYPE_OBJECT_BANK4_PAGE
                SetPage2_A
                CALL RTypeBank4_UpdateBossB1D8Child
                LD   A, CorePage + 1
                SetPage2_A
                RET
RTypeObjectBank4_UpdateC0FinalSprite:
                LD   A, RTYPE_OBJECT_BANK4_PAGE
                SetPage2_A
                CALL RTypeBank4_UpdateC0FinalSprite
                LD   A, CorePage + 1
                SetPage2_A
                RET
RTypeObjectBank4_UpdateC0TerrainChild:
                LD   A, RTYPE_OBJECT_BANK4_PAGE
                SetPage2_A
                CALL RTypeBank4_UpdateC0TerrainChild
                LD   A, CorePage + 1
                SetPage2_A
                RET

; Stage dispatcher вызывает этот блок после полного object scheduler. Поэтому
; каждая созданная здесь запись впервые исполняется только в следующем VBlank.
RTypeObjects_DispatchEvent:
                LD   HL, (RTypeWorldLastHandler)
                LD   DE, #E430
                OR   A
                SBC  HL, DE
                JP   Z, RTypeObjects_InitParticleOwner
                LD   HL, (RTypeWorldLastHandler)
                LD   DE, #FB9C
                OR   A
                SBC  HL, DE
                JP   Z, RTypeObjects_InitPaletteCycle
                LD   HL, (RTypeWorldLastHandler)
                LD   DE, #5526
                OR   A
                SBC  HL, DE
                JP   Z, RTypeObjectBank4_InitPaletteControl
                LD   HL, (RTypeWorldLastHandler)
                LD   DE, #5596
                OR   A
                SBC  HL, DE
                JP   Z, RTypeObjectBank4_InitPaletteControl
                LD   HL, (RTypeWorldLastHandler)
                LD   DE, #FB10
                OR   A
                SBC  HL, DE
                JP   Z, RTypeObjectBank4_InitFinalStreamFB10
                LD   HL, (RTypeWorldLastHandler)
                LD   DE, #EE0B
                OR   A
                SBC  HL, DE
                JP   Z, RTypeObjectBank4_InitFinalResetEE0B
                LD   HL, (RTypeWorldLastHandler)
                LD   DE, #EEAB
                OR   A
                SBC  HL, DE
                JP   Z, RTypeObjectBank4_InitFinalSequenceEEAB
                LD   HL, (RTypeWorldLastHandler)
                LD   DE, #A22E
                OR   A
                SBC  HL, DE
                JP   Z, RTypeObjectBank4_InitStageControllers
                LD   HL, (RTypeWorldLastHandler)
                LD   DE, #B0E1
                OR   A
                SBC  HL, DE
                JP   Z, RTypeObjectBank4_InitStageControllers
                LD   HL, (RTypeWorldLastHandler)
                LD   DE, #B1D8
                OR   A
                SBC  HL, DE
                JP   Z, RTypeObjectBank4_InitStageControllers
                LD   HL, (RTypeWorldLastHandler)
                LD   DE, #C0A9
                OR   A
                SBC  HL, DE
                JP   Z, RTypeObjectBank4_InitStageControllers
                LD   HL, (RTypeWorldLastHandler)
                LD   DE, #F461
                OR   A
                SBC  HL, DE
                JP   Z, RTypeObjects_InitCleanupTimer
                LD   HL, (RTypeWorldLastHandler)
                LD   DE, #596D
                OR   A
                SBC  HL, DE
                JP   Z, RTypeObjects_InitRedFlyer
                LD   HL, (RTypeWorldLastHandler)
                LD   DE, #5DC8
                OR   A
                SBC  HL, DE
                JP   Z, RTypeObjects_InitFormationParent
                LD   HL, (RTypeWorldLastHandler)
                LD   DE, #5A02
                OR   A
                SBC  HL, DE
                JP   Z, RTypeObjects_InitGroundWalker
                LD   HL, (RTypeWorldLastHandler)
                LD   DE, #55E9
                OR   A
                SBC  HL, DE
                JP   Z, RTypeObjectBank1_InitTerrainBound
                LD   HL, (RTypeWorldLastHandler)
                LD   DE, #80E3
                OR   A
                SBC  HL, DE
                JP   Z, RTypeObjectBank1_InitTargeting80E3
                LD   HL, (RTypeWorldLastHandler)
                LD   DE, #74B4
                OR   A
                SBC  HL, DE
                JP   Z, RTypeObjectBank1_InitLargeTerrain
                LD   HL, (RTypeWorldLastHandler)
                LD   DE, #897E
                OR   A
                SBC  HL, DE
                JP   Z, RTypeObjectBank1_InitTerrainAware
                LD   HL, (RTypeWorldLastHandler)
                LD   DE, #86A6
                OR   A
                SBC  HL, DE
                JP   Z, RTypeObjectBank1_InitAnimated86A6
                LD   HL, (RTypeWorldLastHandler)
                LD   DE, #6A9B
                OR   A
                SBC  HL, DE
                JP   Z, RTypeObjectBank1_InitTerrainModifier
                LD   HL, (RTypeWorldLastHandler)
                LD   DE, #60BA
                OR   A
                SBC  HL, DE
                JP   Z, RTypeObjectBank1_InitHandler60BA
                LD   HL, (RTypeWorldLastHandler)
                LD   DE, #98FD
                OR   A
                SBC  HL, DE
                JP   Z, RTypeObjectBank2_InitDobkeratops
                LD   HL, (RTypeWorldLastHandler)
                LD   DE, #6F89
                OR   A
                SBC  HL, DE
                JP   Z, RTypeObjectBank3_InitEnemy6F89
                LD   HL, (RTypeWorldLastHandler)
                LD   DE, #875D
                OR   A
                SBC  HL, DE
                JP   Z, RTypeObjectBank3_InitSpawner875D
                LD   HL, (RTypeWorldLastHandler)
                LD   DE, #7D68
                OR   A
                SBC  HL, DE
                JP   Z, RTypeObjectBank3_InitEnemy7D68
                LD   HL, (RTypeWorldLastHandler)
                LD   DE, #915B
                OR   A
                SBC  HL, DE
                JP   Z, RTypeObjectBank3_InitMultipart915B
                LD   HL, (RTypeWorldLastHandler)
                LD   DE, #F366
                OR   A
                SBC  HL, DE
                JP   Z, RTypeObjects_InitTimedControlF366
                LD   HL, (RTypeWorldLastHandler)
                LD   DE, #696E
                OR   A
                SBC  HL, DE
                JP   Z, RTypeObjectBank3_InitTerrainEnemy696E
                LD   HL, (RTypeWorldLastHandler)
                LD   DE, #8F5E
                OR   A
                SBC  HL, DE
                JP   Z, RTypeObjectBank3_InitEnemy8F5E
                LD   HL, (RTypeWorldLastHandler)
                LD   DE, #8469
                OR   A
                SBC  HL, DE
                JP   Z, RTypeObjectBank3_InitEnemy8469
                LD   HL, (RTypeWorldLastHandler)
                LD   DE, #8561
                OR   A
                SBC  HL, DE
                JP   Z, RTypeObjectBank3_InitEnemy8561
                LD   HL, (RTypeWorldLastHandler)
                LD   DE, #5CEA
                OR   A
                SBC  HL, DE
                JP   Z, RTypeObjectBank3_InitEnemy5CEA
                LD   HL, (RTypeWorldLastHandler)
                LD   DE, #5EED
                OR   A
                SBC  HL, DE
                JP   Z, RTypeObjectBank3_InitEnemy5EED
                LD   HL, (RTypeWorldLastHandler)
                LD   DE, #7182
                OR   A
                SBC  HL, DE
                JP   Z, RTypeObjectBank3_InitEnemy7182
                LD   HL, (RTypeWorldLastHandler)
                LD   DE, #7294
                OR   A
                SBC  HL, DE
                JP   Z, RTypeObjectBank3_InitEnemy7294
                LD   HL, (RTypeWorldLastHandler)
                LD   DE, #8C12
                OR   A
                SBC  HL, DE
                JP   Z, RTypeObjectBank3_InitStageObject8C12
                LD   HL, (RTypeWorldLastHandler)
                LD   DE, #6E9B
                OR   A
                SBC  HL, DE
                JP   Z, RTypeObjectBank3_InitFixedLarge6E9B
                LD   HL, (RTypeWorldLastHandler)
                LD   DE, #78F8
                OR   A
                SBC  HL, DE
                JP   Z, RTypeObjectBank3_InitFormation78F8
                LD   HL, (RTypeWorldLastHandler)
                LD   DE, #9660
                OR   A
                SBC  HL, DE
                JP   Z, RTypeObjectBank3_InitFinalSpawner9660
                LD   HL, (RTypeWorldLastHandler)
                LD   DE, #A71D
                OR   A
                SBC  HL, DE
                JP   Z, RTypeObjectBank3_InitMultipartA71D
                LD   HL, (RTypeWorldLastHandler)
                LD   DE, #B7FB
                OR   A
                SBC  HL, DE
                JP   Z, RTypeObjectBank4_InitBossB7FB
                RET

; `$F366/$F3C1`: первый вызов каждого player немедленно выдаёт `$21` и
; планирует `$20` через `$0180`; повторный индексирует две независимые ROM
; byte-таблицы и использует `$0100`. `RTYPE_LAST_SOUND_COMMAND` — точная
; граница с ещё не перенесённым arcade-SFX/TSFM router; Unreal TSFM не играет.
RTypeObjects_InitTimedControlF366:
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   A, (RTYPE_ACTIVE_PLAYER)
                OR   A
                LD   HL, RTYPE_TRANSITION_FLAGS
                JR   Z, .flagReady
                INC  HL
.flagReady:    LD   A, (HL)
                OR   A
                JR   NZ, .repeat
                LD   (HL), 1
                LD   A, #21
                LD   (RTYPE_LAST_SOUND_COMMAND), A
                LD   HL, #0180
                LD   DE, #0020
                JR   .allocate
.repeat:       LD   A, (RTYPE_TRANSITION_SOUND_INDEX)
                LD   E, A
                LD   D, 0
                LD   HL, #8C16
                ADD  HL, DE
                CALL RTypeWorldRom_ReadByte
                LD   B, A
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   A, B
                LD   (RTYPE_LAST_SOUND_COMMAND), A
                LD   A, (RTYPE_TRANSITION_SOUND_INDEX)
                LD   E, A
                LD   D, 0
                LD   HL, #8C0C
                ADD  HL, DE
                CALL RTypeWorldRom_ReadByte
                LD   E, A
                LD   D, 0
                LD   HL, #0100
.allocate:     LD   (RTypeObjects_F3Timer), HL
                LD   (RTypeObjects_F3Sound), DE
                CALL RTypeObjects_New
                RET  C
                LD   A, RTYPE_OBJ_TIMED_CONTROL_F3C1
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #1000
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   A, #FF
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   HL, (RTypeObjects_F3Timer)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_F3_TIMER), HL
                LD   HL, (RTypeObjects_F3Sound)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_F3_SOUND_COMMAND), HL
                JP   RTypeObjects_CommitCurrent

RTypeObjects_UpdateTimedControlF3C1:
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   A, (RTYPE_CLEANUP_ACTIVE)
                OR   A
                JR   NZ, .finish
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_F3_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_F3_TIMER), HL
                LD   A, H
                OR   L
                RET  NZ
.finish:       LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_F3_SOUND_COMMAND)
                LD   (RTYPE_LAST_SOUND_COMMAND), A
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET

RTypeObjects_F3Timer: DEFW 0
RTypeObjects_F3Sound: DEFW 0

; `$F461/$F477`: три scheduler-прохода держать `$2FC4=1`. Объект имеет
; priority `$0100`; поэтому в третий проход сначала уже очищены частицы `$0010`,
; затем timer снимает flag, и более поздние priority снова исполняются.
RTypeObjects_InitCleanupTimer:
                CALL RTypeObjects_New
                RET  C
                LD   A, RTYPE_OBJ_CLEANUP_TIMER
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #0100
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   HL, 3
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TIMER), HL
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   A, 1
                LD   (RTYPE_CLEANUP_ACTIVE), A
                JP   RTypeObjects_CommitCurrent

; `$E430`: создать владельца фоновых частиц из шестибайтной записи `$8314`.
; Четыре resource types фиксированы ROM и удерживаются до нулевого remaining.
RTypeObjects_InitParticleOwner:
                CALL RTypeObjects_New
                RET  C
                LD   A, RTYPE_OBJ_PARTICLE_OWNER
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #1000
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   A, (RTypeWorldLastCommand)
                AND  3
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                LD   D, H
                LD   E, L
                ADD  HL, HL
                ADD  HL, DE                       ; index * 6
                LD   DE, #8314
                ADD  HL, DE
                LD   (RTypeObjects_RomCursor), HL
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_OWNER_REMAINING), DE
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_OWNER_VELOCITIES), DE
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_OWNER_CADENCE), DE
                LD   HL, RTypeObjects_ParticleResourceTypes
                LD   IX, RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_OWNER_SLOTS
                LD   B, 4
.resource:     LD   A, (HL)
                INC  HL
                PUSH HL
                PUSH BC
                CALL RTypeResources_Acquire
                POP  BC
                POP  HL
                LD   (IX + 0), A
                INC  IX
                DJNZ .resource
                JP   RTypeObjects_CommitCurrent

RTypeObjects_ParticleResourceTypes:
                DEFB #57, #59, #5A, #5C

; `$FB9C`: скопировать неизменяемую 16-байтную запись `$989C[index]` и
; обязательно потребить один RNG для phase, даже если palette update невидим.
RTypeObjects_InitPaletteCycle:
                CALL RTypeObjects_New
                RET  C
                LD   A, RTYPE_OBJ_PALETTE_CYCLE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #FF00
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   A, (RTypeWorldLastCommand)
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL                      ; low command * 16
                LD   DE, #989C
                ADD  HL, DE
                LD   (RTypeObjects_RomCursor), HL
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CYCLE_PALETTE), DE
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CYCLE_FIRST), DE
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CYCLE_SECOND), DE
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CYCLE_REMAINING), DE
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CYCLE_MODE), DE
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CYCLE_MASK), DE
                CALL RTypeRng_Next
                ADD  HL, HL
                ADD  HL, HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CYCLE_PHASE), HL
                JP   RTypeObjects_CommitCurrent

; `$596D`: Red Flyer. Все ROM tables, два вызова RNG, fire counter mask и
; начальный ScriptedMotion совпадают с `$F8DC/$F5C1`, а не выбираются вручную.
RTypeObjects_InitRedFlyer:
                CALL RTypeObjects_New
                RET  C
                LD   A, RTYPE_OBJ_RED_FLYER
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #02C8
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   HL, #28E2
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                LD   HL, #8010
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   A, (RTypeWorldLastCommand)
                AND  #0F
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                LD   DE, #8DB0
                ADD  HL, DE
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), DE
                LD   A, #0D
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #0D
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   HL, #9ACE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT), HL
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT_PTR), DE
                LD   A, 2
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT_COMMANDS), A
                LD   A, (RTypeWorldLastCommand)
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
                ADD  HL, DE                       ; fire index * 6
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
                ADD  HL, HL                      ; RNG * 4
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FIRE_A)
                DEC  DE                          ; power-of-two mask fire_a-1
                LD   A, L
                AND  E
                LD   L, A
                LD   A, H
                AND  D
                LD   H, A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FIRE_COUNTER), HL
                CALL RTypeRng_Next
                LD   A, L
                AND  #1F
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOTION_PHASE), A
                LD   HL, #28E2
                CALL RTypeSprite_PrepareDescriptor
                JP   RTypeObjects_CommitCurrent

; `$5DC8`: невидимый formation parent. Command выбирает anchor, один из
; четырёх `(sequence,count)` и ROM root движения будущих children.
RTypeObjects_InitFormationParent:
                CALL RTypeObjects_New
                RET  C
                LD   A, RTYPE_OBJ_FORMATION_PARENT
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #8010
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   A, (RTypeWorldLastCommand)
                AND  #0F
                LD   (RTypeObjects_FormationCommandIndex), A
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                ADD  HL, HL                      ; index * 4
                LD   DE, #8DD0
                ADD  HL, DE
                LD   (RTypeObjects_RomCursor), HL
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), DE
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), DE
                LD   A, (RTypeObjects_FormationCommandIndex)
                CP   3
                JR   C, .xAdjusted
                CP   9
                JR   NC, .xAdjusted
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, #0040
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
.xAdjusted:    LD   A, (RTypeWorldLastCommand + 1)
                AND  3
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                ADD  HL, HL                      ; parameter index * 4
                LD   DE, #9250
                ADD  HL, DE
                LD   (RTypeObjects_RomCursor), HL
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FORM_SEQUENCE), DE
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FORM_REMAINING), DE
                LD   A, (RTypeWorldLastCommand)
                AND  #F0
                RRCA
                RRCA
                RRCA
                RRCA
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                LD   DE, #92EC
                ADD  HL, DE
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT), DE
                EX   DE, HL
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FORM_PHASE), DE
                LD   HL, 2
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FORM_TIMER), HL
                JP   RTypeObjects_CommitCurrent

; Создать одного `$5E22` formation child. Значения parent предварительно
; сохранены в резидентных переменных, потому что allocator очищает scratch.
RTypeObjects_InitFormationChild:
                LD   (RTypeObjects_FormationMovement), HL
                CALL RTypeObjects_New
                RET  C
                LD   A, RTYPE_OBJ_FORMATION_CHILD
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                LD   HL, #8010
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   HL, (RTypeObjects_FormationParentX)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   HL, (RTypeObjects_FormationParentY)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL
                LD   HL, #29D2
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                LD   A, #0C
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #0C
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   HL, (RTypeObjects_FormationParentScript)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT), HL
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT_PTR), DE
                LD   A, 2
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT_COMMANDS), A
                LD   HL, (RTypeObjects_FormationParentPhase)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOTION_PHASE), HL
                LD   HL, (RTypeObjects_FormationMovement)
                LD   A, L
                AND  #0F
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
                ; `$5E5D` немедленно перезаписывает common initializer ещё
                ; одним RNG & $0F; оба вызова обязательны для общего потока.
                CALL RTypeRng_Next
                LD   A, L
                AND  #0F
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FIRE_COUNTER), A
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FIRE_COUNTER + 1), A
                LD   HL, #29D2
                CALL RTypeSprite_PrepareDescriptor
                JP   RTypeObjects_CommitCurrent

; `$5A02`: Ground Walker. Два resource slots соответствуют обычной и
; falling/scripted палитре; Q8 residue записи остаётся нулевым только после
; чистого reset и далее сохраняется самим 64-байтным slot.
RTypeObjects_InitGroundWalker:
                CALL RTypeObjects_New
                RET  C
                LD   A, RTYPE_OBJ_GROUND_WALKER
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                ; `$5A02` объявляет x_fraction наследуемым: после оборота FIFO
                ; walker получает byte +$10 предыдущего владельца slot.
                LD   A, (RTypeObjects_TakenXFraction)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_FRACTION), A
                LD   HL, #8020
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
                LD   A, (RTypeWorldLastCommand + 1)
                AND  1
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS), A
                LD   HL, #0100
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                LD   A, #1E
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   A, #1E
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   A, #1F
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_WALKER_SECONDARY), A
                LD   A, (RTypeWorldLastCommand)
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
                JP   RTypeObjects_CommitCurrent

; Создать `$E568` background particle. Инициализация намеренно откладывается:
; первый scheduler pass только выбирает три RNG/table значения, а движение и
; sprite-ready начинаются ещё одним VBlank позже, как в исходной цепочке.
RTypeObjects_InitBackgroundParticle:
                LD   (RTypeObjects_NewParticleVelocities), HL
                CALL RTypeObjects_New
                RET  C
                LD   A, RTYPE_OBJ_BG_PARTICLE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                ; До `$E568` resource ещё не выбран; оригинальная/Python
                ; запись помечает оба поля `$FF`, а не нулевым palette slot.
                LD   A, #FF
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                LD   HL, #0010
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PRIORITY), HL
                LD   HL, (RTypeObjects_NewParticleVelocities)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT), HL
                JP   RTypeObjects_CommitCurrent

; `$E568` initializer и `$E5CD` runtime одной фоновой частицы.
RTypeObjects_UpdateBackgroundParticle:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                OR   A
                JR   NZ, .move
                CALL RTypeRng_Next
                LD   A, L
                AND  #1F
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT)
                ADD  HL, DE
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY), DE
                CALL RTypeRng_Next
                LD   A, L
                AND  #1F
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                ADD  HL, HL
                LD   DE, #83AC
                ADD  HL, DE
                LD   (RTypeObjects_RomCursor), HL
                CALL RTypeObjects_ReadWordNext
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), DE
                CALL RTypeObjects_ReadWordNext
                LD   A, E
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_RESOURCE), A
                CALL RTypeResources_Acquire
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                CALL RTypeRng_Next
                LD   A, L
                AND  7
                LD   (RTypeObjects_ParticleJitter), A
                LD   A, L
                AND  #3E
                LD   L, A                        ; `(random & $3E)` уже = index*2
                LD   H, 0
                LD   DE, #842C
                ADD  HL, DE
                CALL RTypeWorldRom_ReadWord
                LD   A, (RTypeObjects_ParticleJitter)
                ADD  A, E
                LD   E, A
                LD   A, D
                ADC  A, 0
                LD   D, A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), DE
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT)
                LD   DE, #832C
                OR   A
                SBC  HL, DE
                LD   HL, #02AC
                JR   NZ, .xReady
                LD   HL, #013C
.xReady:       LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   A, 1
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                JP   RTypePyBackgroundParticleAfterInit

.move:         LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_FRACTION)
                LD   L, A
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   H, A
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY)
                ADD  HL, DE
                LD   A, L
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_FRACTION), A
                LD   A, H
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), A
                LD   C, 0
                BIT  7, D
                JR   Z, .velocitySignReady
                DEC  C
.velocitySignReady:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X + 1)
                ADC  A, C
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X + 1), A
                LD   A, 1
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SUBSTATE), A
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT)
                LD   DE, #832C
                OR   A
                SBC  HL, DE
                JR   NZ, .leftMoving
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, #02C0
                OR   A
                SBC  HL, DE
                JR   C, .prepare
                JR   .remove
.leftMoving:   LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, #0140
                OR   A
                SBC  HL, DE
                JR   NC, .prepare
.remove:       LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET
.prepare:      LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR)
                JP   RTypeSprite_PrepareDescriptor

; `$E4A5/$E532`: decrement lifetime, вести unsigned cadence и создавать
; `$E568`. В последних 63 проходах отрицательный counter вызывает буквальный
; burst: unsigned сравнение снова считает его достигшим cadence.
RTypeObjects_UpdateParticleOwner:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_OWNER_REMAINING)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_OWNER_REMAINING), HL
                LD   A, H
                OR   L
                JR   NZ, .alive
                LD   IX, RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_OWNER_SLOTS
                LD   B, 4
.release:      LD   A, (IX + 0)
                PUSH BC
                CALL RTypeResources_Release
                POP  BC
                INC  IX
                DJNZ .release
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET
.alive:        LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_OWNER_COUNTER)
                INC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_OWNER_COUNTER), HL
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_OWNER_CADENCE)
                OR   A
                SBC  HL, DE
                RET  C
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_OWNER_COUNTER), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_OWNER_COUNTER + 1), A
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_OWNER_REMAINING)
                LD   A, H
                OR   A
                JR   NZ, .spawn
                LD   A, L
                CP   #40
                JR   NC, .spawn
                CALL RTypeRng_Next
                LD   A, L
                AND  7
                ADD  A, 6
                CPL
                INC  A                           ; low byte `-(6…13)`
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_OWNER_COUNTER), A
                LD   A, #FF
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_OWNER_COUNTER + 1), A
.spawn:        LD   A, (RTypeObjects_CurrentIndex)
                LD   (RTypeObjects_ParentIndex), A
                CALL RTypeObjects_StoreScratch
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_OWNER_VELOCITIES)
                CALL RTypeObjects_InitBackgroundParticle
                LD   A, (RTypeObjects_ParentIndex)
                LD   (RTypeObjects_CurrentIndex), A
                JP   RTypeObjects_LoadScratch

; Интерпретатор `$F5C1`. Carry=1 означает конец списка streams; обычный
; возврат после смены stream или двух movement commands очищает Carry.
; Старую копию оставляем только как сверяемый листинг. Она не должна занимать
; резидентное окно: рабочая bank-safe версия находится ниже #8000.
                IF 0
RTypeObjects_ScriptedMotion_DeadCopy:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT_COMMANDS)
                LD   (RTypeObjects_MotionRemaining), A
.command:      LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT_PTR)
                CALL RTypeWorldRom_ReadByte
                LD   (RTypeObjects_MotionCommand), A
                BIT  7, A
                JR   Z, .movement
                AND  #1F
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOTION_PHASE), A
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOTION_PHASE + 1), A
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT_PTR)
                INC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT_PTR), HL
                JR   .command                     ; phase не расходует command
.movement:     LD   A, (RTypeObjects_MotionCommand)
                BIT  6, A
                JR   Z, .positiveX
                BIT  5, A
                JR   Z, .vertical
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                JR   .vertical
.positiveX:    BIT  5, A
                JR   Z, .vertical
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                INC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
.vertical:     LD   A, (RTypeObjects_MotionCommand)
                BIT  4, A
                JR   Z, .positiveY
                BIT  3, A
                JR   Z, .endFlag
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL
                JR   .endFlag
.positiveY:    BIT  3, A
                JR   Z, .endFlag
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                INC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL
.endFlag:      LD   A, (RTypeObjects_MotionCommand)
                BIT  2, A
                JR   Z, .advance
.nextStream:   LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT)
                INC  HL
                INC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT), HL
                CALL RTypeWorldRom_ReadWord
                LD   A, D
                OR   E
                JR   NZ, .streamWord
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT)
                INC  HL
                INC  HL
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT), DE
                EX   DE, HL
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT_PTR), DE
                SCF
                RET
.streamWord:   LD   A, D
                CP   #F0
                JR   NZ, .selectStream
                LD   A, E
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT_COMMANDS), A
                JR   .nextStream
.selectStream: LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT_PTR), DE
                OR   A
                RET
.advance:      LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT_PTR)
                INC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT_PTR), HL
                LD   HL, RTypeObjects_MotionRemaining
                DEC  (HL)
                JP   NZ, .command
                OR   A
                RET

; Runtime Red Flyer: motion, foreground delta, ROM animation ring, точный
; common-fire counter и выделение общего projectile `$E601` на trigger-кадре.
                ENDIF
RTypeObjects_UpdateRedFlyer:
                CALL RTypeObjects_ScriptedMotion
                JR   NC, .alive
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET
.alive:        LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, (RTypeWorldFgDelta)
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   A, (FrameCounter)
                LD   B, A
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOTION_PHASE)
                ADD  A, B
                AND  #1C
                RRCA
                RRCA
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                LD   D, H
                LD   E, L
                ADD  HL, HL
                ADD  HL, DE                       ; phase * 6
                LD   DE, #28E2
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                CALL RTypeSprite_PrepareDescriptor
                CALL RTypeObjects_AdvanceFireCounter
                CALL Z, RTypeObjects_SpawnProjectileFromCurrent
                RET

; `$5DC8` runtime parent: scroll-lock, двухкадровая первая задержка, затем
; child каждые `$10` VBlank и циклический пятисловный movement sequence.
RTypeObjects_UpdateFormationParent:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, (RTypeWorldFgDelta)
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   DE, #0150
                OR   A
                SBC  HL, DE
                JR   NC, .inside
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET
.inside:       LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FORM_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FORM_TIMER), HL
                LD   A, H
                OR   L
                RET  NZ
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FORM_REMAINING)
                LD   A, H
                OR   L
                RET  Z
                LD   HL, #0010
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FORM_TIMER), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FORM_INDEX)
                ADD  HL, HL
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FORM_SEQUENCE)
                ADD  HL, DE
                CALL RTypeWorldRom_ReadWord
                LD   (RTypeObjects_FormationMovement), DE
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FORM_INDEX)
                INC  HL
                LD   A, L
                CP   5
                JR   C, .indexReady
                LD   HL, 0
.indexReady:   LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FORM_INDEX), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FORM_REMAINING)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FORM_REMAINING), HL
                LD   A, (RTypeObjects_CurrentIndex)
                LD   (RTypeObjects_ParentIndex), A
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   (RTypeObjects_FormationParentX), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   (RTypeObjects_FormationParentY), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT)
                LD   (RTypeObjects_FormationParentScript), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FORM_PHASE)
                LD   (RTypeObjects_FormationParentPhase), HL
                CALL RTypeObjects_StoreScratch
                LD   HL, (RTypeObjects_FormationMovement)
                CALL RTypeObjects_InitFormationChild
                LD   A, (RTypeObjects_ParentIndex)
                LD   (RTypeObjects_CurrentIndex), A
                CALL RTypeObjects_LoadScratch
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FORM_REMAINING)
                LD   A, H
                OR   L
                RET  NZ
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET

; `$5E22/$5E9A`: общий ScriptedMotion, scroll-lock и descriptor, выбранный
; непосредственно phase-командой потока. Fire counter повторяет `$F63A`.
RTypeObjects_UpdateFormationChild:
                CALL RTypeObjects_ScriptedMotion
                JR   NC, .alive
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET
.alive:        LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, (RTypeWorldFgDelta)
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_MOTION_PHASE)
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                LD   D, H
                LD   E, L
                ADD  HL, HL
                ADD  HL, DE
                LD   DE, #29D2
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                CALL RTypeSprite_PrepareDescriptor
                CALL RTypeObjects_AdvanceFireCounter
                CALL Z, RTypeObjects_SpawnProjectileFromCurrent
                RET

; Эти общие подпрограммы перенесены в bank-safe блок ниже #8000. Отключённая
; копия сохраняет удобное соседство с handlers, но не попадает в бинарник.
                IF 0
; Общая `$F63A` часть. Z означает кадр projectile request; counter при
; равенстве fire_a намеренно не сбрасывается, при достижении fire_b становится
; нулём. Вызывающий по Z немедленно создаёт и исполняет `$E601`.
RTypeObjects_AdvanceFireCounter_DeadCopy:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FIRE_COUNTER)
                INC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FIRE_COUNTER), HL
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FIRE_A)
                OR   A
                SBC  HL, DE
                RET  Z
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FIRE_COUNTER)
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FIRE_B)
                OR   A
                SBC  HL, DE
                JR   C, .noTrigger
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FIRE_COUNTER), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FIRE_COUNTER + 1), A
                RET                              ; Z=1: upper-limit trigger
.noTrigger:    OR   1                            ; NZ
                RET

; Классифицировать signed HL для углового `$1D89`: A=0 при HL<0, A=1 при
; 0…$3F, A=2 при HL>=$40. Пороговые неравенства различают 16 направлений.
RTypeDirection_Classify_DeadCopy:
                BIT  7, H
                JR   Z, .nonNegative
                XOR  A
                RET
.nonNegative:  LD   A, H
                OR   A
                JR   NZ, .large
                LD   A, L
                CP   #40
                JR   NC, .large
                LD   A, 1
                RET
.large:        LD   A, 2
                RET

; Source/target берутся из резидентных слов. Возврат A — byte offset
; `$00,$04…$3C` в таблице пар signed Q8 velocities.
RTypeDirection_Offset_DeadCopy:
                LD   HL, (RTypeObjects_ProjectileSourceY)
                LD   DE, 8
                ADD  HL, DE
                LD   DE, (RTypePlayerNativeY)
                OR   A
                SBC  HL, DE
                JR   C, .targetBelow
                LD   HL, (RTypeObjects_ProjectileSourceY)
                LD   DE, 8
                OR   A
                SBC  HL, DE
                LD   DE, (RTypePlayerNativeY)
                OR   A
                SBC  HL, DE
                JP   NC, .targetAbove
                LD   HL, (RTypeObjects_ProjectileSourceX)
                LD   DE, (RTypePlayerNativeX)
                OR   A
                SBC  HL, DE
                LD   A, #30
                RET  NC
                LD   A, #10
                RET

.targetBelow:  LD   HL, (RTypeObjects_ProjectileSourceX)
                LD   DE, 8
                ADD  HL, DE
                LD   DE, (RTypePlayerNativeX)
                OR   A
                SBC  HL, DE
                JR   C, .belowRight
                LD   HL, (RTypeObjects_ProjectileSourceX)
                LD   DE, 8
                OR   A
                SBC  HL, DE
                LD   DE, (RTypePlayerNativeX)
                OR   A
                SBC  HL, DE
                JR   NC, .belowLeft
                XOR  A
                RET
.belowRight:   LD   HL, (RTypePlayerNativeX)
                LD   DE, (RTypeObjects_ProjectileSourceX)
                OR   A
                SBC  HL, DE
                PUSH HL
                LD   HL, (RTypePlayerNativeY)
                LD   DE, (RTypeObjects_ProjectileSourceY)
                OR   A
                SBC  HL, DE
                EX   DE, HL
                POP  HL
                OR   A
                SBC  HL, DE
                LD   DE, #0020
                ADD  HL, DE
                CALL RTypeDirection_Classify
                OR   A
                JR   Z, .belowRightNegative
                CP   1
                JR   Z, .belowRightMiddle
                LD   A, #0C
                RET
.belowRightNegative:
                LD   A, #04
                RET
.belowRightMiddle:
                LD   A, #08
                RET
.belowLeft:    LD   HL, (RTypeObjects_ProjectileSourceX)
                LD   DE, (RTypePlayerNativeX)
                OR   A
                SBC  HL, DE
                PUSH HL
                LD   HL, (RTypePlayerNativeY)
                LD   DE, (RTypeObjects_ProjectileSourceY)
                OR   A
                SBC  HL, DE
                EX   DE, HL
                POP  HL
                OR   A
                SBC  HL, DE
                LD   DE, #0020
                ADD  HL, DE
                CALL RTypeDirection_Classify
                OR   A
                JR   Z, .belowLeftNegative
                CP   1
                JR   Z, .belowLeftMiddle
                LD   A, #34
                RET
.belowLeftNegative:
                LD   A, #3C
                RET
.belowLeftMiddle:
                LD   A, #38
                RET

.targetAbove:  LD   HL, (RTypeObjects_ProjectileSourceX)
                LD   DE, 8
                ADD  HL, DE
                LD   DE, (RTypePlayerNativeX)
                OR   A
                SBC  HL, DE
                JR   C, .aboveRight
                LD   HL, (RTypeObjects_ProjectileSourceX)
                LD   DE, 8
                OR   A
                SBC  HL, DE
                LD   DE, (RTypePlayerNativeX)
                OR   A
                SBC  HL, DE
                JR   NC, .aboveLeft
                LD   A, #20
                RET
.aboveRight:   LD   HL, (RTypePlayerNativeX)
                LD   DE, (RTypeObjects_ProjectileSourceX)
                OR   A
                SBC  HL, DE
                PUSH HL
                LD   HL, (RTypeObjects_ProjectileSourceY)
                LD   DE, (RTypePlayerNativeY)
                OR   A
                SBC  HL, DE
                EX   DE, HL
                POP  HL
                OR   A
                SBC  HL, DE
                LD   DE, #0020
                ADD  HL, DE
                CALL RTypeDirection_Classify
                OR   A
                JR   Z, .aboveRightNegative
                CP   1
                JR   Z, .aboveRightMiddle
                LD   A, #14
                RET
.aboveRightNegative:
                LD   A, #1C
                RET
.aboveRightMiddle:
                LD   A, #18
                RET
.aboveLeft:    LD   HL, (RTypeObjects_ProjectileSourceX)
                LD   DE, (RTypePlayerNativeX)
                OR   A
                SBC  HL, DE
                PUSH HL
                LD   HL, (RTypeObjects_ProjectileSourceY)
                LD   DE, (RTypePlayerNativeY)
                OR   A
                SBC  HL, DE
                EX   DE, HL
                POP  HL
                OR   A
                SBC  HL, DE
                LD   DE, #0020
                ADD  HL, DE
                CALL RTypeDirection_Classify
                OR   A
                JR   Z, .aboveLeftNegative
                CP   1
                JR   Z, .aboveLeftMiddle
                LD   A, #2C
                RET
.aboveLeftNegative:
                LD   A, #24
                RET
.aboveLeftMiddle:
                LD   A, #28
                RET

; `$F63A -> $E601`: сохранить source, выделить A000-record и выполнить его
; первый Q8 pass немедленно, потому что новый priority строго позже текущего.
RTypeObjects_SpawnProjectileFromCurrent_DeadCopy:
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
                LD   A, RTYPE_OBJ_ENEMY_PROJECTILE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                ; Только `$E601` просит allocator сохранить Q8 residue нового
                ; физического slot. Это важно после первого оборота FIFO.
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
                CALL RTypeObjects_UpdateEnemyProjectileCore
                CALL RTypeObjects_CommitCurrent
.restore:      LD   A, (RTypeObjects_ParentIndex)
                LD   (RTypeObjects_CurrentIndex), A
                JP   RTypeObjects_LoadScratch

RTypeObjects_UpdateEnemyProjectile_DeadCopy:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PROJECTILE_BORN)
                LD   DE, (FrameCounter)
                OR   A
                SBC  HL, DE
                RET  Z                           ; immediate pass уже сделан source-ом
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PROJECTILE_BURST)
                LD   A, H
                OR   L
                JR   NZ, RTypeProjectile_UpdateBurst_DeadCopy

RTypeObjects_UpdateEnemyProjectileCore_DeadCopy:
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_VELOCITY)
                CALL RTypeProjectile_AddQ8X
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_VELOCITY)
                CALL RTypeProjectile_AddQ8Y
                LD   HL, (FrameCounter)
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PROJECTILE_PHASE)
                ADD  HL, DE
                LD   A, L
                AND  #18
                LD   B, A
                SRL  A
                LD   C, A
                LD   A, B
                SRL  A
                SRL  A
                ADD  A, C
                LD   L, A
                LD   H, 0
                LD   DE, #84AE
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                CALL RTypeSprite_PrepareDescriptor
                LD   A, (FrameCounter)
                INC  A
                AND  1
                RET  NZ
                LD   BC, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                CALL RTypeTerrain_ForegroundCode
                LD   DE, #0DFC
                OR   A
                SBC  HL, DE
                JR   C, .burst
                LD   BC, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                CALL RTypeTerrain_BackgroundCode
                LD   DE, #07D0
                OR   A
                SBC  HL, DE
                JR   C, .burst
                CALL RTypeProjectile_InsideBounds
                RET  NC
                JP   RTypeProjectile_Remove
.burst:        LD   HL, #000A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PROJECTILE_BURST), HL
                RET

; `$E686`: локальный десятикадровый распад projectile. Resource `$56` всё
; время остаётся захваченным; descriptor идёт по убывающему timer и только
; после кадра с timer=1 запись возвращается в FIFO.
RTypeProjectile_UpdateBurst_DeadCopy:
                LD   A, L
                AND  #0E
                LD   L, A
                LD   H, 0
                LD   D, H
                LD   E, L
                ADD  HL, HL
                ADD  HL, DE                       ; `(timer & $0E) * 3`
                LD   DE, #8490
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                CALL RTypeSprite_PrepareDescriptor
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PROJECTILE_BURST)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PROJECTILE_BURST), HL
                LD   A, H
                OR   L
                RET  NZ
                JP   RTypeProjectile_Remove

RTypeProjectile_AddQ8X_DeadCopy:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_FRACTION)
                LD   L, A
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   H, A
                ADD  HL, DE
                LD   A, L
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_FRACTION), A
                LD   A, H
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), A
                LD   HL, RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X + 1
                JR   RTypeProjectile_AddQ8High_DeadCopy
RTypeProjectile_AddQ8Y_DeadCopy:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_FRACTION)
                LD   L, A
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   H, A
                ADD  HL, DE
                LD   A, L
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y_FRACTION), A
                LD   A, H
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), A
                LD   HL, RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y + 1
RTypeProjectile_AddQ8High_DeadCopy:
                LD   C, 0
                BIT  7, D
                JR   Z, .signReady
                DEC  C
.signReady:    LD   A, (HL)
                ADC  A, C
                LD   (HL), A
                RET

RTypeProjectile_InsideBounds_DeadCopy:
                CALL RTypeWalker_InsideBounds
                RET

RTypeProjectile_Remove_DeadCopy:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                SCF
                RET

; Carry=0 только внутри unsigned native rectangle `$1D6B`.
RTypeWalker_InsideBounds_DeadCopy:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, #012C
                OR   A
                SBC  HL, DE
                JR   C, .outside
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, #02D4
                OR   A
                SBC  HL, DE
                JR   NC, .outside
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   DE, #007C
                OR   A
                SBC  HL, DE
                JR   C, .outside
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   DE, #0194
                OR   A
                SBC  HL, DE
                JR   NC, .outside
                OR   A
                RET
.outside:      SCF
                RET

                ENDIF
RTypeWalker_Remove:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_WALKER_SECONDARY)
                CALL RTypeResources_Release
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET

; Один `$5BA4` falling pass. Вызывающий уже выполнил первый `$F63A`; A=1
; запрашивает второй вызов на `$5B4D -> $5B9F` fall-through.
RTypeWalker_Fall:
                OR   A
                JR   Z, .fallMotion
                CALL RTypeObjects_AdvanceFireCounter
                CALL Z, RTypeObjects_SpawnProjectileFromCurrent
.fallMotion:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   DE, -3
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                AND  1
                JR   NZ, .descriptor
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, (RTypeWorldFgDelta)
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
.descriptor:   LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                AND  1
                LD   HL, #294C
                JR   Z, .framePose
                LD   HL, #2970
.framePose:    LD   A, (FrameCounter)
                AND  8
                JR   NZ, .poseReady
                LD   DE, 6
                ADD  HL, DE
.poseReady:    LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                CALL RTypeSprite_PrepareDescriptor
                LD   A, 1
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SUBSTATE), A
                CALL RTypeWalker_InsideBounds
                JP   C, RTypeWalker_Remove
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                AND  1
                LD   DE, -8
                JR   Z, .probeXReady
                LD   DE, 8
.probeXReady:  ADD  HL, DE
                LD   B, H
                LD   C, L
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   DE, -#0010
                ADD  HL, DE
                EX   DE, HL
                CALL RTypeTerrain_ForegroundCode
                LD   DE, #0DFC
                OR   A
                SBC  HL, DE
                RET  NC                          ; solid code: падение продолжается
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   DE, 7
                ADD  HL, DE
                LD   A, L
                AND  #F8
                LD   L, A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y), HL
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                AND  1
                LD   HL, #292A
                JR   Z, .landingPointer
                LD   HL, #2932
.landingPointer:
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_WALKER_ANIM_PTR), HL
                LD   HL, 4
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_WALKER_ANIM_TIMER), HL
                LD   A, RTYPE_WALKER_LANDING
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                RET

RTypeObjects_UpdateGroundWalker:
                CALL RTypeObjects_AdvanceFireCounter
                CALL Z, RTypeObjects_SpawnProjectileFromCurrent
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                CP   RTYPE_WALKER_FALLING
                JR   NZ, .landingCheck
                XOR  A
                JP   RTypeWalker_Fall
.landingCheck: CP   RTYPE_WALKER_LANDING
                JR   NZ, .turningCheck
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                AND  1
                CALL Z, RTypeWalker_AddForegroundDelta
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_WALKER_ANIM_PTR)
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), DE
                EX   DE, HL
                CALL RTypeSprite_PrepareDescriptor
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_WALKER_ANIM_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_WALKER_ANIM_TIMER), HL
                LD   A, H
                OR   L
                RET  NZ
                LD   HL, 4
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_WALKER_ANIM_TIMER), HL
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_WALKER_ANIM_PTR)
                INC  HL
                INC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_WALKER_ANIM_PTR), HL
                CALL RTypeWorldRom_ReadWord
                LD   A, D
                OR   E
                RET  NZ
                LD   A, RTYPE_WALKER_WALKING
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                RET
.turningCheck: CP   RTYPE_WALKER_TURNING
                JR   NZ, .scriptedCheck
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                AND  1
                CALL Z, RTypeWalker_AddForegroundDelta
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_WALKER_ANIM_PTR)
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), DE
                EX   DE, HL
                CALL RTypeSprite_PrepareDescriptor
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_WALKER_ANIM_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_WALKER_ANIM_TIMER), HL
                LD   A, H
                OR   L
                RET  NZ
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_WALKER_ANIM_PTR)
                INC  HL
                INC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_WALKER_ANIM_PTR), HL
                CALL RTypeWorldRom_ReadWord
                LD   A, D
                OR   E
                JR   Z, .turnFinished
                LD   HL, 4
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_WALKER_ANIM_TIMER), HL
                RET
.turnFinished: LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                AND  1
                LD   HL, #9AF8
                JR   Z, .installMotion
                LD   HL, #9B0A
.installMotion:
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT), HL
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT_PTR), DE
                LD   A, 2
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SCRIPT_COMMANDS), A
                LD   A, RTYPE_WALKER_SCRIPTED
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                RET
.scriptedCheck:
                CP   RTYPE_WALKER_SCRIPTED
                JR   NZ, .edgeCheck
                CALL RTypeObjects_ScriptedMotion
                JR   NC, .scriptedAlive
                LD   A, RTYPE_WALKER_FALLING
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                LD   A, 1
                JP   RTypeWalker_Fall
.scriptedAlive:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                AND  1
                CALL Z, RTypeWalker_AddForegroundDelta
                CALL RTypeWalker_SetFallingPose
                CALL RTypeWalker_InsideBounds
                JP   C, RTypeWalker_Remove
                RET
.edgeCheck:    CP   RTYPE_WALKER_EDGE
                JR   NZ, .walking
                CALL RTypeWalker_AddForegroundDelta
                ; Временное чтение player anchor будет заменено буквальным
                ; fixed-player record при его переносе; состояние/границы уже
                ; остаются точными для текущего объекта.
                LD   HL, (ArcadePlayerX + 1)
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                OR   A
                SBC  HL, DE
                LD   HL, #293A
                JR   C, .edgePoseReady
                LD   HL, #295E
.edgePoseReady:
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                CALL RTypeSprite_PrepareDescriptor
                CALL RTypeWalker_InsideBounds
                JP   C, RTypeWalker_Remove
                RET
.walking:      LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                AND  1
                JR   NZ, .walkingVelocity
                CALL RTypeWalker_AddForegroundDelta
.walkingVelocity:
                LD   DE, -#00C0
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                AND  1
                JR   Z, .velocityReady
                LD   DE, #00C0
.velocityReady:
                CALL RTypeWalker_AddQ8X
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                AND  1
                LD   HL, #291A
                JR   Z, .walkTableReady
                LD   HL, #2922
.walkTableReady:
                LD   A, (FrameCounter)
                AND  #18
                RRCA
                RRCA
                LD   E, A
                LD   D, 0
                ADD  HL, DE
                CALL RTypeWorldRom_ReadWord
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), DE
                EX   DE, HL
                CALL RTypeSprite_PrepareDescriptor
                CALL RTypeWalker_InsideBounds
                JP   C, RTypeWalker_Remove
                ; Передний probe: solid -> turning.
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, -#0010
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                AND  1
                JR   Z, .firstX
                LD   DE, #0010
.firstX:       ADD  HL, DE
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
                JR   C, .secondProbe
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                AND  1
                LD   HL, #292A
                JR   Z, .turnPtr
                LD   HL, #2932
.turnPtr:      LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_WALKER_ANIM_PTR), HL
                LD   HL, 4
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_WALKER_ANIM_TIMER), HL
                LD   A, RTYPE_WALKER_TURNING
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                RET
.secondProbe:  LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, -#0012
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                AND  1
                JR   Z, .secondX
                LD   DE, #0012
.secondX:      ADD  HL, DE
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
                RET  NC
                LD   A, RTYPE_WALKER_EDGE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE), A
                RET

RTypeWalker_AddForegroundDelta:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, (RTypeWorldFgDelta)
                ADD  HL, DE
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), HL
                RET

; DE=signed Q8 velocity, обновить `(word X, byte fraction)` с расширением знака.
RTypeWalker_AddQ8X:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_FRACTION)
                LD   L, A
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   H, A
                ADD  HL, DE
                LD   A, L
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X_FRACTION), A
                LD   A, H
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X), A
                LD   C, 0
                BIT  7, D
                JR   Z, .signReady
                DEC  C
.signReady:    LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X + 1)
                ADC  A, C
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X + 1), A
                RET

RTypeWalker_SetFallingPose:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                AND  1
                LD   HL, #294C
                JR   Z, .frame
                LD   HL, #2970
.frame:        LD   A, (FrameCounter)
                AND  8
                JR   NZ, .ready
                LD   DE, 6
                ADD  HL, DE
.ready:        LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR), HL
                JP   RTypeSprite_PrepareDescriptor

RTypeObjects_UpdatePaletteCycle:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CYCLE_REMAINING)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CYCLE_REMAINING), HL
                LD   A, H
                OR   L
                JR   NZ, .alive
                XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET
.alive:        LD   HL, (FrameCounter)
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CYCLE_PHASE)
                ADD  HL, DE
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CYCLE_MASK)
                LD   A, H
                AND  D
                LD   B, A
                LD   A, L
                AND  E
                OR   B
                RET  NZ                         ; `(VBlank+phase)&phase_mask`

                ; Следующий после mask бит выбирает чётный/нечётный palette
                ; type. Для `$3F/$7F/$FF` это соответственно `$40/$80/$100`.
                INC  DE
                LD   A, H
                AND  D
                LD   B, A
                LD   A, L
                AND  E
                OR   B
                LD   HL, RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CYCLE_FIRST
                JR   Z, .typeReady
                INC  HL
                INC  HL
.typeReady:    LD   A, (HL)
                PUSH AF
                LD   HL, RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CYCLE_PALETTE
                LD   C, (HL)
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_CYCLE_MODE)
                POP  AF
                JP   RTypePalette_SetTile

RTypeObjects_UpdateCleanupTimer:
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TIMER)
                DEC  HL
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TIMER), HL
                LD   A, H
                OR   L
                RET  NZ
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                XOR  A
                LD   (RTYPE_CLEANUP_ACTIVE), A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET

; Общая cleanup-ветка `$F461`: owners принадлежат отдельному списку и здесь
; не уничтожаются. Sprite-объекты отпускают захваченный resource slot.
RTypeObjects_CleanupCurrent:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE)
                CP   RTYPE_OBJ_BG_PARTICLE
                JP   Z, .releasePalette
                CP   RTYPE_OBJ_RED_FLYER
                JP   Z, .releasePalette
                CP   RTYPE_OBJ_FORMATION_CHILD
                JP   Z, .releasePalette
                CP   RTYPE_OBJ_GROUND_WALKER
                JR   NZ, .projectileCheck
                ; Ground Walker удерживает два slots, в отличие от остальных.
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_WALKER_SECONDARY)
                CALL RTypeResources_Release
                JP   .clear
.projectileCheck:
                CP   RTYPE_OBJ_ENEMY_PROJECTILE
                JP   Z, .releasePalette
                CP   RTYPE_OBJ_PROJECTILE_7435
                JP   Z, .releasePalette
                CP   RTYPE_OBJ_TERRAIN_BOUND
                JP   Z, .releasePalette
                CP   RTYPE_OBJ_TARGETING_FLASH
                JP   Z, .releasePalette
                CP   RTYPE_OBJ_TARGETING_SHOT
                JP   Z, .releasePalette
                CP   RTYPE_OBJ_TARGETING_80E3
                JP   Z, .targetingRoot
                CP   RTYPE_OBJ_LARGE_CHILD
                JP   Z, .releasePalette
                CP   RTYPE_OBJ_LARGE_TERRAIN
                JP   Z, .largeRoot
                CP   RTYPE_OBJ_TERRAIN_AWARE
                JP   Z, .releasePalette
                CP   RTYPE_OBJ_ANIMATED_86A6
                JP   Z, .releasePalette
                CP   RTYPE_OBJ_TERRAIN_MOD_CHILD
                JP   Z, .releasePalette
                CP   RTYPE_OBJ_TERRAIN_MOD_SHOT
                JP   Z, .releasePalette
                CP   RTYPE_OBJ_HANDLER_60BA_SHOT
                JP   Z, .releasePalette
                CP   RTYPE_OBJ_HANDLER_60BA_CHILD
                JP   Z, .releasePalette
                CP   RTYPE_OBJ_HANDLER_60BA
                JP   Z, .handler60Root
                CP   RTYPE_OBJ_DOB_BACK
                JP   Z, .releasePalette
                CP   RTYPE_OBJ_DOB_BODY
                JP   Z, .dobBody
                CP   RTYPE_OBJ_DOB_TENTACLE
                JP   Z, .releasePalette
                CP   RTYPE_OBJ_DOB_ORB
                JP   Z, .releasePalette
                CP   RTYPE_OBJ_DOB_ORB_TRAIL
                JP   Z, .releasePalette
                CP   RTYPE_OBJ_DOB_DEBRIS
                JP   Z, .releasePalette
                CP   RTYPE_OBJ_DOB_EXP_F280
                JP   Z, .releasePalette
                CP   RTYPE_OBJ_DOB_EXP_EF00
                JP   Z, .releasePalette
                CP   RTYPE_OBJ_DOB_EXP_FE00
                JP   Z, .releasePalette
                CP   RTYPE_OBJ_ENEMY_6F89
                JP   Z, .enemy6F89
                CP   RTYPE_OBJ_SPAWNER_875D_CHILD
                JP   Z, .releasePalette
                CP   RTYPE_OBJ_ENEMY_7D68
                JP   Z, .enemy7D68
                CP   RTYPE_OBJ_CHILD_8D85
                JP   Z, .child8D85
                CP   RTYPE_OBJ_MULTIPART_915B_PARENT
                JP   Z, .clear
                CP   RTYPE_OBJ_MULTIPART_915B_CHILD
                JP   Z, .child915B
                CP   RTYPE_OBJ_RADIAL_95F1
                JP   Z, .releasePalette
                CP   RTYPE_OBJ_TERRAIN_ENEMY_696E
                JP   Z, .enemy696E
                CP   RTYPE_OBJ_ENEMY_8F5E
                JP   Z, .releasePalette
                CP   RTYPE_OBJ_ENEMY_8469
                JP   Z, .releasePalette
                CP   RTYPE_OBJ_STRAIGHT_SHOT_E6AB
                JP   Z, .releasePalette
                CP   RTYPE_OBJ_ENEMY_8561
                JP   Z, .enemy8561
                CP   RTYPE_OBJ_ENEMY_5CEA
                JP   Z, .releasePalette
                CP   RTYPE_OBJ_ENEMY_5EED
                JP   Z, .enemy5EED
                CP   RTYPE_OBJ_ENEMY_7182
                JP   Z, .releasePalette
                CP   RTYPE_OBJ_ENEMY_7294
                JP   Z, .enemy7294
                CP   RTYPE_OBJ_STAGE_OBJECT_8C12
                JP   Z, .clear
                CP   RTYPE_OBJ_FIXED_LARGE_6E9B
                JP   Z, .releasePalette
                CP   RTYPE_OBJ_FORMATION_78_PARENT
                JP   Z, .clear
                CP   RTYPE_OBJ_FORMATION_78_CHILD
                JP   Z, .formation78Child
                CP   RTYPE_OBJ_FINAL_SPAWNER_9660
                JP   Z, .clear
                CP   RTYPE_OBJ_FINAL_PROJECTILE_96E9
                JP   Z, .releasePalette
                CP   RTYPE_OBJ_A71D_CONTROLLER
                JP   Z, .clear
                CP   RTYPE_OBJ_A71D_BODY
                JP   Z, .a71dBody
                CP   RTYPE_OBJ_A71D_ATTACHMENT
                JP   Z, .a71dAttachment
                CP   RTYPE_OBJ_A71D_DEBRIS
                JP   Z, .releasePalette
                CP   RTYPE_OBJ_B7FB_ROOT
                JP   Z, .clear
                CP   RTYPE_OBJ_B7FB_SEGMENT
                JP   Z, .releasePalette
                CP   RTYPE_OBJ_B7FB_RANDOM_SPAWNER
                JP   Z, .clear
                CP   RTYPE_OBJ_B7FB_RANDOM_CHILD
                JP   Z, .releasePalette
                CP   RTYPE_OBJ_B7FB_MISSILE_SPAWNER
                JP   Z, .clear
                CP   RTYPE_OBJ_B7FB_MISSILE
                JP   Z, .releasePalette
                CP   RTYPE_OBJ_B7FB_CORE
                JP   Z, .b7fbCore
                CP   RTYPE_OBJ_B7FB_CORE_CHILD
                JP   Z, .releasePalette
                CP   RTYPE_OBJ_FINAL_STREAM_FB53
                JP   Z, .releasePalette
                CP   RTYPE_OBJ_FINAL_RESET_EE3C
                JP   Z, .clear
                CP   RTYPE_OBJ_FINAL_SEQUENCE_EEB5
                JP   Z, .clear
                CP   RTYPE_OBJ_STAGE_CONTROLLER
                JP   Z, .clear
                CP   RTYPE_OBJ_B1D8_ROOT
                JP   Z, .b1Pair
                CP   RTYPE_OBJ_B1D8_CHILD
                JP   Z, .b1Pair
                CP   RTYPE_OBJ_C0_FINAL_SPRITE
                JP   Z, .releasePalette
                CP   RTYPE_OBJ_C0_TERRAIN_CHILD
                JP   Z, .clear
                JP   .clear
.enemy6F89:    LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_6F_FLASH_PALETTE)
                CALL RTypeResources_Release
                JP   .clear
.enemy7D68:    LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_7D_FLASH_PALETTE)
                CALL RTypeResources_Release
                JP   .clear
.child8D85:    LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8D_FLASH_PALETTE)
                CALL RTypeResources_Release
                JP   .clear
.child915B:    LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_91_FLASH_PALETTE)
                CALL RTypeResources_Release
                JP   .clear
.enemy696E:    LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_69_FLASH_PALETTE)
                CALL RTypeResources_Release
                JP   .clear
.enemy8561:    LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_85_FLASH_PALETTE)
                CALL RTypeResources_Release
                JP   .clear
.enemy5EED:    LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_5E_FLASH_PALETTE)
                CALL RTypeResources_Release
                JP   .clear
.enemy7294:    LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_72_FLASH_PALETTE)
                CALL RTypeResources_Release
                JP   .clear
.formation78Child:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_78_FLASH_PALETTE)
                CALL RTypeResources_Release
                JP   .clear
.a71dBody:     LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_ALT_PALETTE)
                CALL RTypeResources_Release
                JP   .clear
.a71dAttachment:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_ATTACHMENT_ALT_PALETTE)
                CALL RTypeResources_Release
                JP   .clear
.b7fbCore:     LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_CORE_FLASH_PALETTE)
                CALL RTypeResources_Release
                JP   .clear
.b1Pair:       LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_FLASH_PALETTE)
                CALL RTypeResources_Release
                JP   .clear
.dobBody:      LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_FLASH_PALETTE)
                CALL RTypeResources_Release
                JP   .clear
.handler60Root:
                ; `$60BA` постоянно удерживает normal `$21` и flash `$55`.
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_FLASH_PALETTE)
                CALL RTypeResources_Release
                JP   .clear
.largeRoot:
                ; `$74B4` также удерживает normal и flash slots.
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_FLASH_PALETTE)
                CALL RTypeResources_Release
                JP   .clear
.targetingRoot:
                ; `$80E3` удерживает normal `$20` и flash `$55` одновременно.
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLASH_PALETTE)
                CALL RTypeResources_Release
                JP   .clear
.releasePalette:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeResources_Release
                JP   .clear
.clear:        XOR  A
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE), A
                RET

; Один типовой scheduler band. Несколько проходов воспроизводят приоритеты
; `$0010`, `$1000`, `$8010`, `$FF00`; новая частица controller-а не исполняется
; в тот же VBlank, потому что её низкоприоритетный band уже завершён.
RTypeObjects_RunType:
                LD   (RTypeObjects_DesiredType), A
                ; `$03A6` вставляет равный priority перед уже существующим:
                ; обычные объекты поэтому обходятся newest-first. Отдельный
                ; `$E4A5` owner-list в oracle сохраняет порядок создания и
                ; является единственным перенесённым здесь ascending band.
                CP   RTYPE_OBJ_PARTICLE_OWNER
                JR   Z, .ascendingStart
                CP   RTYPE_OBJ_DOB_TENTACLE
                LD   A, RTYPE_OBJECT_COUNT - 1
                JR   NZ, .scanStartReady
.ascendingStart:
                LD   A, 2
.scanStartReady:
                LD   (RTypeObjects_ScanIndex), A
RTypeObjects_RunTypeNext:
                LD   A, (RTypeObjects_ScanIndex)
                LD   (RTypeObjects_CurrentIndex), A
                ; Пять priority bands просматривают 96 slots, но 64-байтный
                ; LDIR выполняется только для совпавшего type. Сначала читаем
                ; один type byte непосредственно из page #09; это сохраняет
                ; scheduler semantics без недопустимых ~30 КБ копий/VBlank.
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   A, (RTypeObjects_ScanIndex)
                CALL RTypeObjects_RecordAddress
                LD   A, (HL)
                LD   B, A
                LD   A, (RTypeObjects_DesiredType)
                CP   B
                JP   NZ, RTypeObjects_RunTypeAdvance
                LD   A, (RTypeObjects_ScanIndex)
                CALL RTypeObjects_LoadScratch
                CALL RTypeObjects_ProcessLoaded
                JP   RTypeObjects_RunTypeAdvance

; Исполнить одну уже загруженную scratch-запись.  DesiredType и
; CurrentIndex заданы вызывающим. Эта граница общая для старого
; test-only RunType и нового однопроходного live scheduler-a.
RTypeObjects_ProcessLoaded:
                ; CleanupTimer и particle owner пропускают глобальную очистку;
                ; остальные перенесённые Enemy записи освобождаются сразу.
                LD   A, (RTypeObjects_DesiredType)
                CP   RTYPE_OBJ_CLEANUP_TIMER
                JR   Z, .dispatch
                CP   RTYPE_OBJ_PARTICLE_OWNER
                JR   Z, .dispatch
                ; `$F3C1` сам наблюдает cleanup и перед удалением обязан
                ; отправить отложенную команду; общий cleanup его не режет.
                CP   RTYPE_OBJ_TIMED_CONTROL_F3C1
                JR   Z, .dispatch
                ; Stage-controller сам поднимает cleanup и обязан дожить до
                ; собственных `$A523/$B1AC/$C1EB` таймеров. Boss `$B1D8` также
                ; переживает общую очистку, чтобы вернуть scroll и отпустить slots.
                CP   RTYPE_OBJ_STAGE_CONTROLLER
                JR   Z, .dispatch
                CP   RTYPE_OBJ_B1D8_ROOT
                JR   Z, .dispatch
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   A, (RTYPE_CLEANUP_ACTIVE)
                OR   A
                JR   Z, .reloadDispatchType
                CALL RTypeObjects_CleanupCurrent
                JP   .commit
.reloadDispatchType:
                LD   A, (RTypeObjects_DesiredType)
.dispatch:
                CP   RTYPE_OBJ_C0_TERRAIN_CHILD + 1
                JR   NC, .commit
                ADD  A, A
                LD   E, A
                LD   D, 0
                LD   HL, RTypeObjects_UpdateDispatchTable
                ADD  HL, DE
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                LD   HL, .commit
                PUSH HL
                PUSH DE
                RET                              ; динамический CALL через таблицу
.commit:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE)
                OR   A
                JR   Z, .release
                LD   A, (RTypeObjects_CurrentIndex)
                CALL RTypeObjects_StoreScratch
                RET
.release:      LD   A, (RTypeObjects_CurrentIndex)
                CALL RTypeObjects_Release
                RET

RTypeObjects_NoUpdate:
                RET

; Номер object type уже является плотным индексом 1…79. Таблица заменяет до
; 79 пар CP/CALL на один O(1) переход и оставляет Z80 только сам автомат.
RTypeObjects_UpdateDispatchTable:
                DEFW RTypeObjects_NoUpdate
                DEFW RTypeObjects_UpdateRedFlyer, RTypeObjects_UpdatePaletteCycle
                DEFW RTypeObjects_UpdateParticleOwner, RTypeObjects_UpdateBackgroundParticle
                DEFW RTypeObjects_UpdateCleanupTimer, RTypeObjects_UpdateFormationParent
                DEFW RTypeObjects_UpdateFormationChild, RTypeObjects_UpdateGroundWalker
                DEFW RTypeObjects_UpdateEnemyProjectile, RTypeObjectBank1_UpdateTerrainBound
                DEFW RTypeObjectBank1_UpdateTargeting80E3, RTypeObjectBank1_UpdateTargetingFlash
                DEFW RTypeObjectBank1_UpdateTargetingShot, RTypeObjectBank1_UpdateLargeTerrain
                DEFW RTypeObjectBank1_UpdateLargeChild, RTypeObjectBank1_UpdateTerrainAware
                DEFW RTypeObjectBank1_UpdateAnimated86A6, RTypeObjectBank1_UpdateTerrainModifierParent
                DEFW RTypeObjectBank1_UpdateTerrainModifierChild, RTypeObjectBank1_UpdateTerrainModifierShot
                DEFW RTypeObjectBank1_UpdateHandler60BA, RTypeObjectBank1_UpdateHandler60BAShot
                DEFW RTypeObjectBank1_UpdateHandler60BAChild, RTypeObjectBank2_UpdateDobRoot
                DEFW RTypeObjectBank2_UpdateDobBack, RTypeObjectBank2_UpdateDobBody
                DEFW RTypeObjectBank2_UpdateDobAnchor, RTypeObjectBank2_UpdateDobTentacle
                DEFW RTypeObjectBank2_UpdateDobOrb, RTypeObjectBank2_UpdateDobOrbTrail
                DEFW RTypeObjectBank2_UpdateDobDebris, RTypeObjectBank2_UpdateDobExplosion
                DEFW RTypeObjectBank2_UpdateDobExplosion, RTypeObjectBank2_UpdateDobExplosion
                DEFW RTypeObjectBank3_UpdateEnemy6F89, RTypeObjectBank3_UpdateSpawner875D
                DEFW RTypeObjectBank3_UpdateSpawner875DChild, RTypeObjectBank3_UpdateEnemy7D68
                DEFW RTypeObjectBank3_UpdateChild8D85, RTypeObjectBank3_UpdateMultipart915BParent
                DEFW RTypeObjectBank3_UpdateMultipart915BChild, RTypeObjectBank3_UpdateRadial95F1
                DEFW RTypeObjects_UpdateTimedControlF3C1, RTypeObjectBank3_UpdateTerrainEnemy696E
                DEFW RTypeObjectBank3_UpdateEnemy8F5E, RTypeObjectBank3_UpdateEnemy8469
                DEFW RTypeObjectBank3_UpdateStraightShotE6AB, RTypeObjectBank3_UpdateEnemy8561
                DEFW RTypeObjectBank3_UpdateEnemy5CEA, RTypeObjectBank3_UpdateEnemy5EED
                DEFW RTypeObjectBank3_UpdateEnemy7182, RTypeObjectBank3_UpdateEnemy7294
                DEFW RTypeObjectBank3_UpdateProjectile7435, RTypeObjectBank3_UpdateStageObject8C12
                DEFW RTypeObjectBank3_UpdateFixedLarge6E9B, RTypeObjectBank3_UpdateFormation78Parent
                DEFW RTypeObjectBank3_UpdateFormation78Child, RTypeObjectBank3_UpdateFinalSpawner9660
                DEFW RTypeObjectBank3_UpdateFinalProjectile96E9, RTypeObjectBank3_UpdateMultipartA71DController
                DEFW RTypeObjectBank3_UpdateMultipartA71DBody, RTypeObjectBank3_UpdateMultipartA71DAttachment
                DEFW RTypeObjectBank3_UpdateMultipartA71DDebris, RTypeObjectBank4_UpdateBossB7FBRoot
                DEFW RTypeObjectBank4_UpdateBossB7FBSegment, RTypeObjectBank4_UpdateBossB7FBRandomSpawner
                DEFW RTypeObjectBank4_UpdateBossB7FBRandomChild, RTypeObjectBank4_UpdateBossB7FBMissileSpawner
                DEFW RTypeObjectBank4_UpdateBossB7FBMissile, RTypeObjectBank4_UpdateBossB7FBCore
                DEFW RTypeObjectBank4_UpdateBossB7FBCoreChild, RTypeObjectBank4_UpdateFinalStreamFB53
                DEFW RTypeObjectBank4_UpdateFinalResetEE3C, RTypeObjectBank4_UpdateFinalSequenceEEB5
                DEFW RTypeObjectBank4_UpdateStageController, RTypeObjectBank4_UpdateBossB1D8Root
                DEFW RTypeObjectBank4_UpdateBossB1D8Child, RTypeObjectBank4_UpdateC0FinalSprite
                DEFW RTypeObjectBank4_UpdateC0TerrainChild
RTypeObjects_RunTypeAdvance:
                LD   A, (RTypeObjects_ScanIndex)
                LD   B, A
                LD   A, (RTypeObjects_DesiredType)
                CP   RTYPE_OBJ_PARTICLE_OWNER
                JR   Z, .ascendingSelected
                CP   RTYPE_OBJ_DOB_TENTACLE
                JR   NZ, .descendingSelected
.ascendingSelected:
                LD   A, B
                JR   .ascending
.descendingSelected:
                LD   A, B
                CP   2
                RET  Z
                DEC  A
                LD   (RTypeObjects_ScanIndex), A
                JP   RTypeObjects_RunTypeNext
.ascending:    INC  A
                LD   (RTypeObjects_ScanIndex), A
                CP   RTYPE_OBJECT_COUNT
                JP   C, RTypeObjects_RunTypeNext
                RET

RTypeObjects_Update:
                ; IRQ `$0219` reseed выполняется при обнулении low 9 bits.
                LD   A, (FrameCounter)
                OR   A
                JR   NZ, .bands
                LD   A, (FrameCounter + 1)
                AND  1
                CALL Z, RTypeRng_Reset
.bands:        ; Старые 71 type-band прохода были недостижимы после JP и
                ; занимали дефицитный resident Core. Test entry
                ; RTypeObjects_RunType остаётся ниже как отдельная процедура.
                JP   RTypeObjects_UpdateOrdered

; Один кадр live scheduler-a.  Список уже упорядочен при allocation,
; поэтом цена пустого кадра — несколько инструкций, а занятого —
; ровно один handler на каждую active record.  NEXT читается после
; handler-a: новый object с большим priority, вставленный после current,
; попадает в тот же pass; equal-priority newer object вставлен перед
; current и законно ждёт следующего VBlank.
RTypeObjects_UpdateOrdered:
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   A, RTYPE_OBJECT_COUNT
                LD   (RTypeScheduler_UpdateRemaining), A
                LD   A, (RTYPE_SCHED_HEAD)
.next:         CP   RTYPE_SCHED_NULL
                RET  Z
                LD   (.walkIndex), A
                CP   RTYPE_OBJECT_COUNT
                JP   NC, RTypeScheduler_Rebuild
                LD   A, (RTypeScheduler_UpdateRemaining)
                OR   A
                JP   Z, RTypeScheduler_Rebuild
                DEC  A
                LD   (RTypeScheduler_UpdateRemaining), A
                LD   A, (.walkIndex)
                LD   (RTypeObjects_CurrentIndex), A
                ; Движущаяся BackgroundParticleE5CD переводится напрямую в
                ; её 64-байтной записи. Однократный initializer возвращает NC
                ; и по-прежнему идёт через общий scratch-путь.
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   A, (.walkIndex)
                CALL RTypeObjects_RecordAddress
                LD   A, (HL)
                CP   RTYPE_OBJ_BG_PARTICLE
                JR   NZ, .generic
                LD   A, (.walkIndex)
                CALL RTypePyBackgroundParticleFastUpdate
                JR   C, .processed
.generic:
                LD   A, (.walkIndex)
                CALL RTypeObjects_LoadScratch
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE)
                LD   (RTypeObjects_DesiredType), A
                CALL RTypeObjects_ProcessLoaded
.processed:
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   A, (.walkIndex)
                LD   E, A
                LD   D, 0
                LD   HL, RTYPE_SCHED_NEXT
                ADD  HL, DE
                LD   A, (HL)
                JR   .next
.walkIndex:    DEFB RTYPE_SCHED_NULL

; Отрисовка идёт в порядке физического пула. Для перенесённых типов это тот же
; порядок, в котором hardware sprite RAM получает `$068D`; служебные owners и
; palette cycles изображения не имеют.
RTypeObjects_Draw:
                LD   A, 2
                LD   (RTypeObjects_ScanIndex), A
                LD   HL, RTYPE_OBJECT_BASE + 2 * RTYPE_OBJECT_REC_SIZE
                LD   (.scanPtr), HL
.next:         LD   A, (RTypeObjects_ScanIndex)
                LD   A, RTYPE_OBJECT_PAGE
                SetPage3_A
                LD   HL, (.scanPtr)
                LD   A, (HL)
                ; Compact Python pool marks a free slot with type 0.  Reject it
                ; before the translated type dispatcher instead of comparing
                ; it against every concrete Enemy subclass.
                OR   A
                JP   Z, .advance
                CP   RTYPE_OBJ_RED_FLYER
                JP   Z, .loadDraw
                CP   RTYPE_OBJ_FORMATION_CHILD
                JP   Z, .loadDraw
                CP   RTYPE_OBJ_GROUND_WALKER
                JP   Z, .loadWalker
                CP   RTYPE_OBJ_ENEMY_PROJECTILE
                JP   Z, .loadDraw
                CP   RTYPE_OBJ_PROJECTILE_7435
                JP   Z, .loadDraw
                CP   RTYPE_OBJ_TERRAIN_BOUND
                JP   Z, .loadDraw
                CP   RTYPE_OBJ_TARGETING_80E3
                JP   Z, .loadTargeting
                CP   RTYPE_OBJ_TARGETING_FLASH
                JP   Z, .loadVisible
                CP   RTYPE_OBJ_TARGETING_SHOT
                JP   Z, .loadDraw
                CP   RTYPE_OBJ_LARGE_TERRAIN
                JP   Z, .loadLargeTerrain
                CP   RTYPE_OBJ_LARGE_CHILD
                JP   Z, .loadDraw
                CP   RTYPE_OBJ_TERRAIN_AWARE
                JP   Z, .loadDraw
                CP   RTYPE_OBJ_ANIMATED_86A6
                JP   Z, .loadDraw
                CP   RTYPE_OBJ_TERRAIN_MOD_CHILD
                JP   Z, .loadDraw
                CP   RTYPE_OBJ_TERRAIN_MOD_SHOT
                JP   Z, .loadDraw
                CP   RTYPE_OBJ_HANDLER_60BA
                JP   Z, .loadHandler60Root
                CP   RTYPE_OBJ_HANDLER_60BA_SHOT
                JP   Z, .loadDraw
                CP   RTYPE_OBJ_HANDLER_60BA_CHILD
                JP   Z, .loadHandler60Child
                CP   RTYPE_OBJ_DOB_BACK
                JP   Z, .loadDraw
                CP   RTYPE_OBJ_DOB_BODY
                JP   Z, .loadDobBody
                CP   RTYPE_OBJ_DOB_TENTACLE
                JP   Z, .loadDobTentacle
                CP   RTYPE_OBJ_DOB_ORB
                JP   Z, .loadDraw
                CP   RTYPE_OBJ_DOB_ORB_TRAIL
                JP   Z, .loadDraw
                CP   RTYPE_OBJ_DOB_DEBRIS
                JP   Z, .loadDobEfObject
                CP   RTYPE_OBJ_DOB_EXP_F280
                JP   Z, .loadDraw
                CP   RTYPE_OBJ_DOB_EXP_FE00
                JP   Z, .loadDraw
                CP   RTYPE_OBJ_ENEMY_6F89
                JP   Z, .loadEnemy6F89
                CP   RTYPE_OBJ_SPAWNER_875D_CHILD
                JP   Z, .loadDraw
                CP   RTYPE_OBJ_ENEMY_7D68
                JP   Z, .loadEnemy7D68
                CP   RTYPE_OBJ_CHILD_8D85
                JP   Z, .loadChild8D85
                CP   RTYPE_OBJ_MULTIPART_915B_CHILD
                JP   Z, .loadChild915B
                CP   RTYPE_OBJ_RADIAL_95F1
                JP   Z, .loadDraw
                CP   RTYPE_OBJ_TERRAIN_ENEMY_696E
                JP   Z, .loadEnemy696E
                CP   RTYPE_OBJ_ENEMY_8F5E
                JP   Z, .loadDraw
                CP   RTYPE_OBJ_ENEMY_8469
                JP   Z, .loadDraw
                CP   RTYPE_OBJ_STRAIGHT_SHOT_E6AB
                JP   Z, .loadPair
                CP   RTYPE_OBJ_ENEMY_8561
                JP   Z, .loadEnemy8561
                CP   RTYPE_OBJ_ENEMY_5CEA
                JP   Z, .loadDraw
                CP   RTYPE_OBJ_ENEMY_5EED
                JP   Z, .loadEnemy5EED
                CP   RTYPE_OBJ_ENEMY_7182
                JP   Z, .loadDraw
                CP   RTYPE_OBJ_ENEMY_7294
                JP   Z, .loadEnemy7294
                CP   RTYPE_OBJ_FIXED_LARGE_6E9B
                JP   Z, .loadFixed6E9B
                CP   RTYPE_OBJ_FORMATION_78_CHILD
                JP   Z, .loadFormation78Child
                CP   RTYPE_OBJ_FINAL_PROJECTILE_96E9
                JP   Z, .loadDraw
                CP   RTYPE_OBJ_A71D_BODY
                JP   Z, .loadA71DBody
                CP   RTYPE_OBJ_A71D_ATTACHMENT
                JP   Z, .loadA71DAttachment
                CP   RTYPE_OBJ_A71D_DEBRIS
                JP   Z, .loadDraw
                CP   RTYPE_OBJ_B7FB_SEGMENT
                JP   Z, .loadDraw
                CP   RTYPE_OBJ_B7FB_RANDOM_CHILD
                JP   Z, .loadDraw
                CP   RTYPE_OBJ_B7FB_MISSILE
                JP   Z, .loadDraw
                CP   RTYPE_OBJ_B7FB_CORE
                JP   Z, .loadB7FBCore
                CP   RTYPE_OBJ_B7FB_CORE_CHILD
                JP   Z, .loadDraw
                CP   RTYPE_OBJ_FINAL_STREAM_FB53
                JP   Z, .loadDraw
                CP   RTYPE_OBJ_B1D8_ROOT
                JP   Z, .loadB1D8
                CP   RTYPE_OBJ_B1D8_CHILD
                JP   Z, .loadB1D8
                CP   RTYPE_OBJ_C0_FINAL_SPRITE
                JP   Z, .loadDraw
                CP   RTYPE_OBJ_BG_PARTICLE
                JP   Z, .advance                  ; отдельный нижний Z-pass
                JP   .advance
.loadDraw:     LD   A, (RTypeObjects_ScanIndex)
                CALL RTypeObjects_LoadScratch
                JP   .draw
.loadVisible:  LD   A, (RTypeObjects_ScanIndex)
                CALL RTypeObjects_LoadScratch
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SUBSTATE)
                OR   A
                JP   Z, .advance
                JP   .draw
.loadTargeting:
                LD   A, (RTypeObjects_ScanIndex)
                CALL RTypeObjects_LoadScratch
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                AND  2
                JP   Z, .drawPair
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLASH_PALETTE)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                JP   .drawPair
.loadEnemy7294:
                LD   A, (RTypeObjects_ScanIndex)
                CALL RTypeObjects_LoadScratch
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                AND  2
                JP   Z, .draw
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_72_FLASH_PALETTE)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                JP   .draw
.loadFixed6E9B:
                LD   A, (RTypeObjects_ScanIndex)
                CALL RTypeObjects_LoadScratch
                ; `$6EC4` безусловно вызывает paired `$1C1B` для четырёх
                ; roots: всего восемь аппаратных descriptor records.
                LD   HL, #3042
                CALL .drawFixedPair
                LD   HL, #304E
                CALL .drawFixedPair
                LD   HL, #305A
                CALL .drawFixedPair
                LD   HL, #3066
                CALL .drawFixedPair
                JP   .advance
.drawFixedPair:
                PUSH HL
                LD   BC, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeSprite_DrawDescriptor
                POP  HL
                LD   DE, 6
                ADD  HL, DE
                LD   BC, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                JP   RTypeSprite_DrawDescriptor
.loadFormation78Child:
                LD   A, (RTypeObjects_ScanIndex)
                CALL RTypeObjects_LoadScratch
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                AND  2
                JR   Z, .formation78PaletteReady
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_78_FLASH_PALETTE)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
.formation78PaletteReady:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                CP   RTYPE_78_FIRST
                JP   Z, .drawPair
                JP   .draw
.loadA71DBody: LD   A, (RTypeObjects_ScanIndex)
                CALL RTypeObjects_LoadScratch
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                CP   RTYPE_A7_BODY_DEBRIS
                JP   Z, .advance
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                AND  2
                JP   Z, .draw
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_BODY_ALT_PALETTE)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                JP   .draw
.loadA71DAttachment:
                LD   A, (RTypeObjects_ScanIndex)
                CALL RTypeObjects_LoadScratch
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                AND  2
                JP   Z, .draw
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_A7_ATTACHMENT_ALT_PALETTE)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                JP   .draw
.loadB7FBCore: LD   A, (RTypeObjects_ScanIndex)
                CALL RTypeObjects_LoadScratch
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                CP   RTYPE_B7_CORE_EXPLODING
                JP   Z, .advance
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                AND  2
                JP   Z, .draw
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B7_CORE_FLASH_PALETTE)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                JP   .draw
.loadB1D8:     LD   A, (RTypeObjects_ScanIndex)
                CALL RTypeObjects_LoadScratch
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                AND  2
                JP   Z, .draw
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_B1_FLASH_PALETTE)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                JP   .draw
.loadLargeTerrain:
                LD   A, (RTypeObjects_ScanIndex)
                CALL RTypeObjects_LoadScratch
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                AND  2
                JP   Z, .draw
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_LARGE_FLASH_PALETTE)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                JP   .draw
.loadHandler60Root:
                LD   A, (RTypeObjects_ScanIndex)
                CALL RTypeObjects_LoadScratch
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                AND  2
                JP   Z, .draw
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_FLASH_PALETTE)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                JP   .draw
.loadHandler60Child:
                LD   A, (RTypeObjects_ScanIndex)
                CALL RTypeObjects_LoadScratch
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                CP   RTYPE_60_AUX_EXPLOSION_WAIT
                JP   NC, .draw
                ; `$68EE` выдаёт две аппаратные записи: тело и светящийся
                ; восьмикадровый overlay с отдельной anchor-позицией.
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR)
                LD   BC, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeSprite_DrawDescriptor
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_CHILD_OVERLAY)
                LD   BC, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_CHILD_OVERLAY_X)
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_60_CHILD_OVERLAY_Y)
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeSprite_DrawDescriptor
                JP   .advance
.loadDobBody:  LD   A, (RTypeObjects_ScanIndex)
                CALL RTypeObjects_LoadScratch
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                CP   RTYPE_DOB_BODY_DEATH
                JP   Z, .advance
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                AND  2
                JP   Z, .draw
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_FLASH_PALETTE)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                JP   .draw
.loadDobTentacle:
                LD   A, (RTypeObjects_ScanIndex)
                CALL RTypeObjects_LoadScratch
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                CP   RTYPE_DOB_TENTACLE_EXP_WAIT
                JP   Z, .advance
                JP   .draw
.loadDobEfObject:
                LD   A, (RTypeObjects_ScanIndex)
                CALL RTypeObjects_LoadScratch
                ; Debris `$E700` имеет один полностью невидимый initializer
                ; pass (state=1); обычные EF00 explosion records используют 0.
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                CP   1
                JP   Z, .advance
                ; Поток `$85FA`, установленный death-handler-ом `$E817`,
                ; рисуется через paired emitter `$1C1B` (`descriptor,+6`).
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_EXP_POINTER)
                LD   DE, #85FA
                OR   A
                SBC  HL, DE
                JP   C, .draw
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DOB_EXP_POINTER)
                LD   DE, #863A
                OR   A
                SBC  HL, DE
                JP   C, .drawPair
                JP   .draw
.loadEnemy6F89:
                LD   A, (RTypeObjects_ScanIndex)
                CALL RTypeObjects_LoadScratch
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                AND  2
                JP   Z, .drawPair
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_6F_FLASH_PALETTE)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                JP   .drawPair
.loadEnemy7D68:
                LD   A, (RTypeObjects_ScanIndex)
                CALL RTypeObjects_LoadScratch
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                AND  2
                JR   Z, .drawPair
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_7D_FLASH_PALETTE)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                JR   .drawPair
.loadEnemy696E:
                LD   A, (RTypeObjects_ScanIndex)
                CALL RTypeObjects_LoadScratch
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                AND  2
                JP   Z, .draw
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_69_FLASH_PALETTE)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                JP   .draw
.loadEnemy8561:
                LD   A, (RTypeObjects_ScanIndex)
                CALL RTypeObjects_LoadScratch
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                AND  2
                JR   Z, .drawPair
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_85_FLASH_PALETTE)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                JR   .drawPair
.loadEnemy5EED:
                LD   A, (RTypeObjects_ScanIndex)
                CALL RTypeObjects_LoadScratch
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                AND  2
                JR   Z, .drawPair
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_5E_FLASH_PALETTE)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                JR   .drawPair
.loadPair:     LD   A, (RTypeObjects_ScanIndex)
                CALL RTypeObjects_LoadScratch
                JR   .drawPair
.loadChild8D85:
                LD   A, (RTypeObjects_ScanIndex)
                CALL RTypeObjects_LoadScratch
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                AND  2
                JR   Z, .drawPair
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_8D_FLASH_PALETTE)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                ; `$8035` и все три `$8D85` renderer-а вызывают `$1C1B`:
                ; это две соседние 6-байтные descriptor-записи, а не одна.
                JR   .drawPair
.loadChild915B:
                LD   A, (RTypeObjects_ScanIndex)
                CALL RTypeObjects_LoadScratch
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_FLAGS)
                AND  2
                JR   Z, .draw
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_91_FLASH_PALETTE)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
                ; Активный Python M72EnemyWorld.draw выводит Multipart915BChild
                ; один раз. Кратность общих объектов ниже приходит из AST.
                JR   .draw
.drawPair:     LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR)
                LD   BC, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeSprite_DrawDescriptor
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR)
                LD   DE, 6
                ADD  HL, DE
                LD   BC, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeSprite_DrawDescriptor
                JP   .advance
.loadWalker:   LD   A, (RTypeObjects_ScanIndex)
                CALL RTypeObjects_LoadScratch
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_SUBSTATE)
                OR   A
                JR   Z, .advance
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_STATE)
                CP   RTYPE_WALKER_FALLING
                JR   Z, .walkerSecondary
                CP   RTYPE_WALKER_SCRIPTED
                JR   NZ, .draw
.walkerSecondary:
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_WALKER_SECONDARY)
                LD   (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE), A
.draw:         LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_TYPE)
                LD   L, A
                LD   H, 0
                LD   DE, RTypePyObjectDrawCount
                ADD  HL, DE
                LD   A, (HL)
                CP   2
                JP   Z, .drawPair
                LD   HL, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_DESCRIPTOR)
                LD   BC, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_X)
                LD   DE, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_Y)
                LD   A, (RTYPE_OBJECT_SCRATCH + RTYPE_OBJ_PALETTE)
                CALL RTypeSprite_DrawDescriptor
.advance:      LD   A, (RTypeObjects_ScanIndex)
                INC  A
                LD   (RTypeObjects_ScanIndex), A
                LD   HL, (.scanPtr)
                LD   DE, RTYPE_OBJECT_REC_SIZE
                ADD  HL, DE
                LD   (.scanPtr), HL
                CP   RTYPE_OBJECT_COUNT
                JP   C, .next
                RET
.scanPtr:      DEFW 0
