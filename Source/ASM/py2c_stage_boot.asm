; Аппаратная обвязка SPG транслированного Stage: страницы, FT812, DMA и цикл кадра.
; Игровой логики здесь нет: она целиком в C, сгенерированном py2c из Python.
                DEVICE ZXSPECTRUM4096
                define MAPPING_REGISTERS
TSLibPage       EQU #00
InterruptVA     EQU #4000
ResolutionWidthPtr EQU #41F3
ResolutionHeightPtr EQU #41F5
; Частота кадров FT812 ≈55 Гц, как в Python-версии и в аркаде.
RTYPE_PY_FT_VCYCLE EQU 866
DL_PAGE         EQU #00
DL_ADDRESS      EQU #1000
                include "../../Docs/TSLib/Include/TSConf.inc"
                include "../../Docs/TSLib/Include/Memory/Include.inc"
                include "../../Docs/TSLib/Include/Cache/Macro.inc"
                include "../../Docs/TSLib/Include/Video/Macro.inc"
                include "../../Docs/TSLib/Include/INT/Macro.inc"
                include "../../Docs/TSLib/Include/System/Macro.inc"
                include "../../Docs/TSLib/Include/FT/DL  Macro.inc"
                include "../../Docs/TSLib/Include/FT/812 Macro.inc"
                include "../../Build/Py2cStageZ80/py2c_symbols.inc"
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
                SetPage2 PY2C_FIRST_DATA_PAGE
                SetPage3 #06
                LD SP,#3FFF
                ; Сторожевой байт нижней границы стека.
                LD HL,#3C00
                LD (HL),#A5
                LD DE,#3C01
                LD BC,#03EF
                LDIR
                CALL Platform_Init
                CALL UploadGraphics
                LD A,PY2C_FIRST_DATA_PAGE
                LD (py2c_page2),A
                XOR A
                LD (py2c_fault),A
                CALL Py2c_Init
MainLoop:
                CALL Py2c_Frame
                LD A,(#3C00)
                CP #A5
                JP NZ,Fault
                LD A,(py2c_fault)
                OR A
                JP NZ,Fault
.wait:
                FT_RD_REG8 FT_REG_DLSWAP
                OR A
                JR NZ,.wait
                CALL WriteDL_DMA
                FT_WR_REG8 FT_REG_DLSWAP,FT_DLSWAP_FRAME
                JP MainLoop

Fault:
                LD A,2
                LD BC,BORDER
                OUT (C),A
                DI
                HALT

; -----------------------------------------------------------------------------
; DMA RAM→SPI: A — число пакетов по 256 слов (0 — нет), C — остаток слов.
; Адрес источника DMA уже установлен; SPI-заголовок записи уже отправлен.
DMA_SendWords:
                OR A
                JR Z,.tail
                DEC A
                LD B,HIGH DMANUM
                PUSH BC
                LD C,LOW DMANUM
                OUT (C),A
                LD A,#FF
                LD BC,DMALEN
                OUT (C),A
                LD A,DMA_RAM_SPI
                LD BC,DMACTR
                OUT (C),A
.wait_full:
                LD BC,DMASTATUS
                IN A,(C)
                AND DMA_WNR
                JR NZ,.wait_full
                POP BC
.tail:
                LD A,C
                OR A
                RET Z
                DEC A
                LD BC,DMALEN
                OUT (C),A
                XOR A
                LD BC,DMANUM
                OUT (C),A
                LD A,DMA_RAM_SPI
                LD BC,DMACTR
                OUT (C),A
.wait_tail:
                LD BC,DMASTATUS
                IN A,(C)
                AND DMA_WNR
                JR NZ,.wait_tail
                RET

; Источник DMA: страница A, смещение HL внутри страницы.
DMA_SetSource:
                PUSH AF
                LD A,L
                LD BC,DMASADDRL
                OUT (C),A
                LD A,H
                AND #3F
                LD BC,DMASADDRH
                OUT (C),A
                POP AF
                LD BC,DMASADDRX
                OUT (C),A
                RET

; Display list из резидентного буфера страницы 0 в RAM_DL FT812.
WriteDL_DMA:
                FT_ON
                LD A,((FT_RAM_DL >> 16) & #FF) | #80
                OUT (SPI_DATA),A
                XOR A
                OUT (SPI_DATA),A
                OUT (SPI_DATA),A
                LD A,DL_PAGE
                LD HL,DL_ADDRESS
                CALL DMA_SetSource
                LD HL,(py2c_dl_bytes)
                SRL H
                RR L
                LD A,H
                LD C,L
                CALL DMA_SendWords
                FT_OFF
                RET

; Готовые ARGB4444-атласы: страницы подряд в RAM_G с адреса 0.
UploadGraphics:
                XOR A
                LD (UploadIndex),A
.page:
                LD A,(UploadIndex)
                CP PY2C_GFX_PAGES
                RET Z
                FT_ON
                ; Адрес RAM_G = индекс << 14: байт 2 — индекс >> 2, байт 1 — (индекс << 6) & #FF.
                LD A,(UploadIndex)
                SRL A
                SRL A
                OR #80
                OUT (SPI_DATA),A
                LD A,(UploadIndex)
                RRCA
                RRCA
                AND #C0
                OUT (SPI_DATA),A
                XOR A
                OUT (SPI_DATA),A
                LD A,(UploadIndex)
                ADD A,PY2C_GFX_FIRST_PAGE
                LD HL,0
                CALL DMA_SetSource
                LD A,32
                LD C,0
                CALL DMA_SendWords
                FT_OFF
                LD A,(UploadIndex)
                INC A
                LD (UploadIndex),A
                JR .page
UploadIndex:    DB 0

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
                ; Цикл синхронизируется по swap FT812, без лишних IRQ.
                DI
                INT_Setting 0
                RET
Boot_FrameIRQ:  EI
                RETI
EmptyDL:        FT_CLEAR_COLOR_RGB 0,0,0
                FT_CLEAR 1,1,1
                FT_DISPLAY
CodeEnd:
                ASSERT CodeEnd < #8000
                SAVEBIN "Build/Py2cStageZ80/boot.bin",#5000,CodeEnd-#5000
