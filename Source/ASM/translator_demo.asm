; Отдельная аппаратная обвязка нового C-профиля. Старого игрового ASM здесь нет.
                DEVICE ZXSPECTRUM4096
                define MAPPING_REGISTERS
TSLibPage       EQU #00
InterruptVA     EQU #4000
LOG_SCREEN_W    EQU 640
LOG_SCREEN_H    EQU 480
InputState      EQU #4202
InputAnyPressed EQU #4259
ResolutionWidthPtr EQU #41F3
ResolutionHeightPtr EQU #41F5
RTYPE_PY_FT_VCYCLE EQU 866
                include "../../Docs/TSLib/Include/TSConf.inc"
                include "../../Docs/TSLib/Include/Memory/Include.inc"
                include "../../Docs/TSLib/Include/Cache/Macro.inc"
                include "../../Docs/TSLib/Include/Video/Macro.inc"
                include "../../Docs/TSLib/Include/INT/Macro.inc"
                include "../../Docs/TSLib/Include/System/Macro.inc"
                include "../../Docs/TSLib/Include/FT/DL  Macro.inc"
                include "../../Docs/TSLib/Include/FT/812 Macro.inc"
                include "../../Build/TranslatorDemo/symbols.inc"
                include "../../Build/TranslatorDemo/assets.inc"
                ORG #4E00
StageKernel_Thunk:
                ; Только аппаратный межбанковый вызов; вся логика класса в C.
                SetPage3 STAGE_KERNEL_PAGE
                CALL STAGE_KERNEL_ENTRY
                SetPage3 #06
                RET
                ASSERT $ < #4F00
                ORG #5000
                JP Start
                include "../../Docs/TSLib/Include/FT/81x Const.inc"
                include "../../Docs/TSLib/Include/Input/Include.inc"
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
                SetPage2 #30
                SetPage3 #06
                LD SP,#3FFF
                LD HL,#3C00
                LD (HL),#A5
                LD DE,#3C01
                LD BC,#03EF
                LDIR
                CALL Platform_Init
                CALL Input.Mouse.Initialize
                CALL Input_Init
                XOR A
                LD (UploadIndex),A
                LD DE,0
                XOR A
.upload:
                PUSH AF
                PUSH DE
                LD A,(UploadIndex)
                ADD A,#40
                SetPage2_A
                POP DE
                POP AF
                LD HL,#8000
                LD BC,#4000
                CALL FT.WriteMem
                PUSH AF
                LD A,(UploadIndex)
                INC A
                LD (UploadIndex),A
                CP DEMO_GFX_PAGES
                JR Z,.uploaded
                POP AF
                JR .upload
.uploaded:
                POP AF
                SetPage2 #30
                CALL ReadInput
                CALL Demo_Init
                LD HL,0
                LD (#210A),HL
MainLoop:
                CALL ReadInput
                SetPage2 #30
                CALL Demo_Tick
                SetPage2 #32
                CALL Demo_Render
                LD A,(#3C00)
                CP #A5
                JP NZ,Fault
                LD A,(demo_fault)
                OR A
                JP NZ,Fault
.wait:
                FT_RD_REG8 FT_REG_DLSWAP
                OR A
                JR NZ,.wait
                LD HL,#1000
                LD BC,(demo_dl_bytes)
                LD DE,0
                CALL FT.WriteDL
                FT_WR_REG8 FT_REG_DLSWAP,FT_DLSWAP_FRAME
                JP MainLoop
Fault:
                LD A,2
                LD BC,BORDER
                OUT (C),A
                JP Fault
ReadInput:
                CALL Input_Poll
                LD A,(InputState)
                LD (#2100),A
                CALL Input_MouseX
                LD (#2102),HL
                CALL Input_MouseY
                LD (#2104),HL
                RET
UploadIndex:    DB 0
Platform_Init:
                Video_Setting VID_NOGFX
                ; FT_DELAY внутри FT_BOOT_UP/FT_CMD_RESET ждёт кадровые IRQ.
                ; При DI первый HALT никогда не завершается.
                LD HL,Demo_FrameIRQ
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
                LD HL,LOG_SCREEN_W
                LD (ResolutionWidthPtr),HL
                LD HL,LOG_SCREEN_H
                LD (ResolutionHeightPtr),HL
                ; Игровой цикл синхронизируется по swap FT812, без лишних IRQ.
                DI
                INT_Setting 0
                RET
Demo_FrameIRQ:  EI
                RETI
EmptyDL:        FT_CLEAR_COLOR_RGB 0,0,0
                FT_CLEAR 1,1,1
                FT_DISPLAY
                include "input.asm"
CodeEnd:
                ASSERT CodeEnd < #8000
                SAVEBIN "Build/TranslatorDemo/boot.bin",#4E00,CodeEnd-#4E00
