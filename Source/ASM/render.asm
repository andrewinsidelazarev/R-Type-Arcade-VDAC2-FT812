; ============================================================================
; Отрисовщик аркадного R-Type.
; Нативная графика M72 заранее преобразована в логические ассеты 640x480.
; FT812 выполняет только NEAREST 640x480 -> 1024x768 (A=E=160).
; ============================================================================

SPRITE_SCALE    EQU 160                  ; 256 / (8/5)

; Смена TITLE -> GAME перезаписывает общие диапазоны RAM_G. Этот короткий
; display list отцепляет активный title от его атласов до начала DMA.
Render_BlankFrame:
                CALL Render_WaitPreviousSwap
                XOR  A
                LD   (RTypePyCommandFlushCount), A
                FT_CMD_Start
                FT_DL_Start
                FT_ClearColorRGB 0, 0, 0
                FT_ClearAll
                FT_Display
                JP   Render_SubmitFrame

Render_Frame:
                ; Streamed chunks may reach the FT812 while the list is still
                ; being assembled. RAM_DL must therefore be writable before
                ; the first command, not only before the final chunk.
                CALL Render_WaitPreviousSwap
                XOR  A
                LD   (RTypePyCommandFlushCount), A
                FT_CMD_Start
                FT_DL_Start

                FT_VertexFormat 3                ; единицы по 1/8 физического пикселя
                FT_ClearColorRGB 0, 0, 0
                FT_ClearAll

                ifdef RTYPE_TSFM_TEST
                CALL Render_TsfmDetectBar        ; полоса результата детекта TSFM
                endif
                ifdef RTYPE_TSFM_DEBUG
                CALL Render_TsfmDebug            ; состояние плеера музыки
                endif
                ; Диспетчер сцен по GameMode: титул собирается из примитивов
                ; тайловой памяти и sprite RAM оригинала; игра — свой рендер.
                LD   A, (GameMode)
                OR   A
                JR   NZ, .gameScene
                CALL M72Video_DrawTitle
                JR   .sceneDone
.gameScene:
                ; Z-порядок транслирован из Game.render: back, самые нижние
                ; background particles, остальные objects/fixed/player, front.
                CALL Render_WorldBackground
                CALL RTypePyDrawBackgroundParticles
                CALL RTypeObjects_Draw
                CALL RTypeFixedPlayer_Draw
                ; Состояние вычисляется из WIDTH/HEIGHT активного Python
                ; генератором rtype_python_translator.py. Terrain оставляет
                ; собственные A/C/E/F, непригодные для logical blit.
                CALL RTypePyLogicalBitmapState
                CALL RTypePyRenderPlayerLifecycle
                CALL Render_M72PlayerShots
                CALL Render_M72WaveProjectile
                CALL RTypePyRenderChargeOrb
                CALL Render_WorldForeground
                CALL Render_ArcadeBackground     ; HUD всегда поверх playfield
                CALL Render_M72Hud                ; живой семизначный score поверх заготовки
                CALL RTypePyRenderBeamMeter
                CALL RTypePyRenderLives           ; ArcadeLives активного Python
.sceneDone:

                FT_Display
Render_SubmitFrame:
                ; RAM_DL уже свободна; закончить текущий streamed command list,
                ; выполнить его целиком и только затем запросить FRAME swap.
                FT_CMD_Write
                RET  C
                CALL FT.Coprocessor.WaitFlush
                RET  C
                FT_WR_REG8 FT_REG_DLSWAP, FT_DLSWAP_FRAME
                RET

; Кадровый протокол из Zuna Deluxe. Вызывается ДО сборки нового списка: это
; обязательно, когда список длиннее host-окна и ранние chunks уже отправляются.
Render_WaitPreviousSwap:
                LD   L, 64
.waitSwapInt:   FT_RD_REG8 FT_REG_INT_FLAGS
                AND  FT_INT_SWAP
                JR   NZ, .gotSwapInt
                DEC  L
                JR   NZ, .waitSwapInt
                JR   .waitDLSwap
