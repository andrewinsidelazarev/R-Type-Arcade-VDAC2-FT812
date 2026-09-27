; ============================================================================
; Предсохранённый 226-кадровый вылет R-9 и малый fixed-player автомат.
;
; Таблица получена m72_player_launch_stream.py из того же потока Sprite RAM,
; который проверяет готовая Python-версия. Одна 14-байтная запись уже содержит
; логические координаты 640x480, индекс наклона, launch-эффект и native anchor.
; В VBlank нет делений, интерполяции и распаковки: только чтение одной записи.
; Код расположен в постоянно видимой page #00 вместе с таблицей, потому что
; Core упирается в буфер display list CMD_ADDRESS_PTR, а slot2
; нужен enemy bank-ам.
; ============================================================================

RTypePlayerLaunchTable:
                INCBIN "Assets/Converted/Arcade/Player/R9_LAUNCH_LOGICAL.bin"
RTypePlayerLaunchTable_End:
                ASSERT RTypePlayerLaunchTable_End - RTypePlayerLaunchTable == ARCADE_INTRO_FRAMES * ARCADE_INTRO_REC_SIZE

; Выбрать запись ArcadeIntroFrame после текущего object pass.
; Формат `<hhBBhhHH`: player X/Y, body, effect, effect X/Y, native X/Y.
ArcadePlayer_IntroUpdate:
                LD   HL, (ArcadeIntroFrame)
                ADD  HL, HL                      ; index * 2
                LD   D, H
                LD   E, L                        ; DE = index * 2
                ADD  HL, HL                      ; index * 4
                ADD  HL, HL                      ; index * 8
                ADD  HL, HL                      ; index * 16
                OR   A
                SBC  HL, DE                      ; index * 14
                LD   DE, RTypePlayerLaunchTable
                ADD  HL, DE

                XOR  A
                LD   (ArcadePlayerX), A           ; дробь Q16.8 уже равна нулю
                LD   (ArcadePlayerY), A
                LD   A, (HL)
                LD   (ArcadePlayerX + 1), A
                INC  HL
                LD   A, (HL)
                LD   (ArcadePlayerX + 2), A
                INC  HL
                LD   A, (HL)
                LD   (ArcadePlayerY + 1), A
                INC  HL
                LD   A, (HL)
                LD   (ArcadePlayerY + 2), A
                INC  HL

                LD   A, (HL)                     ; body index 0…4 -> pitch 0…32
                ADD  A, A
                ADD  A, A
                ADD  A, A
                LD   (ArcadePlayerPitch), A
                INC  HL
                LD   A, (HL)
                LD   (ArcadeIntroEffectKind), A
                INC  HL
                LD   A, (HL)
                LD   (ArcadeIntroEffectX), A
                INC  HL
                LD   A, (HL)
                LD   (ArcadeIntroEffectX + 1), A
                INC  HL
                LD   A, (HL)
                LD   (ArcadeIntroEffectY), A
                INC  HL
                LD   A, (HL)
                LD   (ArcadeIntroEffectY + 1), A
                INC  HL

                ; Enemy handlers следующего кадра получают исходный native
                ; anchor напрямую: обратный scale на Z80 здесь не нужен.
                LD   A, (HL)
                LD   (RTypePlayerNativeX), A
                INC  HL
                LD   A, (HL)
                LD   (RTypePlayerNativeX + 1), A
                INC  HL
                LD   A, (HL)
                LD   (RTypePlayerNativeY), A
                INC  HL
                LD   A, (HL)
                LD   (RTypePlayerNativeY + 1), A

                LD   HL, (ArcadeIntroFrame)
                INC  HL
                LD   (ArcadeIntroFrame), HL
                RET

; ArcadePlayer_UpdatePitch теперь генерирует pyz80_compiler из декларативного
; call_adapters manifest и размещает в свободном окне page #00/#1000.
                include "generated_python_call_adapters.asm"

