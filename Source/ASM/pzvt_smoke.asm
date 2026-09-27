                DEVICE ZXSPECTRUM4096
                define MAPPING_REGISTERS
TSLibPage       EQU #00

                include "../../Docs/TSLib/Include/TSConf.inc"
                include "../../Docs/TSLib/Include/Memory/Include.inc"
                include "generated_pzvt_smoke_symbols.inc"

                ORG #5000
Start:
                DI
                FMapAddrInit
                SetPage0 #00
                SetPage1 #05
                SetPage2 #F0
                SetPage3 #F1
                LD SP, #3FFF
                CALL PZVTSmoke_Run
                LD A, (#2F01)       ; VM error: zero means the image executed.
                OR A
                JR NZ, .failed
                LD A, (#2F00)
                CP 2                ; PYZ80_VM_RETURNED
                JR NZ, .failed
                LD A, 4             ; green border = returned translated value
                JR .show
.failed:
                LD A, 2             ; red border = target VM rejected execution
.show:
                LD BC, BORDER
                OUT (C), A
.hold:
                JR .hold

CodeEnd:
                SAVEBIN "Build/pzvt_smoke_boot.bin", Start, CodeEnd - Start
