; Сгенерировано rtype_python_translator.py из Game.update.
; Эта процедура намеренно размещается ниже $8000: collision bank page #E5
; не видит вторую страницу Core в переключаемом slot2.
RTypePyPlayerTerrainCollision:
                LD   BC, (RTypePlayerNativeX)
                LD   DE, (RTypePlayerNativeY)
                CALL RTypeTerrain_ForegroundCode
                LD   DE, #0DFC
                OR   A
                SBC  HL, DE
                JR   C, .hit
                LD   BC, (RTypePlayerNativeX)
                LD   DE, (RTypePlayerNativeY)
                CALL RTypeTerrain_BackgroundCode
                LD   DE, #07D0
                OR   A
                SBC  HL, DE
                RET  NC
.hit:          SCF
                RET

; Collision page #E5 cannot call lifecycle code stored in Core slot2.
; Restore page #06 before tail-entering the Python-translated death branch;
; its RET still reaches the resident wrapper that called the collision bank.
RTypePyCollisionBeginDeath:
                LD   A, CorePage + 1
                SetPage2_A
                ifdef RTYPE_DIAGNOSTIC_INVINCIBLE
                ; Временная покадровая проверка: collision полностью вычислена,
                ; но смерть не запускается. Релиз без define идёт обычным путём.
                RET
                endif
                JP   ArcadeLifecycle_BeginDeath