; Динамический R-9. Пять корпусов и четыре launch-эффекта совпадают с Python.
; Эффект существует только пока 226-кадровая intro-таблица дала kind 1…4;
; после вылета здесь выводится ровно один корпус, без постоянного синего хвоста.
Render_M72DynamicPlayer:
                ; Director `$22CD` удаляет fixed R-9 record на age 117. Флаг
                ; ведёт тот же lifecycle, поэтому после смерти корабль не
                ; остаётся нарисованным поверх остановленного playfield.
                LD   A, (ArcadePlayerVisible)
                OR   A
                RET  Z
                FT_ColorRGB 255, 255, 255
                FT_Begin FT_BITMAPS

                ; Launch-эффект рисуется первым и только по текущей записи.
                LD   A, (ArcadeIntroEffectKind)
                OR   A
                JR   Z, .body
                CP   M72_R9_LAUNCH_ASSET_COUNT + 1
                JR   NC, .body                   ; повреждённый kind не читать
                DEC  A
                LD   E, A
                LD   D, 0
                LD   HL, M72R9LaunchAssetTable
                ADD  HL, DE
                LD   A, (HL)
                LD   (.effectAsset), A
                LD   HL, (ArcadeIntroEffectX)
                BIT  7, H
                JR   Z, .effectFull
                ; VERTEX2F bt8xxemu не принимает отрицательную X. Не прячем
                ; частично вошедший объект: сдвигаем source на -X столбцов и
                ; уменьшаем BITMAP_SIZE, как обычное экранное clipping Python.
                LD   A, L
                NEG
                LD   C, A
                LD   A, (.effectAsset)
                CALL M72_CopyAssetLeftClip
                JR   C, .body                    ; весь эффект ещё левее экрана
                LD   BC, 0
                LD   (M72SprX), BC
                JR   .effectY
.effectFull:   CALL M72_LogicalToVertex
                LD   (M72SprX), BC
                LD   A, (.effectAsset)
                CALL M72_CopyAsset
.effectY:      LD   HL, (ArcadeIntroEffectY)
                CALL M72_LogicalToVertex
                LD   (M72SprY), BC
                LD   BC, (M72SprX)
                LD   DE, (M72SprY)
                CALL FT.Coprocessor.Vertex2f

.body:         ; Выбрать точный корпус до обработки X: та же запись нужна и
                ; полному bitmap, и варианту частичной левой обрезки.
                LD   A, (ArcadePlayerPitch)
                SRL  A
                SRL  A
                SRL  A
                LD   E, A
                LD   D, 0
                LD   HL, M72R9PitchAssetTable
                ADD  HL, DE
                LD   A, (HL)
                LD   (.bodyAsset), A
                LD   HL, (ArcadePlayerX + 1)
                BIT  7, H
                JR   Z, .bodyFull
                LD   A, L
                NEG
                LD   C, A
                LD   A, (.bodyAsset)
                CALL M72_CopyAssetLeftClip
                JR   C, .done                    ; корпус целиком за левым краем
                LD   BC, 0
                LD   (M72SprX), BC
                JR   .bodyY
.bodyFull:     CALL M72_LogicalToVertex
                LD   (M72SprX), BC
                LD   A, (.bodyAsset)
                CALL M72_CopyAsset
.bodyY:        LD   HL, (ArcadePlayerY + 1)
                ; Python: player_y + PITCH_CROP_TOP[pitch] - 1.
                PUSH HL
                LD   A, (ArcadePlayerPitch)
                SRL  A
                SRL  A
                SRL  A
                LD   E, A
                LD   D, 0
                LD   HL, M72R9PitchCropTopTable
                ADD  HL, DE
                LD   A, (HL)
                DEC  A
                LD   E, A
                RLCA
                SBC  A, A
                LD   D, A
                POP  HL
                ADD  HL, DE
                CALL M72_LogicalToVertex
                LD   (M72SprY), BC
                LD   BC, (M72SprX)
                LD   DE, (M72SprY)
                CALL FT.Coprocessor.Vertex2f

.done:         FT_End
                RET
.effectAsset:  DEFB 0
.bodyAsset:    DEFB 0