.gotSwapInt:    FT_WR_REG8 FT_REG_INT_FLAGS, FT_INT_SWAP
.waitDLSwap:    FT_RD_REG8 FT_REG_DLSWAP
                AND  3
                JR   NZ, .waitDLSwap
                RET

; Нижние 30 logical строк интерфейса v002; landscape в asset больше не входит.
Render_ArcadeBackground:
                FT_BitmapTransformA SPRITE_SCALE
                FT_BitmapTransformB 0
                FT_BitmapTransformC 0
                FT_BitmapTransformD 0
                FT_BitmapTransformE SPRITE_SCALE
                FT_BitmapTransformF 0
                FT_BitmapSource ARCADE_BG_RAMG
                FT_BitmapLayout FT_RGB565, ARCADE_BG_STRIDE, ARCADE_BG_HEIGHT
                FT_BitmapSize FT_NEAREST, FT_BORDER, FT_BORDER, 1024, 48
                FT_ColorRGB 255, 255, 255
                FT_Begin FT_BITMAPS
                FT_Vertex2f 0, 720 * 8
                FT_End
                RET

; Две живые 512x512 ring-текстуры M72. Они обновляются только новой
; 64x240-полосой, поэтому display list кадра содержит два bitmap вместо тысяч
; команд на отдельные tiles. Hardware palette slot остаётся high nibble index8.
Render_WorldTerrain:
                CALL Render_WorldBackground
                JP   Render_WorldForeground

Render_WorldBackground:
                ; Реализация генерируется Python-транслятором и рисует восемь
                ; аппаратных strip slots без построчной перекладки через Z80.
                JP   RTypePyRenderWorldBackground
                if 0
                FT_ScissorXY 0, 0
                FT_ScissorSize 1024, 720
                FT_BitmapTransformA 96           ; native 384 -> physical 1024
                FT_BitmapTransformB 0
                FT_BitmapTransformD 0
                FT_BitmapTransformE 85           ; native 240 -> physical 720
                LD   HL, (RTypeWorldBgScrollQ8 + 1)
                LD   DE, 64
                ADD  HL, DE
                CALL Render_WorldTransformC
                LD   HL, (RTypeWorldBgYScrollQ8 + 1)
                LD   DE, 128
                ADD  HL, DE
                CALL Render_WorldTransformF
                FT_PaletteSource RTYPE_WORLD_TILE_PALETTE_RAMG
                FT_BitmapSource RTYPE_WORLD_BG_TEXTURE_RAMG
                FT_BitmapLayout FT_PALETTED4444, 512, 512
                FT_BitmapSize FT_NEAREST, FT_REPEAT, FT_REPEAT, 1024, 720
                FT_ColorRGB 255, 255, 255
                FT_Begin FT_BITMAPS
                FT_Vertex2f 0, 0
                FT_End
                RET
                endif

Render_WorldForeground:
                CALL RTypePyRenderWorldForeground
                FT_ScissorXY 0, 0
                FT_ScissorSize 1024, 768
                RET
                if 0
                FT_ScissorXY 0, 0
                FT_ScissorSize 1024, 720
                FT_BitmapTransformA 96           ; native 384 -> physical 1024
                FT_BitmapTransformB 0
                FT_BitmapTransformD 0
                FT_BitmapTransformE 85           ; native 240 -> physical 720
                LD   HL, (RTypeWorldFgScrollQ8 + 1)
                LD   DE, 64
                ADD  HL, DE
                CALL Render_WorldTransformC
                LD   HL, (RTypeWorldFgYScrollQ8 + 1)
                LD   DE, 128
                ADD  HL, DE
                CALL Render_WorldTransformF
                FT_PaletteSource RTYPE_WORLD_TILE_PALETTE_RAMG + 512
                FT_BitmapSource RTYPE_WORLD_FG_TEXTURE_RAMG
                FT_BitmapLayout FT_PALETTED4444, 512, 512
                FT_BitmapSize FT_NEAREST, FT_REPEAT, FT_REPEAT, 1024, 720
                FT_Begin FT_BITMAPS
                FT_Vertex2f 0, 0
                FT_End
                FT_ScissorXY 0, 0
                FT_ScissorSize 1024, 768
                RET
                endif

