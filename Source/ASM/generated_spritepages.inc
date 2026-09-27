; ═══ СГЕНЕРИРОВАНО split_sprites.py — не редактировать вручную ═══
; Блок спрайтов M72: страница и длина; загрузка начинается с RAM_G 0.

M72_SPR_PAGE_COUNT  EQU 6
M72SpritePageTable:
                DEFB $10
                DEFW 16384
                DEFB $11
                DEFW 16384
                DEFB $12
                DEFW 16384
                DEFB $13
                DEFW 16384
                DEFB $14
                DEFW 16384
                DEFB $15
                DEFW 2652

; Полученное из MAME беззнаковое 8-битное моно PCM 11025 Гц для General Sound.
GS_WAVE_RAW_SIZE    EQU 4608
GS_WAVE_PAGE_COUNT  EQU 1
GSWavePageTable:
                DEFB $16
                DEFW 4608

; Обычный выстрел R-9 (звуковая команда игры $30), снят изолированно.
GS_SHOT_RAW_SIZE    EQU 5632
GS_SHOT_PAGE_COUNT  EQU 1
GSShotPageTable:
                DEFB $17
                DEFW 5632

; Музыка Stage 1 для TurboSound FM (2×YM2203): поток «пауза/счётчик/чип,регистр,значение».
TSFM_MUSIC_SIZE       EQU 59628
TSFM_MUSIC_PAGE_COUNT EQU 4
TsfmMusicPageTable:
                DEFB $18
                DEFW 16384
                DEFB $19
                DEFW 16384
                DEFB $1A
                DEFW 16384
                DEFB $1B
                DEFW 10476

; Атлас глифов M72: тайлы 8x8 из ROM, увеличенные офлайн.
M72_ATLAS_RAMG       EQU $020000
M72_ATLAS_SIZE       EQU 45360
M72_ATLAS_PAGE_COUNT EQU 3
M72AtlasPageTable:
                DEFB $1C
                DEFW 16384
                DEFB $1D
                DEFW 16384
                DEFB $1E
                DEFW 12592

; Тайловая память титула: карта 64x64, на тайл два слова.
M72_TVRAM_SIZE       EQU 16384
M72_TVRAM_PAGE_COUNT EQU 1
M72TitleVramPageTable:
                DEFB $1F
                DEFW 16384

; Спрайтовые ячейки M72: логотип титульного экрана.
M72_SPRATLAS_RAMG       EQU $02B130
M72_SPRATLAS_SIZE       EQU 300720
M72_SPRATLAS_PAGE_COUNT EQU 19
M72SprAtlasPageTable:
                DEFB $20
                DEFW 16384
                DEFB $21
                DEFW 16384
                DEFB $22
                DEFW 16384
                DEFB $23
                DEFW 16384
                DEFB $24
                DEFW 16384
                DEFB $25
                DEFW 16384
                DEFB $26
                DEFW 16384
                DEFB $27
                DEFW 16384
                DEFB $28
                DEFW 16384
                DEFB $29
                DEFW 16384
                DEFB $2A
                DEFW 16384
                DEFB $2B
                DEFW 16384
                DEFB $2C
                DEFW 16384
                DEFB $2D
                DEFW 16384
                DEFB $2E
                DEFW 16384
                DEFB $2F
                DEFW 16384
                DEFB $30
                DEFW 16384
                DEFB $31
                DEFW 16384
                DEFB $32
                DEFW 5808

; Sprite RAM титульного экрана — структура оригинала.
M72_SPRRAM_SIZE       EQU 1024
M72_SPRRAM_PAGE_COUNT EQU 1
M72SpriteRamPageTable:
                DEFB $33
                DEFW 1024

; Покадровые состояния самостоятельного Python-title.
M72_TITLE_EVENTS_SIZE       EQU 133668
M72_TITLE_EVENTS_PAGE_COUNT EQU 9
M72TitleEventPageTable:
                DEFB $34
                DEFW 16074
                DEFB $35
                DEFW 16074
                DEFB $36
                DEFW 16074
                DEFB $37
                DEFW 16074
                DEFB $38
                DEFW 16074
                DEFB $39
                DEFW 16074
                DEFB $3A
                DEFW 16074
                DEFB $3B
                DEFW 16074
                DEFB $3C
                DEFW 5076