; A=asset, C=число невидимых логических столбцов слева. Вернуть CF=1, если
; bitmap целиком вне экрана. Иначе выдать пять изменённых state-команд FT812:
; исходные пиксели не копируются, меняются только BITMAP_SOURCE и BITMAP_SIZE.
; Это редкая ветка первых кадров launch; обычная игра использует CopyAsset.
M72_CopyAssetLeftClip:
                LD   (.asset), A
                LD   A, C
                LD   (.crop), A
                LD   A, (.asset)
                LD   L, A
                LD   H, 0
                LD   DE, M72SpriteLogicalWidthTable
                ADD  HL, DE
                LD   A, (HL)
                LD   C, A                        ; C = полная logical width
                LD   A, (.crop)
                CP   C
                JR   NC, .invisible
                LD   A, (.crop)
                LD   B, A
                LD   A, C
                SUB  B
                LD   (.remaining), A

                ; HL = M72SpriteTable + asset*20.
                LD   A, (.asset)
                LD   L, A
                LD   H, 0
                ADD  HL, HL                      ; x2
                ADD  HL, HL                      ; x4
                LD   D, H
                LD   E, L                        ; DE=x4
                ADD  HL, HL                      ; x8
                ADD  HL, HL                      ; x16
                ADD  HL, DE                      ; x20
                LD   DE, M72SpriteTable
                ADD  HL, DE
                LD   DE, .state
                LD   BC, M72_SPRITE_REC_SIZE
                LDIR

                ; ARGB4444: один скрытый столбец сдвигает source на два байта.
                LD   A, (.crop)
                ADD  A, A
                LD   E, A
                LD   D, 0
                LD   HL, (.state)
                ADD  HL, DE
                LD   (.state), HL
                JR   NC, .sourceReady
                LD   HL, .state + 2
                INC  (HL)                        ; carry в биты 16…21 RAM_G
.sourceReady:
                ; physical width = ceil(remaining * 8 / 5). Размеры launch
                ; меньше 128 физических пикселей, поэтому SIZE_H остаётся 0.
                LD   A, (.remaining)
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL                      ; remaining * 8
                LD   DE, 4
                ADD  HL, DE
                LD   B, 0
                LD   DE, 5
.divide5:      OR   A
                SBC  HL, DE
                JR   C, .widthReady
                INC  B
                JR   .divide5
.widthReady:   LD   A, B
                ADD  A, A                        ; width bits 0…6 -> byte 17 bits 1…7
                LD   (.state + 17), A             ; height всегда <256, bit 0 = 0
                XOR  A
                LD   (.state + 18), A             ; width <128, старшие биты = 0
                LD   HL, .state
                LD   BC, M72_SPRITE_REC_SIZE
                CALL FT.Coprocessor.Copy
                OR   A                           ; CF=0: state выдан
                RET
.invisible:    SCF
                RET
.asset:        DEFB 0
.crop:         DEFB 0
.remaining:    DEFB 0
.state:        DEFS M72_SPRITE_REC_SIZE, 0

; Нарисовать fixed-player после dynamic enemy list и до корпуса R-9, как
; Python `enemy_world.draw -> force.draw -> bits.draw -> player`. Code-bank #E6
; к этому моменту уже снят, поэтому FT command buffer
; CMD_ADDRESS_PTR снова принадлежит
; Core page #06 и ни одна команда копроцессора не пишет поверх bank-кода.
RTypeFixedPlayer_Draw:
                LD   A, (ArcadeForceLevel)
                OR   A
                JR   Z, .bits
                LD   A, (ArcadeForcePalette)
                CP   #10
                JR   NC, .bits
                LD   HL, (ArcadeForceDescriptor)
                LD   BC, (ArcadeForceXQ8 + 1)
                LD   DE, (ArcadeForceYQ8 + 1)
                CALL RTypeSprite_DrawDescriptor
.bits:         LD   IX, ArcadeBit0Record
                CALL RTypeFixedPlayer_DrawBit
                LD   IX, ArcadeBit1Record
                JP   RTypeFixedPlayer_DrawBit

RTypeFixedPlayer_DrawBit:
                LD   A, (IX + 0)                 ; active
                OR   A
                RET  Z
                LD   A, (IX + 7)                 ; palette slot
                CP   #10
                RET  NC
                LD   L, (IX + 13)                ; descriptor
                LD   H, (IX + 14)
                LD   C, (IX + 2)                 ; native X integer word
                LD   B, (IX + 3)
                LD   E, (IX + 5)                 ; native Y integer word
                LD   D, (IX + 6)
                JP   RTypeSprite_DrawDescriptor
