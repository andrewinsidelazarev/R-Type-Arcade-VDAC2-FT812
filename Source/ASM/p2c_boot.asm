; Загрузчик SPG транслированной программы app.main: TS-Config, FT812 и переход в резидент.
; Игровой логики здесь нет: она целиком в C, сгенерированном p2c из Python.
                DEVICE ZXSPECTRUM4096
                define MAPPING_REGISTERS
TSLibPage       EQU #00
InterruptVA     EQU #4000
ResolutionWidthPtr EQU #41F3
ResolutionHeightPtr EQU #41F5
; Частота кадров FT812 ≈55 Гц, как в Python-версии и в аркаде.
RTYPE_PY_FT_VCYCLE EQU 866
                include "../../Docs/TSLib/Include/TSConf.inc"
                include "../../Docs/TSLib/Include/Memory/Include.inc"
                include "../../Docs/TSLib/Include/Cache/Macro.inc"
                include "../../Docs/TSLib/Include/Video/Macro.inc"
                include "../../Docs/TSLib/Include/INT/Macro.inc"
                include "../../Docs/TSLib/Include/System/Macro.inc"
                include "../../Docs/TSLib/Include/FT/DL  Macro.inc"
                include "../../Docs/TSLib/Include/FT/812 Macro.inc"
                include "../../Build/P2cZ80/p2c_z80_boot.inc"
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
                Cache_Setting EN_0000 | EN_4000 | EN_8000
                SetPage0 #00
                SetPage1 #05
                LD SP,#3FFF
                CALL Platform_Init
                ; Окончательная раскладка: FM-оверлей выключен, страницы — портами.
                ; Окно #4000 (здесь исполняется загрузчик) переключает резидент после перехода.
                DI
                XOR A
                LD BC,FMADDR
                OUT (C),A
                ; ОЗУ при запуске не очищено: страницы, которые программа считает нулевыми
                ; (в SPG их нет), обнуляются через окно #C000.
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
                LD A,P2C_PAGE_DATA2
                LD BC,PAGE2
                OUT (C),A
                LD A,P2C_FIRST_BANK
                LD BC,PAGE3
                OUT (C),A
                LD A,P2C_PAGE_RESIDENT
                LD BC,PAGE0
                OUT (C),A
                LD A,P2C_FIRST_BANK
                JP P2C_START

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
                FT_WR_REG16 FT_REG_VCYCLE,RTYPE_PY_FT_VCYCLE
                LD HL,EmptyDL
                LD BC,12
                LD DE,0
                CALL FT.WriteDL
                FT_WR_REG8 FT_REG_DLSWAP,FT_DLSWAP_FRAME
                Video_Setting VID_FT812 | VID_NOGFX
                ; Цикл синхронизируется по swap FT812, без IRQ.
                DI
                INT_Setting 0
                RET
Boot_FrameIRQ:  EI
                RETI
ZeroPages:      P2C_ZERO_PAGE_LIST
EmptyDL:        FT_CLEAR_COLOR_RGB 0,0,0
                FT_CLEAR 1,1,1
                FT_DISPLAY
CodeEnd:
                ASSERT CodeEnd < #5800
                SAVEBIN "../../Build/P2cZ80/boot.bin",#5000,CodeEnd-#5000