; HL=native source coordinate 0..511. C/F используют signed 8.8 value.
Render_WorldTransformC:
                LD   A, H
                AND  1
                LD   C, A
                LD   D, L
                LD   E, 0
                LD   B, #17
                JP   FT.Coprocessor.Command_BCDE

Render_WorldTransformF:
                LD   A, H
                AND  1
                LD   C, A
                LD   D, L
                LD   E, 0
                LD   B, #1A
                JP   FT.Coprocessor.Command_BCDE

; Статические объекты M72 кадра 900 (звёзды/частицы) уже упорядочены как в MAME.
; R-9 и его хвост исключены: ниже они рисуются из живого логического состояния.
Render_M72SceneSprites:
                FT_ColorRGB 255, 255, 255
                FT_Begin FT_BITMAPS
                LD   HL, M72SceneInstanceTable
                LD   (.instancePtr), HL
                LD   A, M72_SCENE_INSTANCE_COUNT
                LD   (.instanceCount), A
.next:
                LD   HL, (.instancePtr)
                LD   A, (HL)                     ; индекс ассета
                INC  HL
                LD   C, (HL)
                INC  HL
                LD   B, (HL)
                INC  HL
                LD   (M72SprX), BC
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                INC  HL
                LD   (M72SprY), DE
                LD   (.instancePtr), HL
                CALL M72_CopyAsset
                LD   BC, (M72SprX)
                LD   DE, (M72SprY)
                CALL FT.Coprocessor.Vertex2f
                LD   HL, .instanceCount
                DEC  (HL)
                JR   NZ, .next
                FT_End
                RET
.instancePtr:   DEFW 0
.instanceCount: DEFB 0

; До четырёх живых врагов Stage 1. Изображения — подлинные объекты M72 из
; frame 1500, положение приходит из игрового состояния, а не из готового кадра.
                ifdef RTYPE_STAGE_GAME_EXPERIMENT
Render_M72Enemies:
                FT_ColorRGB 255, 255, 255
                FT_Begin FT_BITMAPS
                LD   IX, ArcadeEnemyTable
                LD   A, ARCADE_ENEMY_COUNT
                LD   (.enemyCount), A
.next:         LD   A, (IX + ARCADE_ENEMY_ACTIVE)
                OR   A
                JR   Z, .advance
                LD   L, (IX + ARCADE_ENEMY_X)
                LD   H, (IX + ARCADE_ENEMY_X + 1)
                CALL M72_LogicalToVertex
                LD   (M72SprX), BC
                LD   L, (IX + ARCADE_ENEMY_Y)
                LD   H, (IX + ARCADE_ENEMY_Y + 1)
                CALL M72_LogicalToVertex
                LD   (M72SprY), BC
                LD   A, (IX + ARCADE_ENEMY_TYPE)
                LD   E, A
                LD   D, 0
                LD   HL, M72EnemyAssetTable
                ADD  HL, DE
                LD   A, (HL)
                CALL M72_CopyAsset
                LD   BC, (M72SprX)
                LD   DE, (M72SprY)
                CALL FT.Coprocessor.Vertex2f
.advance:      LD   DE, ARCADE_ENEMY_REC_SIZE
                ADD  IX, DE
                LD   HL, .enemyCount
                DEC  (HL)
                JR   NZ, .next
                FT_End
                RET
.enemyCount:   DEFB 0

M72EnemyAssetTable:
                DEFB M72_ENEMY_PATROL_ASSET, M72_ENEMY_RED_ASSET
                DEFB M72_ENEMY_RED_FLIP_ASSET, M72_ENEMY_WALKER_ASSET
                endif