M72_TITLE_PACKET_SIZE EQU 423
M72_TITLE_PACKETS_PER_PAGE EQU 38
M72_TITLE_FRAME_COUNT EQU 316
M72_TITLE_GLYPH_STATE_SIZE EQU 35

; Stage 1: задний tile-проход после полного HQ-апскейла слоя.
M72_STAGE_BG_ATLAS_RAMG       EQU $0747E0
M72_STAGE_BG_ATLAS_SIZE       EQU 3360
M72_STAGE_BG_ATLAS_PAGE_COUNT EQU 1
M72StageBgAtlasPageTable:
                DEFB $3D
                DEFW 3360

; Stage 1: передний tile-проход после полного HQ-апскейла слоя.
M72_STAGE_FG_ATLAS_RAMG       EQU $075500
M72_STAGE_FG_ATLAS_SIZE       EQU 53760
M72_STAGE_FG_ATLAS_PAGE_COUNT EQU 4
M72StageFgAtlasPageTable:
                DEFB $3E
                DEFW 16384
                DEFB $3F
                DEFW 16384
                DEFB $40
                DEFW 16384
                DEFB $41
                DEFW 4608

; Stage 1: 64x32 word-map слотов заднего прохода.
M72_STAGE_BG_MAP_SIZE       EQU 4096
M72_STAGE_BG_MAP_PAGE_COUNT EQU 1
M72StageBgMapPageTable:
                DEFB $42
                DEFW 4096

; Stage 1: 64x32 word-map слотов переднего прохода.
M72_STAGE_FG_MAP_SIZE       EQU 4096
M72_STAGE_FG_MAP_PAGE_COUNT EQU 1
M72StageFgMapPageTable:
                DEFB $43
                DEFW 4096

; Stage 1: точные пакеты MAME VRAM-delta для runtime replay.
M72_STAGE_EVENTS_SIZE       EQU 860
M72_STAGE_EVENTS_PAGE_COUNT EQU 1
M72StageEventPageTable:
                DEFB $44
                DEFW 860

; Игровой интерфейс v002: нижняя RGB565 HUD-панель 640x30.
ARCADE_BG_RAMG       EQU $036000
ARCADE_BG_SIZE       EQU 38400
ARCADE_BG_PAGE_COUNT EQU 3
ArcadeBgPageTable:
                DEFB $45
                DEFW 16384
                DEFB $46
                DEFW 16384
                DEFB $47
                DEFW 5632

; Bootstrap Z80 pack: общие таблицы и Stage 1; Stage 2…8 идут с SD.
RTYPE_TARGET_PACK_SIZE       EQU 557056
RTYPE_TARGET_PACK_PAGE_COUNT EQU 34
RTypeTargetPackPageTable:
                DEFB $49
                DEFW 16384
                DEFB $4A
                DEFW 16384
                DEFB $4B
                DEFW 16384
                DEFB $4C
                DEFW 16384
                DEFB $4D
                DEFW 16384
                DEFB $4E
                DEFW 16384
                DEFB $4F
                DEFW 16384
                DEFB $50
                DEFW 16384
                DEFB $51
                DEFW 16384
                DEFB $52
                DEFW 16384
                DEFB $53
                DEFW 16384
                DEFB $54
                DEFW 16384
                DEFB $55
                DEFW 16384
                DEFB $56
                DEFW 16384
                DEFB $57
                DEFW 16384
                DEFB $58
                DEFW 16384
                DEFB $59
                DEFW 16384
                DEFB $5A
                DEFW 16384
                DEFB $5B
                DEFW 16384
                DEFB $5C
                DEFW 16384
                DEFB $5D
                DEFW 16384
                DEFB $5E
                DEFW 16384
                DEFB $5F
                DEFW 16384
                DEFB $60
                DEFW 16384
                DEFB $61
                DEFW 16384
                DEFB $62
                DEFW 16384
                DEFB $63
                DEFW 16384
                DEFB $64
                DEFW 16384
                DEFB $65
                DEFW 16384
                DEFB $66
                DEFW 16384
                DEFB $67
                DEFW 16384
                DEFB $68
                DEFW 16384
                DEFB $69
                DEFW 16384
                DEFB $6A
                DEFW 16384

