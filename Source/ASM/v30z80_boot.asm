; Загрузчик SPG переведённой программы World ROM: TS-Config 14 МГц, VDAC2 (FT812) с пустым
; списком отображения, обнуление страниц, которых нет в SPG (ОЗУ при запуске не очищено),
; резидент в окне #0000 и переход в его цикл кадров. Константы и список нулевых страниц —
; из v30z80_build.py (Build/V30Z80/boot.inc).
                DEVICE ZXSPECTRUM4096
                define MAPPING_REGISTERS
TSLibPage       EQU #00
InterruptVA     EQU #4000
ResolutionWidthPtr EQU #41F3
ResolutionHeightPtr EQU #41F5
; Развёртка FT812 — стандартный режим TSLib VM_1024_768_59Hz без изменений (HCYCLE 1344, VCYCLE 806, 64 МГц:
; 59.08 Гц, строки 47.6 кГц), как у Zuma Deluxe и HMM2. Прежняя запись REG_VCYCLE = 866 давала 55 Гц, как у
; M72, но 1024×768 с такой кадровой частотой вне VESA, и часть мониторов изображение не показывала. Решение
; пользователя 2026-09-16: только стандартный режим; игра, мелодии и эффекты идут по кадрам развёртки и быстрее
; аркады на 59.08 / 55.02 = 7.4 % (отступление на аппаратном пределе мониторов).
                include "../../Docs/TSLib/Include/TSConf.inc"
                include "../../Docs/TSLib/Include/Memory/Include.inc"
                include "../../Docs/TSLib/Include/Cache/Macro.inc"
                include "../../Docs/TSLib/Include/Video/Macro.inc"
                include "../../Docs/TSLib/Include/INT/Macro.inc"
                include "../../Docs/TSLib/Include/System/Macro.inc"
                include "../../Docs/TSLib/Include/FT/DL  Macro.inc"
                include "../../Docs/TSLib/Include/FT/812 Macro.inc"
                include "../../Build/V30Z80/boot.inc"
                ORG #5000
                JP Start
                include "../../Docs/TSLib/Include/FT/81x Const.inc"
                module FT
                include "../../Docs/TSLib/Include/FT/812 Func.asm"
                endmodule
Start:
                DI
                FMapAddrInit
                System_Setting SYS_ZCLK14 | SYS_CACHEEN
                ; Код в W3 должен пользоваться кэшем, как резидент; DMA не пишет страницы кода.
                Cache_Setting EN_0000 | EN_4000 | EN_8000 | EN_C000
                SetPage0 #00
                SetPage1 #05
                LD SP,#3FFF
                CALL Platform_Init
                ; Окончательная раскладка: FM-оверлей выключен (резидент займёт #0000…#3FFF),
                ; страницы — портами.
                DI
                XOR A
                LD BC,FMADDR
                OUT (C),A
                ; Страницы, которые программа считает нулевыми (в SPG их нет), — через окно #C000.
                LD HL,ZeroPages
.zeroPage:      LD A,(HL)
                OR A
                JR Z,.zeroDone
                INC HL
                PUSH HL
                LD BC,PAGE3
                OUT (C),A
                LD HL,#C000
                LD DE,#C001
                LD BC,#3FFF
                LD (HL),0
                LDIR
                POP HL
                JR .zeroPage
.zeroDone:
                LD A,V30Z80_RES_PAGE
                LD BC,PAGE0
                OUT (C),A
                ; Хуки платформы включаются только в SPG (в модели сверки HOST_PRESENT = 0).
                LD A,1
                LD (V30Z80_HOST_PRESENT),A
                JP V30Z80_START

Platform_Init:
                Video_Setting VID_NOGFX
                ; FT_DELAY внутри FT_BOOT_UP/FT_CMD_RESET ждёт кадровые IRQ.
                LD HL,Boot_FrameIRQ
                LD (InterruptVA + INT_VEC_FRAME),HL
                LD A,HIGH InterruptVA
                LD I,A
                IM 2
                INT_Setting INT_MSK_FRAME
                EI
                FT_BOOT_UP
                FT_CMD_RESET
                FT_RESOLUTION VM_1024_768_59Hz,ResolutionWidthPtr
                LD HL,EmptyDL
                LD BC,12
                LD DE,0
                CALL FT.WriteDL
                FT_WR_REG8 FT_REG_DLSWAP,FT_DLSWAP_FRAME
                Video_Setting VID_FT812 | VID_NOGFX
                ; Цикл кадров без прерываний Z80.
                DI
                INT_Setting 0
                RET
Boot_FrameIRQ:  EI
                RETI
ZeroPages:      V30Z80_ZERO_PAGE_LIST
EmptyDL:        FT_CLEAR_COLOR_RGB 0,0,0
                FT_CLEAR 1,1,1
                FT_DISPLAY
CodeEnd:
                ASSERT CodeEnd < #5800
                SAVEBIN "../../Build/V30Z80/boot.bin",#5000,CodeEnd-#5000