; Семь цифр счёта из оригинального M72 tile ROM. `$191B` гасит максимум
; первые шесть нулей, поэтому при нулевом счёте последняя ячейка всё равно
; показывает `0`. Атлас сохранён в RAM_G после перехода с титула: HUD не
; использует встроенный шрифт FT812 и совпадает с канонической Python-версией.
Render_M72Hud:
                FT_BitmapTransformA SPRITE_SCALE
                FT_BitmapTransformB 0
                FT_BitmapTransformC 0
                FT_BitmapTransformD 0
                FT_BitmapTransformE SPRITE_SCALE
                FT_BitmapTransformF 0
                FT_BitmapLayout FT_ARGB4, M72_GLYPH_W * 2, M72_GLYPH_H
                FT_BitmapSize FT_NEAREST, FT_BORDER, FT_BORDER, M72_GLYPH_PHYS_W, M72_GLYPH_PHYS_H
                FT_ColorRGB 255, 255, 255
                FT_Begin FT_BITMAPS
                LD   HL, 744 * 8                  ; `(HUD_Y+15)*1.6`, VERTEX_FORMAT=3
                LD   (M72Video_DrawTileLayer.screenY), HL
                LD   A, 7                        ; source columns 15…21 минус HUD view 8
                LD   (.column), A
                XOR  A
                LD   (.seenNonZero), A
                LD   A, 7
                LD   (.digitsRemaining), A
                ; Старший допустимый разряд — младшая тетрада byte 3. Старшая
                ; тетрада служит только контролем переполнения до 9,999,999.
                LD   A, (ArcadeScore + 3)
                AND  #0F
                CALL .scoreDigit
                LD   HL, ArcadeScore + 2
                LD   B, 3
.byte:         LD   A, (HL)
                RRCA
                RRCA
                RRCA
                RRCA
                AND  #0F
                CALL .scoreDigit
                LD   A, (HL)
                AND  #0F
                CALL .scoreDigit
                DEC  HL
                DJNZ .byte
                FT_End
                RET
.scoreDigit:   PUSH HL
                PUSH BC
                LD   C, A                        ; C сохраняет цифру во время проверок
                LD   HL, .digitsRemaining
                DEC  (HL)
                OR   A
                JR   NZ, .firstVisible
                LD   A, (.seenNonZero)
                OR   A
                JR   NZ, .draw
                LD   A, (.digitsRemaining)
                OR   A
                JR   Z, .draw                    ; седьмой ноль не гасится
                JR   .advanceColumn              ; blank `$11`: команды bitmap нет
.firstVisible: LD   A, 1
                LD   (.seenNonZero), A
.draw:         LD   A, C
                LD   E, A
                LD   D, 0
                LD   HL, M72HudDigitGlyph
                ADD  HL, DE
                LD   A, (HL)
                PUSH AF
                LD   HL, .column
                LD   A, (HL)
                LD   (M72Video_DrawTileLayer.column), A
                POP  AF
                CALL M72Video_EmitTile
.advanceColumn:
                LD   HL, .column
                INC  (HL)
                POP  BC
                POP  HL
                RET
.column:       DEFB 0
.seenNonZero:  DEFB 0
.digitsRemaining:
                DEFB 0

M72HudDigitGlyph:
                DEFB M72_DIGIT_0_GLYPH, M72_DIGIT_1_GLYPH
                DEFB M72_DIGIT_2_GLYPH, M72_DIGIT_3_GLYPH
                DEFB M72_DIGIT_4_GLYPH, M72_DIGIT_5_GLYPH
                DEFB M72_DIGIT_6_GLYPH, M72_DIGIT_7_GLYPH
                DEFB M72_DIGIT_8_GLYPH, M72_DIGIT_9_GLYPH

; Три fixed-slot выстрела `$04D6`, как в Python/M72. X хранится в нативной
; системе M72, а Y — готовой логической строкой offline-crop: это не позволяет
; рендереру незаметно добавить ещё один игровой шаг при переводе координат.
Render_M72PlayerShots:
                FT_ColorRGB 255, 255, 255
                FT_Begin FT_BITMAPS
                LD   IX, ArcadeShotTable
                LD   A, ARCADE_SHOT_COUNT
                LD   (.shotCount), A