; Точные Python HQ sprite cells лежат подряд: таблица страниц не нужна.
RTYPE_PY_HQ_SPRITE_RAMG_BASE EQU $0C0000
; Совместимое имя старого uploader-а; это адрес распакованных pixels.
RTYPE_PY_HQ_SPRITE_ZLIB_RAMG EQU RTYPE_PY_HQ_SPRITE_RAMG_BASE
RTYPE_PY_HQ_SPRITE_ZLIB_SIZE EQU 41700
RTYPE_PY_HQ_SPRITE_ZLIB_PAGE_COUNT EQU 3
RTYPE_PY_HQ_SPRITE_ZLIB_FIRST_PAGE EQU #6B
RTYPE_PY_HQ_SPRITE_RAW_SIZE EQU 236520
RTYPE_PY_HQ_INFLATE_RAW_SIZE EQU 239664
RTYPE_PY_HQ_APPEND_RAMG EQU $0F9BE8
RTYPE_PY_HQ_APPEND_SIZE EQU 3144
RTYPE_PY_HQ_APPEND_BLOB_COUNT EQU 73
RTYPE_PY_HQ_LOOKUP_PAGE EQU #EC
RTYPE_PY_HQ_LOOKUP_PTR EQU #E000
RTYPE_PY_HQ_LOOKUP_SIZE EQU 1664
RTYPE_PY_HQ_LOOKUP_COUNT EQU 206
RTYPE_PY_HQ_LOOKUP_REC_SIZE EQU 8
RTYPE_PY_HQ_TEMPLATE_PTR EQU #E700
RTYPE_PY_HQ_TEMPLATE_SIZE EQU 2304
RTYPE_PY_HQ_TEMPLATE_COUNT EQU 40
RTYPE_PY_HQ_TEMPLATE_REC_SIZE EQU 16
RTYPE_PY_HQ_TEMPLATE_CELL_COUNT EQU 206
RTYPE_PY_HQ_TEMPLATE_CELL_SIZE EQU 8

; Анимация накопления Beam из активной Python-версии.
RTYPE_PY_CHARGE_RAMG       EQU $02C000
RTYPE_PY_CHARGE_SIZE       EQU 35216
RTYPE_PY_CHARGE_PAGE_COUNT EQU 3
RTypePyChargePageTable:
                DEFB $E8
                DEFW 16384
                DEFB $E9
                DEFW 16384
                DEFB $EA
                DEFW 2448
ARCADE_BG_WIDTH  EQU 640
ARCADE_BG_HEIGHT EQU 30
ARCADE_BG_STRIDE EQU 1280
RTYPE_TARGET_PACK_BASE_PAGE EQU $49

; Полный распакованный M72 sprite ROM: 128 chunks по 8 КБ.
RTYPE_SPRITE_RAW_PAGE_COUNT EQU 64
RTypeSpriteRawPageTable:
                DEFB $77
                DEFB $78
                DEFB $79
                DEFB $7A
                DEFB $7B
                DEFB $7C
                DEFB $7D
                DEFB $7E
                DEFB $7F
                DEFB $80
                DEFB $81
                DEFB $82
                DEFB $83
                DEFB $84
                DEFB $85
                DEFB $86
                DEFB $87
                DEFB $88
                DEFB $89
                DEFB $8A
                DEFB $8B
                DEFB $8C
                DEFB $8D
                DEFB $8E
                DEFB $8F
                DEFB $90
                DEFB $91
                DEFB $92
                DEFB $93
                DEFB $94
                DEFB $95
                DEFB $96
                DEFB $97
                DEFB $98
                DEFB $99
                DEFB $9A
                DEFB $9B
                DEFB $9C
                DEFB $9D
                DEFB $9E
                DEFB $9F
                DEFB $A0
                DEFB $A1
                DEFB $A2
                DEFB $A3
                DEFB $A4
                DEFB $A5
                DEFB $A6
                DEFB $A7
                DEFB $A8
                DEFB $A9
                DEFB $AA
                DEFB $AB
                DEFB $AC
                DEFB $AD
                DEFB $AE
                DEFB $AF
                DEFB $DE
                DEFB $DF
                DEFB $E0
                DEFB $E1
                DEFB $E2
                DEFB $E3
                DEFB $E4
