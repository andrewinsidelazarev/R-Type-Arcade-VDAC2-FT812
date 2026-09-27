; Проба бюджета строки FT812 (Source/Tools/ft812_probe.py): загрузчик как rtype_boot.asm — TS-Config
; 14 МГц, VDAC2 в режиме игры (1024×768, VCYCLE 866). Данные пробы (страница PROBE_DATA_PAGE) пишутся в
; RAM_G; display list (страницы PROBE_DL_PAGE0…) сменяются по кругу каждые ≈5 с, клавиши 1…6 выбирают список
; сразу; сначала показан список 1.
                DEVICE ZXSPECTRUM4096
                define MAPPING_REGISTERS
TSLibPage       EQU #00
InterruptVA     EQU #4000
ResolutionWidthPtr EQU #41F3
ResolutionHeightPtr EQU #41F5
PROBE_VCYCLE    EQU 866                         ; как RTYPE_FT_VCYCLE игры
                include "../../Docs/TSLib/Include/TSConf.inc"
                include "../../Docs/TSLib/Include/Memory/Include.inc"
                include "../../Docs/TSLib/Include/Cache/Macro.inc"
                include "../../Docs/TSLib/Include/Video/Macro.inc"
                include "../../Docs/TSLib/Include/INT/Macro.inc"
                include "../../Docs/TSLib/Include/System/Macro.inc"
                include "../../Docs/TSLib/Include/FT/DL  Macro.inc"
                include "../../Docs/TSLib/Include/FT/812 Macro.inc"
                ORG #5000
                JP Start
                include "../../Docs/TSLib/Include/FT/81x Const.inc"
                module FT
                include "../../Docs/TSLib/Include/FT/812 Func.asm"
                endmodule
                include "../../Build/V30Z80/ft812_probe.inc"
Start:
                DI
                FMapAddrInit
                System_Setting SYS_ZCLK14 | SYS_CACHEEN
                Cache_Setting EN_0000 | EN_4000 | EN_8000
                SetPage0 #00
                SetPage1 #05
                LD SP,#3FFF
                CALL Platform_Init
                DI
                XOR A
                LD BC,FMADDR
                OUT (C),A
                ; данные пробы → RAM_G с адреса 0
                LD A,PROBE_DATA_PAGE
                LD BC,PAGE3
                OUT (C),A
                LD HL,#C000
                LD BC,PROBE_DATA_BYTES
                XOR A
                LD DE,0
                CALL FT.WriteMem
                XOR A
                CALL ShowList
                ; Смена списка каждые PROBE_CYCLE кадров развёртки FT812 (REG_FRAMES) — без клавиш; клавиши
                ; 1…6 выбирают список сразу, отсчёт начинается заново.
Loop:           FT_RD_REG8 FT_REG_FRAMES
                LD HL,LastFrame
                CP (HL)
                JR Z,Keys
                LD (HL),A
                LD HL,(Ticks)
                INC HL
                LD (Ticks),HL
                LD DE,PROBE_CYCLE
                OR A
                SBC HL,DE
                JR C,Keys
                LD A,(Shown)
                INC A
                CP PROBE_LISTS
                JR C,.next
                XOR A
.next:          CALL ShowList
                JR Loop
Keys:           LD BC,#F7FE                     ; клавиши 1…5 (активный ноль)
                IN A,(C)
                LD E,0
                LD D,5
.bit:           RRCA
                JR NC,.key
                INC E
                DEC D
                JR NZ,.bit
                LD BC,#EFFE                     ; клавиша 6 — бит 4 полуряда 0…6
                IN A,(C)
                BIT 4,A
                JR NZ,Loop
.key:           LD A,E
                LD HL,Shown
                CP (HL)
                JR Z,Loop
                CALL ShowList
                JR Loop

; A — номер списка (0…PROBE_LISTS − 1): страница в окне W3, запись в RAM_DL, DLSWAP; отсчёт смены — заново.
ShowList:       LD HL,0
                LD (Ticks),HL
                LD (Shown),A
                LD L,A
                LD H,0
                ADD HL,HL
                LD DE,PROBE_DL_BYTES
                ADD HL,DE
                LD C,(HL)
                INC HL
                LD B,(HL)
                PUSH BC
                ADD A,PROBE_DL_PAGE0
                LD BC,PAGE3
                OUT (C),A
                POP BC
                LD HL,#C000
                LD DE,0
                CALL FT.WriteDL
                FT_WR_REG8 FT_REG_DLSWAP,FT_DLSWAP_FRAME
                RET

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
                FT_WR_REG16 FT_REG_VCYCLE,PROBE_VCYCLE
                LD HL,EmptyDL
                LD BC,12
                LD DE,0
                CALL FT.WriteDL
                FT_WR_REG8 FT_REG_DLSWAP,FT_DLSWAP_FRAME
                FT_DELAY 25                     ; FT812 готов к записи RAM_G
                Video_Setting VID_FT812 | VID_NOGFX
                DI
                INT_Setting 0
                RET
Boot_FrameIRQ:  EI
                RETI
Shown:          DB #FF
LastFrame:      DB 0
Ticks:          DW 0
PROBE_CYCLE     EQU 275                         ; ≈5 с при 55 Гц
EmptyDL:        FT_CLEAR_COLOR_RGB 0,0,0
                FT_CLEAR 1,1,1
                FT_DISPLAY
CodeEnd:
                ASSERT CodeEnd < #5800
                SAVEBIN "../../Build/V30Z80/ft812_probe.bin",#5000,CodeEnd-#5000