.nextShot:      LD   A, (IX + ARCADE_SHOT_ACTIVE)
                CP   ARCADE_SHOT_FLIGHT
                JR   C, .advance                 ; FREE/WAIT ещё не видимы
                CP   ARCADE_SHOT_TERMINAL
                JR   NC, .advance                ; terminal рисуется отдельным impact
                LD   L, (IX + ARCADE_SHOT_X)
                LD   H, (IX + ARCADE_SHOT_X + 1)
                LD   DE, -#0148                  ; native world -> левый край crop
                ADD  HL, DE
                CALL RTypeSprite_NativeXToVertex
                LD   (M72SprX), BC
                LD   L, (IX + ARCADE_SHOT_LOGICAL_Y)
                LD   H, (IX + ARCADE_SHOT_LOGICAL_Y + 1)
                CALL M72_LogicalToVertex
                LD   (M72SprY), BC
                LD   A, M72_R9_SHOT_ASSET
                CALL M72_CopyAsset
                LD   BC, (M72SprX)
                LD   DE, (M72SprY)
                CALL FT.Coprocessor.Vertex2f
.advance:       LD   DE, ARCADE_SHOT_REC_SIZE
                ADD  IX, DE
                LD   HL, .shotCount
                DEC  (HL)
                JR   NZ, .nextShot
                FT_End
                RET
.shotCount:     DEFB 0

; Настоящий Wave Cannon появляется только после двухкадровой задержки M72.
; Две ROM-фазы сменяются раз в два кадра; X остаётся нативным M72 anchor.
Render_M72WaveProjectile:
                LD   A, (ArcadeWaveActive)
                OR   A
                RET  Z
                LD   A, (ArcadeWaveDelay)
                OR   A
                RET  NZ
                FT_ColorRGB 255, 255, 255
                FT_Begin FT_BITMAPS

                ; Неподвижная вспышка у носа: длительности фаз 2+2+2+1.
                LD   A, (ArcadeWaveAnim)
                CP   7
                JR   NC, .main
                CP   2
                JR   C, .release0
                CP   4
                JR   C, .release1
                CP   6
                JR   C, .release2
                LD   A, M72_R9_WAVE_RELEASE_3
                JR   .releaseDraw
.release0:      LD   A, M72_R9_WAVE_RELEASE_0
                JR   .releaseDraw
.release1:      LD   A, M72_R9_WAVE_RELEASE_1
                JR   .releaseDraw
.release2:      LD   A, M72_R9_WAVE_RELEASE_2
.releaseDraw:   CALL M72_CopyAsset
                LD   HL, (ArcadeWaveReleaseX)
                LD   DE, -#0148
                ADD  HL, DE
                CALL RTypeSprite_NativeXToVertex
                LD   (M72SprX), BC
                LD   HL, (ArcadeWaveLogicalY)
                CALL M72_LogicalToVertex
                LD   (M72SprY), BC
                LD   BC, (M72SprX)
                LD   DE, (M72SprY)
                CALL FT.Coprocessor.Vertex2f

.main:
                LD   HL, (ArcadeWaveX)
                LD   DE, -#0148
                ADD  HL, DE
                CALL RTypeSprite_NativeXToVertex
                LD   (M72SprX), BC
                LD   HL, (ArcadeWaveLogicalY)
                CALL M72_LogicalToVertex
                LD   (M72SprY), BC
                LD   A, (ArcadeWaveAnim)
                INC  A
                SRL  A
                AND  1
                JR   NZ, .phaseB
                LD   A, M72_R9_WAVE_ASSET_A
                JR   .copy
.phaseB:        LD   A, M72_R9_WAVE_ASSET_B
.copy:          CALL M72_CopyAsset
                LD   BC, (M72SprX)
                LD   DE, (M72SprY)
                CALL FT.Coprocessor.Vertex2f
                FT_End
                RET

