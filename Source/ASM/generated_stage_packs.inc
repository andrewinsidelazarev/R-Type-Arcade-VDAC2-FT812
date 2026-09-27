; Сгенерировано m72_stage_packs.py; вручную не редактировать.
RTYPE_STAGE_PACK_BASE_PAGE EQU #49
RTYPE_STAGE_PACK_COUNT     EQU 8
RTypeStagePackSectorTable:
                DEFW 1088
                DEFW 1280
                DEFW 928
                DEFW 1024
                DEFW 1472
                DEFW 1184
                DEFW 992
                DEFW 1024
RTypeStagePackPageTable:
                DEFB 34
                DEFB 40
                DEFB 29
                DEFB 32
                DEFB 46
                DEFB 37
                DEFB 31
                DEFB 32
RTypeStagePackNameTable:
                DEFB "RTYPE01.PAK", 0
                DEFB "RTYPE02.PAK", 0
                DEFB "RTYPE03.PAK", 0
                DEFB "RTYPE04.PAK", 0
                DEFB "RTYPE05.PAK", 0
                DEFB "RTYPE06.PAK", 0
                DEFB "RTYPE07.PAK", 0
                DEFB "RTYPE08.PAK", 0
