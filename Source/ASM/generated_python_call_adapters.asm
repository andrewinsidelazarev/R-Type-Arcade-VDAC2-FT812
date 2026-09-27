; Сгенерировано pyz80_compiler из call_adapters manifest.
; Только ABI/MMU glue; игровая семантика находится в compiler bank.

; rtype_port.game.advance_pitch -> ArcadePlayer_UpdatePitch
ArcadePlayer_UpdatePitch:
                GetPage2
                PUSH AF
                PUSH IY
                LD   A, (ArcadePlayerPitch)
                LD   D, A
                LD   A, (InputState)
                LD   E, A
                LD   A, RTYPE_PY_CODE_BANK0_PAGE
                SetPage2_A
                CALL RTypePyABI_Bridge_000
                LD   D, A
                POP  IY
                POP  AF
                SetPage2_A
                LD   A, D
                LD   (ArcadePlayerPitch), A
                RET