; A = индекс ассета. Добавить в буфер пять команд состояния FT812.
M72_CopyAsset:
                LD   L, A
                LD   H, 0
                ADD  HL, HL                      ; x2
                ADD  HL, HL                      ; x4
                LD   D, H
                LD   E, L                        ; DE = x4
                ADD  HL, HL                      ; x8
                ADD  HL, HL                      ; x16
                ADD  HL, DE                      ; x20
                LD   DE, M72SpriteTable
                ADD  HL, DE
                LD   BC, M72_SPRITE_REC_SIZE
                JP   FT.Coprocessor.Copy

; HL = знаковая логическая координата в пикселях, BC = знаковые единицы VERTEX2F.
; Таблица хранит round(logical * 64/5): физический x8/5 в единицах 1/8 пикселя.
M72_LogicalToVertex:
                BIT  7, H
                JR   NZ, .negative
.lookup:        ADD  HL, HL
                LD   DE, M72LogicalToVertexTable
                ADD  HL, DE
                LD   C, (HL)
                INC  HL
                LD   B, (HL)
                RET
.negative:      XOR  A
                ; 16-битный модуль через дополнение до двух. XOR между SUB и
                ; SBC терял borrow младшего byte, поэтому прежняя ветка была
                ; неверна почти для всех отрицательных logical coordinates.
                LD   A, L
                CPL
                LD   L, A
                LD   A, H
                CPL
                LD   H, A
                INC  HL
                CALL .lookup
                LD   A, C
                CPL
                LD   C, A
                LD   A, B
                CPL
                LD   B, A
                INC  BC
                RET

M72SprX:        DEFW 0
M72SprY:        DEFW 0

                ifdef RTYPE_TSFM_TEST
; ---------------------------------------------------------------------------
; Render_TsfmDetectBar — широкая полоса вверху экрана по результату детекта
; TurboSound FM: зелёная — чип ответил (как в WildCommander TFMDET),
; красная — не ответил. Видна даже при полной тишине.
; ---------------------------------------------------------------------------
Render_TsfmDetectBar:
                LD   A, (TsfmMusic_Present)
                OR   A
                JR   Z, .absent
                LD   C, 0 : LD D, 220 : LD E, 0          ; зелёная
                JR   .draw
.absent:        LD   C, 220 : LD D, 0 : LD E, 0          ; красная
.draw:          CALL FT.Coprocessor.ColorRGB
                FT_Begin FT_RECTS
                LD   BC, 0
                LD   DE, 0
                CALL FT.Coprocessor.Vertex2f
                LD   BC, 1024 * 8
                LD   DE, 40 * 8
                CALL FT.Coprocessor.Vertex2f
                FT_End
                FT_ColorRGB 255, 255, 255
                RET
                endif

                ifdef RTYPE_TSFM_DEBUG
; ---------------------------------------------------------------------------
; Render_TsfmDebug — состояние плеера музыки встроенным шрифтом FT812:
; номер страницы потока, указатель и счётчик паузы. Нужно, чтобы видеть,
; идёт ли воспроизведение по страницам на настоящем пейджинге.
; ---------------------------------------------------------------------------
Render_TsfmDebug:
                CALL Render_DebugIdentity
                FT_ColorRGB 255, 240, 120
                LD   A, (TsfmMusic_PageIndex)
                LD   C, A
                LD   B, 0
                LD   DE, 0
                FT_NumberDEBC 20, 20, 29, 0
                LD   BC, (TsfmMusic_Ptr)
                LD   DE, 0
                FT_NumberDEBC 120, 20, 29, 0
                LD   A, (TsfmMusic_Wait)
                LD   C, A
                LD   B, 0
                LD   DE, 0
                FT_NumberDEBC 320, 20, 29, 0
                FT_ColorRGB 255, 255, 255
                RET
                endif

; Единичная матрица: встроенный шрифт FT812 — тоже битмап, и общий масштаб ×1.6
; рвёт глифы. Используется только отладочным выводом.
Render_DebugIdentity:
                FT_BitmapTransformA 256
                FT_BitmapTransformB 0
                FT_BitmapTransformC 0
                FT_BitmapTransformD 0
                FT_BitmapTransformE 256
                FT_BitmapTransformF 0
                RET
