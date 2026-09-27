; ============================================================================
; Платформенный слой: инициализация TS-Config и видеорежима FT812.
; Перенесено из HMM2 (Init_Video.asm / platform_tsconf.asm) без изменений по сути:
; Базовый профиль — 1024×768, логический кадр 640×480 масштабируется ×1.6.
; Физическую кадровую частоту задаёт только generated timing contract.
; ============================================================================

Platform_Init:
                Video_Setting VID_NOGFX          ; гасим TS-Config gfx до FT_BOOT_UP
                XOR  A
                LD   BC, BORDER
                OUT  (C), A
                CALL Init_Int
                CALL Init_Video
                DI
                INT_Setting 0
                ; Логическое разрешение — для модулей ввода (мышь/джойстик),
                ; физический режим FT812 остаётся 1024×768.
                LD   HL, LOG_SCREEN_W
                LD   (ResolutionWidthPtr), HL
                LD   HL, LOG_SCREEN_H
                LD   (ResolutionHeightPtr), HL
                RET

; ---------------------------------------------------------------------------
; Init_Int — дождаться первого кадрового прерывания TS-Config до FT_BOOT_UP:
; железу нужно время стабилизировать тайминги.
; ---------------------------------------------------------------------------
Init_Int:
                LD   HL, INT_Handler
                LD   (InterruptVA + INT_VEC_FRAME), HL
                LD   A, HIGH InterruptVA
                LD   I, A
                IM   2
                INT_Setting INT_MSK_FRAME
                EI
                HALT
                RET

INT_Handler:    EI
                RET

; ---------------------------------------------------------------------------
; Init_Video — включение VDAC2/FT812.
; Out: A=0, Z=1 — успех; A=1, Z=0 — VDAC2 на плате не найден.
; ---------------------------------------------------------------------------
Init_Video:
                ; TS-Conf STATUS[2:0] = 111 ⇒ на плате FT812-VDAC2.
                IN   A, (STATUS)
                AND  %00000111
                CP   %00000111
                JP   NZ, .no_vdac2               ; JP, не JR: FT_BOOT_UP разворачивается большим

                FT_BOOT_UP                       ; PWRDOWN→CLKEXT→ACTIVE, ждать REG_ID, GPIOX, PCLK
                FT_CMD_RESET                     ; сбросить очередь копроцессора

                ; Базовая таблица фиксирует 64MHz/PCLK=1, 1024×768 и HCYCLE=1344.
                ; Generated hook меняет только доказанную длину vertical blank.
                FT_RESOLUTION VM_1024_768_59Hz, ResolutionWidthPtr
                CALL RTypeFrameTiming_ApplyGenerated

                ; Пустой DL до первого кадра — иначе на экране мусор из RAM_DL.
                LD   HL, .EmptyDL
                LD   BC, .EmptyDL_Size
                LD   DE, 0
                CALL FT.WriteDL
                FT_WR_REG8 FT_REG_DLSWAP, FT_DLSWAP_FRAME

                FT_WR_REG8 FT_REG_INT_MASK, FT_INT_SWAP
                FT_WR_REG8 FT_REG_INT_EN,   1

                ; VID_FT812 — выход через VDAC2, VID_NOGFX освобождает DMA-циклы строки.
                Video_Setting VID_FT812 | VID_NOGFX

                XOR  A
                RET

.no_vdac2:      LD   A, 1
                OR   A
                RET

; Generic hook: никаких FPS/porch-констант здесь нет. Значение VCYCLE приходит
; только из generated_python_frame_timing.inc и проверяется его ASSERT-ами.
RTypeFrameTiming_ApplyGenerated:
                FT_WR_REG16 FT_REG_VCYCLE, RTYPE_PY_FT_VCYCLE
                RET

.EmptyDL:       FT_CLEAR_COLOR_RGB 0, 0, 0
                FT_CLEAR 1, 1, 1
                FT_DISPLAY
.EmptyDL_End:
.EmptyDL_Size   EQU .EmptyDL_End - .EmptyDL
