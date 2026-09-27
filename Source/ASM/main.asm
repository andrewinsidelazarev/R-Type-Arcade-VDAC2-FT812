; ============================================================================
; Arcade R-Type для TS-Config / VDAC2 (FT812).
; Игровое состояние — logical 640×480; renderer переводит его в physical
; 1024×768. Готовые bitmap assets масштабируются FT812 только через NEAREST.
; ============================================================================

                DEVICE ZXSPECTRUM4096
                define MAPPING_REGISTERS

EntryPoint      EQU #5000
StackTop        EQU #4EFF
InterruptVA     EQU #4000
CorePage        EQU #05
TSLibPage       EQU #00
SpritePageBase  EQU #10
RTYPE_CANARY    EQU 0            ; 1 = остановиться после Init_Video (диагностика старта)
LOG_SCREEN_W    EQU 640
LOG_SCREEN_H    EQU 480

; --- Резидентные переменные (#4200…); карта продолжена в arcade_game.asm. ---
FrameCounter    EQU #4200        ; 2Б
InputState      EQU #4202        ; movement/fire/release bits из input.asm
; Диспетчер повторяет два состояния текущего rtype_port/app.py.
APP_SCENE_TITLE EQU 0
APP_SCENE_GAME  EQU 1
GameMode        EQU #4271        ; одно из APP_SCENE_*, за блоком видеотракта
InputAnyPressed EQU #4259        ; make-код, ЛКМ или кнопка Kempston-джойстика
ResolutionWidthPtr  EQU #41F3    ; сюда FT_RESOLUTION пишет ширину/высоту
ResolutionHeightPtr EQU #41F5

; Загрузчик всегда исполняется из slot1 и использует отдельный стек. Область
; #4101…#41F0 свободна: #40FF/#4100 занимает последнее слово IM2-таблицы, а
; #41F3…#41F6 — размеры экрана. Поэтому remap slot2 внутри FAT32-кода не может
; уничтожить ни адрес возврата, ни состояние загрузки.
RTypeLoaderStackTop        EQU #41F0
RTypeLoaderSavedSP         EQU #41F7       ; word
RTypeStageStorageAvailable EQU #41F9
RTypeStageLoadNumber       EQU #41FA
RTypeStageLoadPages        EQU #41FB
RTypeStageLoadRemain       EQU #41FC
RTypeStageLoadSourcePage   EQU #41FD
RTypeStageLoadDestPage     EQU #41FE
RTYPE_LOADER_PAGE          EQU #0E         ; sd_zc + raw_pak, slot3 overlay
RAWPAK_BUF_PAGE            EQU #0F         ; один 16-КБ SD/FAT32 буфер, slot2
RTYPE_STAGE_STAGING_PAGE   EQU #B0         ; максимум #B0…#DD (46 pages)

; Буфер сборки списка команд копроцессора (slot2, 3584 bytes). Он начинается
; после resident Core и целиком меньше полезного FIFO FT812 (#0FFC bytes).
; Display list может быть больше окна: общий слой отправляет заполненные chunks
; в FIFO FT812 и продолжает сборку с начала этого окна.
                define CMD_ADDRESS_PTR #B200
                define CMD_ADDRESS_END #C000
RTypeFTCommandBufferStart EQU CMD_ADDRESS_PTR
RTypeFTCommandBufferEnd   EQU CMD_ADDRESS_END

                include "../../Docs/TSLib/Include/TSConf.inc"
                include "../../Docs/TSLib/Include/Memory/Include.inc"
                include "../../Docs/TSLib/Include/Cache/Macro.inc"
                include "../../Docs/TSLib/Include/Video/Macro.inc"
                include "../../Docs/TSLib/Include/INT/Macro.inc"
                include "../../Docs/TSLib/Include/System/Macro.inc"
                include "../../Docs/TSLib/Include/FT/DL  Macro.inc"
                include "../../Docs/TSLib/Include/FT/812 Macro.inc"

                ORG EntryPoint
                JP   Start

                include "../../Docs/TSLib/Include/FT/81x Const.inc"
                include "../../Docs/TSLib/Include/Input/Include.inc"

                ; Функции FT (SPI-обмен, запись RAM_G/RAM_DL) и буфер копроцессора
                ; живут в module FT — макросы FT_CMD_*/FT_Begin из BufferMacro.inc
                ; должны быть определены ДО render.asm, поэтому включаются здесь.
                module FT
                include "../../Docs/TSLib/Include/FT/812 Func.asm"
                include "../../Docs/TSLib/Include/FT/Coprocessor/Include.inc"
                endmodule

                ; Адреса и ABI настоящего Python AST -> C -> Z80 bank.
                include "generated_python_compiled_symbols.inc"

Start:
                DI
                ; Страницы выставляются до первого CALL: иначе адрес возврата ляжет
                ; в старую страницу slot2 и RET уйдёт в мусор (грабли из HMM2).
                FMapAddrInit
                System_Setting SYS_ZCLK14 | SYS_CACHEEN
                Cache_Setting  EN_0000 | EN_4000 | EN_8000
                SetPage1 CorePage
                SetPage2 CorePage + 1
                LD   SP, StackTop
                CALL RTypePyStack_Init

                CALL Platform_Init
                ifdef RTYPE_TSFMDIAG
                ; Диагностика TurboSound FM: тоновый тест + цветная индикация.
                ; В релиз НЕ входит. Включается ключом -DRTYPE_TSFMDIAG.
                CALL TsfmDiag_Run
                endif
                if RTYPE_CANARY
                ; Диагностика: остановиться сразу после видеоинициализации.
                ; Если дамп эмулятора стал 1024×768 — Init_Video отработал,
                ; и виновата дальнейшая часть старта.
.canaryHold:    JR   .canaryHold
                endif
                CALL Input.Mouse.Initialize
                CALL Input_Init
                ; Если SD/FAT32 недоступна, встроенный монолитный pack остаётся
                ; нетронутым и загрузка продолжается по старому пути.
                CALL RTypeStageStorage_Init
                CALL M72Sprites_Upload
                CALL M72Video_Init       ; титул: атлас глифов/спрайтов, тайл.память
                XOR  A
                LD   (GameMode), A       ; старт с титульного экрана
                CALL ArcadeGame_Init
                CALL Title_Init
                ; Как Python-приложение, показать frame 0 до длительной
                ; инициализации звуковой платы. Пользователь сразу видит
                ; живой title, а не последний мусорный display list загрузчика.
                CALL Render_Frame
                ifndef RTYPE_NO_GS
                CALL GeneralSound_Init
                endif
                ifdef RTYPE_TSFM_TEST
                ; Диагностика: детект чипа + тоны. Результат детекта виден на
                ; экране полосой: зелёная — чип отвечает, красная — нет.
                CALL TsfmMusic_TestTone
                else
                ; Python-title беззвучен. Раньше Stage 1 запускался здесь и
                ; поэтому был слышен поверх неподвижного меню — звук и сцена
                ; принадлежали разным автоматам. Трек теперь запускает только
                ; Application_EnterWorld после реальной смены сцены.
                CALL TsfmMusic_Stop
                endif
                ifdef RTYPE_GAME_AUTOSTART
                ; Только отдельная диагностическая сборка patched Unreal:
                ; сразу войти в тот же Application_StartGame, минуя ожидание
                ; title-ввода Windows. Сам релиз этого CALL не содержит.
                CALL Application_StartGame
                endif

MainLoop:
                XOR  A
                LD   (RTypePyStackPhase), A
                CALL RTypePyStack_Check
                JP   C, RTypePyStack_Fatal
                LD   A, 1
                LD   (RTypePyStackPhase), A
                CALL Input_Poll
                CALL RTypePyStack_Check
                JP   C, RTypePyStack_Fatal
                ; В GAME update заранее вызывает PrepareDescriptor для живых
                ; Python-объектов. Сначала выбрать свободную половину RAM_G,
                ; чтобы все эти cells принадлежали одному будущему кадру.
                LD   A, 2
                LD   (RTypePyStackPhase), A
                LD   A, (GameMode)
                OR   A
                CALL NZ, RTypeSpriteCache_BeginFrame
                CALL RTypePyStack_Check
                JP   C, RTypePyStack_Fatal
                LD   A, 3
                LD   (RTypePyStackPhase), A
                CALL Application_Update
                CALL RTypePyStack_Check
                JP   C, RTypePyStack_Fatal
                ifndef RTYPE_NO_GS
                LD   A, 4
                LD   (RTypePyStackPhase), A
                CALL GeneralSound_Update
                CALL RTypePyStack_Check
                JP   C, RTypePyStack_Fatal
                endif
                LD   A, 5
                LD   (RTypePyStackPhase), A
                CALL TsfmMusic_Update
                CALL RTypePyStack_Check
                JP   C, RTypePyStack_Fatal
                LD   A, 6
                LD   (RTypePyStackPhase), A
                CALL Render_Frame
                CALL RTypePyStack_Check
                JP   C, RTypePyStack_Fatal
                JR   MainLoop

; ---------------------------------------------------------------------------
; Application_Update — верхний автомат ровно из rtype_port/app.py.
;
; TITLE исполняет заставку до ready и принимает отдельный фронт FIRE/ENTER.
; GAME получает реальный ввод. Других сцен в rtype_port/app.py нет.
; ---------------------------------------------------------------------------
Application_Update:
                LD   A, (GameMode)
                OR   A
                JP   Z, Title_Update
                JP   ArcadeGame_Update

; Новая сессия сначала собирается при GameMode=TITLE: RTypeTarget_Init тогда
; не тратит время на промежуточную загрузку texture. После установки GAME
; нужный level переносится в RAM_G одним DMA-путём и запускается музыка.
Application_EnterWorld:
                PUSH AF
                ; Game RAM_G intentionally reuses the large title-atlas range.
                ; First make a black list active and wait for its swap; otherwise
                ; DMA tears the still-visible menu while stage textures arrive.
                CALL Render_BlankFrame
                CALL Render_WaitPreviousSwap
                XOR  A
                LD   (GameMode), A
                CALL ArcadeGame_Init
                POP  AF
                LD   (GameMode), A
                CALL ArcadeBackground_Upload
                CALL RTypePyChargeAssetsUpload
                CALL RTypeSpriteCache_Reset
                LD   A, (RTypeTargetStage)
                CALL RTypeTarget_SelectStage
                ; Первый GAME-кадр возникает прямо из Title_Update, поэтому
                ; обычный MainLoop ещё не успел открыть его cache buffer.
                CALL RTypeSpriteCache_BeginFrame
                ifndef RTYPE_TSFM_TEST
                CALL TsfmMusic_Start
                endif
                RET

Application_StartGame:
                LD   A, APP_SCENE_GAME
                JP   Application_EnterWorld

; ---------------------------------------------------------------------------
; Резидентный FAT32/SD front-end. Все процедуры этого блока физически ниже
; #8000: raw_pak временно отображает buffer-page в slot2 и loader overlay в
; slot3. Главный стек #4EFF заменяется локальным видимым стеком #41F0.
; ---------------------------------------------------------------------------
Loader_Init:
                LD   (RTypeLoaderSavedSP), SP
                LD   SP, RTypeLoaderStackTop
                CALL Loader_MapIn
                CALL sd_init
                JR   Loader_Leave

Loader_Mount:
                LD   (RTypeLoaderSavedSP), SP
                LD   SP, RTypeLoaderStackTop
                CALL Loader_MapIn
                CALL RawPak_Mount                 ; CF=1: FAT32 смонтирована
                JR   Loader_Leave

Loader_OpenFile:                                  ; HL = zero-terminated имя
                LD   (RTypeLoaderSavedSP), SP
                LD   SP, RTypeLoaderStackTop
                CALL Loader_MapIn
                CALL RawPak_OpenFile              ; CF=1: найден и построены extents
                JR   Loader_Leave

Loader_ReadSectors:                               ; C=page, HL=offset, B=count
                LD   (RTypeLoaderSavedSP), SP
                LD   SP, RTypeLoaderStackTop
                CALL Loader_MapIn
                CALL RawPak_ReadSectors           ; ВАЖНО: CF=1 здесь означает ошибку

Loader_Leave:
                PUSH AF                           ; сохранить carry результата драйвера
                LD   A, CorePage + 1
                SetPage2_A                        ; raw_pak менял slot2 — вернуть Core
Loader_SavedPage3 EQU $ + 1
                LD   A, #00
                SetPage3_A
                POP  AF
                LD   SP, (RTypeLoaderSavedSP)
                RET

Loader_MapIn:
                ; Вариант SetPage3_A не портит HL с именем файла.
                GetPage3
                LD   (Loader_SavedPage3), A
                LD   A, RTYPE_LOADER_PAGE
                SetPage3_A
                RET

; При старте сначала пробуем заменить встроенный Stage 1 файлом с SD. Чтение
; идёт только во временное окно, поэтому любой timeout оставляет SPG-pack целым.
RTypeStageStorage_Init:
                XOR  A
                LD   (RTypeStageStorageAvailable), A
                CALL Loader_Init
                CALL Loader_Mount
                RET  NC
                LD   A, 1
                LD   (RTypeStageStorageAvailable), A
                CALL RTypeStage_LoadPack
                RET  C
                XOR  A
                LD   (RTypeStageStorageAvailable), A
                RET

; A=1…8. Межуровневый dispatcher вызывает этот вход вместо прямого SelectStage.
; При рабочей SD новый pack атомарно заменяет активный; без SD остаётся прежний
; встроенный путь, полезный для диагностики SPG и host-регрессий.
RTypeStage_LoadAndSelect:
                LD   (RTypeStageLoadNumber), A
                LD   A, (RTypeStageStorageAvailable)
                OR   A
                JR   Z, .embedded
                LD   A, (RTypeStageLoadNumber)
                CALL RTypeStage_LoadPack
                RET  NC                           ; старый pack не повреждён
.embedded:      LD   A, (RTypeStageLoadNumber)
                JP   RTypeTarget_SelectStage

; A=1…8. Полный файл читается по 32 сектора (ровно одна 16-КБ TS-страница).
; Внутри цикла НЕТ DMA/FT812: фаза SD обязана полностью завершиться первой.
RTypeStage_LoadPack:
                CP   1
                JP   C, .fail
                CP   RTYPE_STAGE_PACK_COUNT + 1
                JP   NC, .fail
                LD   (RTypeStageLoadNumber), A
                DEC  A
                LD   L, A
                LD   H, 0
                LD   D, H
                LD   E, L                         ; DE = index
                ADD  HL, HL                       ; 2*index
                ADD  HL, HL                       ; 4*index
                EX   DE, HL                       ; HL=index, DE=4*index
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL                       ; 8*index
                ADD  HL, DE                       ; 12*index (имя всегда 11+NUL)
                LD   DE, RTypeStagePackNameTable
                ADD  HL, DE
                CALL Loader_OpenFile
                JR   NC, .fail

                LD   A, (RTypeStageLoadNumber)
                DEC  A
                LD   E, A
                LD   D, 0
                LD   HL, RTypeStagePackPageTable
                ADD  HL, DE
                LD   A, (HL)
                LD   (RTypeStageLoadPages), A
                LD   (RTypeStageLoadRemain), A
                LD   A, RTYPE_STAGE_STAGING_PAGE
                LD   (RTypeStageLoadDestPage), A
.readPage:      LD   A, (RTypeStageLoadDestPage)
                LD   C, A
                LD   HL, 0
                LD   B, 32                        ; 32*512 = одна полная страница
                CALL Loader_ReadSectors
                JR   C, .fail                     ; обратная carry-конвенция ReadSectors
                LD   HL, RTypeStageLoadDestPage
                INC  (HL)
                LD   HL, RTypeStageLoadRemain
                DEC  (HL)
                JR   NZ, .readPage

                ; До первой DMA проверяем magic и запись именно нужного уровня.
                LD   A, RTYPE_STAGE_STAGING_PAGE
                SetPage3_A
                LD   HL, #C000
                LD   A, (HL)
                CP   'R'
                JR   NZ, .fail
                INC  HL
                LD   A, (HL)
                CP   'T'
                JR   NZ, .fail
                INC  HL
                LD   A, (HL)
                CP   'Z'
                JR   NZ, .fail
                INC  HL
                LD   A, (HL)
                CP   '2'
                JR   NZ, .fail
                LD   A, (RTypeStageLoadNumber)
                DEC  A
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL                       ; 8*index
                LD   D, H
                LD   E, L
                ADD  HL, HL
                ADD  HL, HL
                ADD  HL, HL                       ; 64*index
                ADD  HL, DE                       ; 72*index
                LD   DE, #C040
                ADD  HL, DE
                LD   A, (RTypeStageLoadNumber)
                CP   (HL)
                JR   NZ, .fail

                ; Только после полного успешного SD-чтения начинается отдельная
                ; DMA-фаза: staging #B0… -> active target window #49… .
                CALL RTypeStage_CommitDMA
                SCF
                RET
.fail:          OR   A                            ; CF=0, активный pack не менять
                RET

RTypeStage_CommitDMA:
                LD   A, RTYPE_STAGE_STAGING_PAGE
                LD   (RTypeStageLoadSourcePage), A
                LD   A, RTYPE_STAGE_PACK_BASE_PAGE
                LD   (RTypeStageLoadDestPage), A
                LD   A, (RTypeStageLoadPages)
                LD   (RTypeStageLoadRemain), A
.page:          LD   A, (RTypeStageLoadSourcePage)
                LD   D, A
                LD   A, (RTypeStageLoadDestPage)
                LD   E, A
                CALL RTypeDma_CopyPage
                LD   HL, RTypeStageLoadSourcePage
                INC  (HL)
                LD   HL, RTypeStageLoadDestPage
                INC  (HL)
                LD   HL, RTypeStageLoadRemain
                DEC  (HL)
                JR   NZ, .page
                RET

; D=source page, E=destination page. Одна операция = 32 bursts по 512 байт.
; Код и стек находятся в slot1, поэтому DMA может свободно писать любые pages.
RTypeDma_CopyPage:
                XOR  A
                LD   BC, DMASADDRL
                OUT  (C), A
                LD   BC, DMASADDRH
                OUT  (C), A
                LD   A, D
                LD   BC, DMASADDRX
                OUT  (C), A
                XOR  A
                LD   BC, DMADADDRL
                OUT  (C), A
                LD   BC, DMADADDRH
                OUT  (C), A
                LD   A, E
                LD   BC, DMADADDRX
                OUT  (C), A
                LD   A, #FF                      ; 256 words = 512 bytes/burst
                LD   BC, DMALEN
                OUT  (C), A
                LD   A, 31                       ; 32 bursts = 16384 bytes
                LD   BC, DMANUM
                OUT  (C), A
                LD   A, DMA_RAM
                LD   BC, DMACTR
                OUT  (C), A
.wait:         LD   BC, DMASTATUS
                IN   A, (C)
                AND  DMA_WNR
                JR   NZ, .wait
                RET

; ---------------------------------------------------------------------------
; Динамический RAM -> FT812 DMA. Контракт совместим с нужной частью
; FT.WriteMem: source page заранее записывается в RTypeFT_DmaSourcePage,
; HL=offset/CPU-адрес, A:DE=RAM_G destination, BC=чётный byte count;
; на выходе A:DE сдвинуты на count. Большие неизменяемые атласы больше не
; прогоняются Z80 через OUTI — копированием занимается DMA-контроллер TS-Conf.
; ---------------------------------------------------------------------------
RTypeFT_WriteMemDMA:
                LD   (RTypeFT_DmaDstHigh), A
                LD   (RTypeFT_DmaDstLow), DE
                LD   (RTypeFT_DmaSize), BC
                SRL  B
                RR   C                            ; bytes -> 16-bit words
                LD   A, B
                LD   (RTypeFT_DmaWordsHi), A
                LD   A, C
                LD   (RTypeFT_DmaWordsLo), A
                FT_ON
RTypeFT_DmaDstHigh EQU $ + 1
                LD   A, #00
                OR   #80                          ; FT812 memory-write transaction
                OUT  (SPI_DATA), A
RTypeFT_DmaDstLow EQU $ + 1
                LD   DE, #0000
                LD   A, D
                OUT  (SPI_DATA), A
                LD   A, E
                OUT  (SPI_DATA), A
                LD   A, L
                LD   BC, DMASADDRL
                OUT  (C), A
                LD   A, H
                AND  #3F                          ; offset внутри физической page
                LD   BC, DMASADDRH
                OUT  (C), A
RTypeFT_DmaSourcePage EQU $ + 1
                LD   A, #00
                LD   BC, DMASADDRX
                OUT  (C), A
                LD   A, (RTypeFT_DmaWordsHi)
                OR   A
                JR   Z, .tail
                DEC  A
                LD   BC, DMANUM
                OUT  (C), A
                LD   A, #FF
                LD   BC, DMALEN
                OUT  (C), A
                LD   A, DMA_RAM_SPI
                LD   BC, DMACTR
                OUT  (C), A
.waitFull:      LD   BC, DMASTATUS
                IN   A, (C)
                AND  DMA_WNR
                JR   NZ, .waitFull
.tail:          LD   A, (RTypeFT_DmaWordsLo)
                OR   A
                JR   Z, .done
                DEC  A
                LD   BC, DMALEN
                OUT  (C), A
                XOR  A
                LD   BC, DMANUM
                OUT  (C), A
                LD   A, DMA_RAM_SPI
                LD   BC, DMACTR
                OUT  (C), A
.waitTail:      LD   BC, DMASTATUS
                IN   A, (C)
                AND  DMA_WNR
                JR   NZ, .waitTail
.done:          FT_OFF
                LD   HL, (RTypeFT_DmaSize)
                LD   DE, (RTypeFT_DmaDstLow)
                ADD  HL, DE
                EX   DE, HL
                LD   A, (RTypeFT_DmaDstHigh)
                ADC  A, 0
                RET
RTypeFT_DmaWordsHi: DEFB 0
RTypeFT_DmaWordsLo: DEFB 0
RTypeFT_DmaSize:    DEFW 0

; ---------------------------------------------------------------------------
; Пакетная запись host command buffer в write-only REG_CMDB_WRITE FT812.
;
; RTypeFT_CmdWriteDMA:     HL=source в resident page #06, BC=bytes.
; RTypeFT_CmdWritePageDMA: A=physical source page, HL=offset/VMA, BC=bytes.
;
; Входной размер обязан быть кратен четырём. Перед каждым DMA проверяется
; реальный REG_CMDB_SPACE; один transfer никогда не превышает документированные
; #0FFC bytes FIFO. Тайм-аут возвращает CF=1 вместо вечного зависания Z80.
; Оба входа сохраняют AF/BC/DE/HL так же, как прежний FT.Coprocessor.Write.
; ---------------------------------------------------------------------------
RTypeFT_CmdWriteDMA:
                LD   A, CorePage + 1
RTypeFT_CmdWritePageDMA:
                LD   (RTypeFT_CmdSourcePage), A
                PUSH AF
                PUSH BC
                PUSH DE
                PUSH HL
                LD   A, C
                AND  3
                JR   NZ, .failure                ; FIFO принимает только dword
                LD   (RTypeFT_CmdSource), HL
                LD   (RTypeFT_CmdRemain), BC
                LD   A, B
                OR   C
                JR   Z, .success
.resetTimeout:  LD   HL, #1000
                LD   (RTypeFT_CmdTimeout), HL
.waitSpace:     CALL FT.Coprocessor.IsFault
                JR   C, .failure
                FT_RD_REG16 FT_REG_CMDB_SPACE    ; BC=free bytes
                LD   A, C
                AND  #FC
                LD   C, A                        ; conservative dword alignment
                LD   A, B
                CP   #10
                JR   C, .spaceCapped
                LD   BC, #0FFC                   ; hardware maximum usable FIFO
.spaceCapped:   LD   A, B
                OR   C
                JR   NZ, .chooseChunk
                LD   HL, (RTypeFT_CmdTimeout)
                DEC  HL
                LD   (RTypeFT_CmdTimeout), HL
                LD   A, H
                OR   L
                JR   NZ, .waitSpace
                JR   .failure
.chooseChunk:   LD   HL, (RTypeFT_CmdRemain)
                OR   A
                SBC  HL, BC
                JR   NC, .chunkReady             ; remaining >= free
                ADD  HL, BC                       ; restore remaining
                LD   B, H
                LD   C, L                        ; final short chunk
.chunkReady:    LD   (RTypeFT_CmdChunk), BC
                LD   HL, (RTypeFT_CmdSource)
                LD   A, (RTypeFT_CmdSourcePage)
                LD   (RTypeFT_DmaSourcePage), A
                LD   A, (FT_REG_CMDB_WRITE >> 16) & #FF
                LD   DE, FT_REG_CMDB_WRITE & #FFFF
                CALL RTypeFT_WriteMemDMA
                LD   BC, (RTypeFT_CmdChunk)
                LD   HL, (RTypeFT_CmdSource)
                ADD  HL, BC
                LD   (RTypeFT_CmdSource), HL
                LD   HL, (RTypeFT_CmdRemain)
                OR   A
                SBC  HL, BC
                LD   (RTypeFT_CmdRemain), HL
                LD   A, H
                OR   L
                JR   NZ, .resetTimeout
.success:       POP  HL
                POP  DE
                POP  BC
                POP  AF
                OR   A                            ; CF=0
                RET
.failure:       POP  HL
                POP  DE
                POP  BC
                POP  AF
                SCF
                RET
RTypeFT_CmdSourcePage: DEFB CorePage + 1
RTypeFT_CmdSource:     DEFW 0
RTypeFT_CmdRemain:     DEFW 0
RTypeFT_CmdChunk:      DEFW 0
RTypeFT_CmdTimeout:    DEFW 0

                ; Имена/размеры генерируются одновременно с восемью PAK-файлами.
                ; Таблица находится в slot1: raw_pak может читать имя при любом
                ; отображении slot2/slot3.
                include "generated_stage_packs.inc"

; ---------------------------------------------------------------------------
; Title_Init / Title_Update — самостоятельный title активной Python-версии.
; Геометрия и строки заранее переведены в таблицы на ПК.
; ---------------------------------------------------------------------------
Title_Init:
                XOR  A
                LD   (M72_TitleTimer), A
                LD   (M72_TitleTimer + 1), A
                LD   (M72_TitleInputArmed), A
                LD   (M72_TitleReleaseCnt), A
                LD   HL, 0
                LD   (M72_TitleLogoOffset), HL
                CALL M72TitleEvents_Reset
                ; Packet 0 нужен немедленно: начальный render показывает frame 0,
                ; а первый обычный update затем выдаёт Python frame 1.
                CALL M72TitleEvents_Update
                ifdef RTYPE_TITLE_FREEZE_540
                ; Диагностика: packet 209 соответствует MAME frame 540.
                ; Идём штатным декодером, включая обычные границы страниц.
                LD   B, 210
.seek540:       PUSH BC
                CALL M72TitleEvents_Update
                POP  BC
                DJNZ .seek540
                else
                endif
                CALL RTypePythonTitle_LoadCurrent
                RET

Title_Update:
                ifdef RTYPE_TITLE_FREEZE_540
                RET
                endif
                CALL Title_AdvanceByFtClock
                ; pygame выдаёт start_pressed только на KEYDOWN/MOUSEBUTTONDOWN.
                ; Здесь хранится прошлый уровень FIRE и принимается тот же фронт.
                LD   A, (InputState)
                AND  INPUT_FIRE
                LD   B, A
                LD   A, (M72_TitleInputArmed)
                LD   C, A
                LD   A, B
                LD   (M72_TitleInputArmed), A
                LD   HL, (M72_TitleTimer)
                LD   DE, 316                     ; Python TitleScreen.ready: frame >= 315
                OR   A
                SBC  HL, DE
                RET  C
.ready:
                ifdef RTYPE_TITLE_AUTOSTART
                ; Только диагностическая сборка: после появления полного меню
                ; подставить один новый фронт FIRE. В релизе блока нет.
                LD   HL, (M72_TitleTimer)
                LD   DE, 320
                OR   A
                SBC  HL, DE
                RET  C
                LD   B, INPUT_FIRE
                LD   C, 0
                endif
                LD   A, C                        ; прошлый уровень
                OR   A
                RET  NZ
                LD   A, B                        ; текущий уровень
                OR   A
                RET  Z
                JP   Application_StartGame

; Один записанный кадр M72 приходится на один физический кадр FT812. Частоту
; задаёт source-derived generated_python_frame_timing.inc; пересчёта и пропуска
; состояний нет. Render_Frame ограничивает главный цикл реальным DLSWAP.
Title_AdvanceByFtClock:
                CALL M72TitleEvents_Update
                JP   RTypePythonTitle_LoadCurrent

; Семь visible/x/y записей берутся не из записанного M72-видеопотока, а из
; LUT, которую AST-транслятор вычислил непосредственно из
; rtype_port.title._logo_state для всех 316*7 комбинаций.
RTypePythonTitle_LoadCurrent:
                LD   HL, (M72_TitleTimer)
                DEC  HL                          ; timer = Python frame + 1
                PUSH HL
                LD   DE, 316
                OR   A
                SBC  HL, DE
                POP  HL
                JR   C, .inRange
                LD   HL, 315
.inRange:       LD   DE, 35                     ; 7 записей по 5 байт
                CALL M72Video_MulHLDE
                LD   DE, RTYPEPYTITLELOGOSTATE_ADDRESS
                ADD  HL, DE
                LD   A, RTYPEPYTITLELOGOSTATE_PAGE
                SetPage3_A
                LD   DE, M72TitleGlyphState
                LD   BC, 35
                LDIR
                RET

; ---------------------------------------------------------------------------
; M72Sprites_Upload — authentic M72 ARGB4444 blob из страниц SPG в RAM_G.
; Страницы перечислены в generated_spritepages.inc; каждая мапится в slot3
; (#C000) и уходит в FT812 одним FT.WriteMem. Функция сама двигает адрес RAM_G:
; WriteMem возвращает ADE = адрес + длина.
; ---------------------------------------------------------------------------
M72Sprites_Upload:
                LD   HL, M72SpritePageTable
                LD   (.tblPtr), HL
                LD   A, (M72_SPR_BLOB_BASE >> 16) & #FF
                LD   (.ramgHi), A
                LD   HL, M72_SPR_BLOB_BASE & #FFFF
                LD   (.ramgLo), HL
                LD   A, M72_SPR_PAGE_COUNT
                LD   (.count), A
.next:
                LD   HL, (.tblPtr)
                LD   A, (HL)                     ; физическая source page
                LD   (RTypeFT_DmaSourcePage), A
                INC  HL
                LD   E, (HL)
                INC  HL
                LD   D, (HL)                     ; DE = длина куска
                INC  HL
                LD   (.tblPtr), HL
                LD   (.chunkLen), DE
                LD   HL, #C000
                LD   BC, (.chunkLen)
                LD   DE, (.ramgLo)
                LD   A, (.ramgHi)
                CALL RTypeFT_WriteMemDMA         ; TS DMA: page→RAM_G, A:DE сдвигаются
                LD   (.ramgLo), DE
                LD   (.ramgHi), A
                LD   HL, .count
                DEC  (HL)
                JR   NZ, .next
                RET
.tblPtr:        DEFW 0
.ramgLo:        DEFW 0
.ramgHi:        DEFB 0
.chunkLen:      DEFW 0
.count:         DEFB 0

; ---------------------------------------------------------------------------
; ArcadeBackground_Upload — нижняя HUD-панель игрового экрана.
; Исходный RGB565 640x480 получен офлайн из точного M72 frame 900 через
; xBRZ6 + Lanczos, но в SPG сохраняются только последние 30 строк. Верхние
; 450 строк теперь рисует живой World ROM ring, поэтому их прежняя копия не
; должна занимать RAM_G и перекрывать адреса BG/FG-текстур. Z80 переносит сюда
; ровно 640x30x2 байт неизменяемой панели, начинающейся с экранной строки 450.
; ---------------------------------------------------------------------------
ArcadeBackground_Upload:
                LD   HL, ArcadeBgPageTable
                LD   (.tblPtr), HL
                LD   A, (ARCADE_BG_RAMG >> 16) & #FF
                LD   (.ramgHi), A
                LD   HL, ARCADE_BG_RAMG & #FFFF
                LD   (.ramgLo), HL
                LD   A, ARCADE_BG_PAGE_COUNT
                LD   (.count), A
.next:         LD   HL, (.tblPtr)
                LD   A, (HL)
                LD   (RTypeFT_DmaSourcePage), A
                INC  HL
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                INC  HL
                LD   (.tblPtr), HL
                LD   (.chunkLen), DE
                LD   HL, #C000
                LD   BC, (.chunkLen)
                LD   DE, (.ramgLo)
                LD   A, (.ramgHi)
                CALL RTypeFT_WriteMemDMA
                LD   (.ramgLo), DE
                LD   (.ramgHi), A
                LD   HL, .count
                DEC  (HL)
                JR   NZ, .next
                RET
.tblPtr:       DEFW 0
.ramgLo:       DEFW 0
.ramgHi:       DEFB 0
.chunkLen:     DEFW 0
.count:        DEFB 0

                ; Единственный вход платформы в source-derived timing contract.
                include "generated_python_frame_timing.inc"
                include "platform.asm"
                include "input.asm"
                include "generated_python_gameplay_layout.inc"
                include "arcade_game.asm"
                ; Resident bridge generated from Game.update. Bank #E5 may
                ; call only code below the switchable slot2 window.
                include "generated_python_collision.asm"
                include "generated_python_stack.asm"
                include "world_runtime.asm"
                include "object_runtime.asm"
                ; Этот gameplay backend каждый раз генерируется строгим AST-
                ; транслятором из версии, которую запускает run_python.cmd.
                include "generated_python_gameplay.asm"
                include "general_sound.asm"
                include "tsfm_music.asm"
                include "render.asm"
                include "m72_video.asm"   ; видеотракт M72 (пока не вызывается)
                ifdef RTYPE_TSFMDIAG
                include "tsfm_diag.asm"
                endif

                ; Пути SAVEBIN — от каталога запуска сборки (корень проекта).
CoreEnd:
                ; Буфер FT812 начинается с #B200. Без этого assert рост кода
                ; молча превращал последние таблицы Core в display list и уже
                ; первый кадр менял номера SPG-страниц на мусор.
                ASSERT CoreEnd <= CMD_ADDRESS_PTR
                ASSERT CMD_ADDRESS_END - CMD_ADDRESS_PTR = #0E00
                SAVEBIN "Build/Core.bin", EntryPoint, CoreEnd - EntryPoint

; Generic Python/C -> FT812 fragment transport must remain visible while
; slot2 is page #F0 and slot3 is queue page #ED/#EE.  Page #00 is permanently
; mapped in slot0.  #0400..#04FF is the hardware FMap register window, while
; the generated coordinate tables begin at #1000, leaving one isolated 2816-
; byte executable window which does not consume the packed Core pages.
                SLOT 0
                PAGE TSLibPage
                ORG  #0500
RTypePyFTFragmentResident_Start:
                include "pyz80_ft812_fragment_bridge.asm"
RTypePyFTFragmentResident_End:
                ASSERT RTypePyFTFragmentResident_Start = #0500
                ASSERT RTypePyFTFragmentResident_End <= #1000
                SAVEBIN "Build/pyz80_ft812_fragment_bridge.bin", RTypePyFTFragmentResident_Start, RTypePyFTFragmentResident_End - RTypePyFTFragmentResident_Start

; Масштабирование native M72 -> VERTEX_FORMAT-3 полностью предвычислено.
; Свободная нижняя половина постоянно отображённой page #00 даёт ровно 4 КБ:
; Z80 делает два сложения и чтение word вместо signed multiply/divide.
                SLOT 0
                PAGE TSLibPage
                ORG  #1000
RTypeCoordinateTables_Start:
                include "generated_ft812_coordinate_tables.inc"
                include "generated_python_translation.inc"
RTypeCoordinateTables_End:
                ASSERT RTypeCoordinateTables_End <= #2000
                SAVEBIN "Build/coordinate_tables.bin", RTypeCoordinateTables_Start, RTypeCoordinateTables_End - RTypeCoordinateTables_Start

; Неизменяемые таблицы занимают около 4 КБ и читаются во всех сценах. Page 0
; постоянно отображена в slot0 как TSLibPage, поэтому размещение #2000…#3FFF
; освобождает быстрый slot2 для кода/банков и не требует ни одного runtime
; remap. Это прямое использование 4 МБ TS-Conf RAM вместо уплотнения таблиц.
                SLOT 0
                PAGE TSLibPage
                ORG  #2000
RTypeResidentTables_Start:
                include "generated_m72_sprites.inc"
                include "generated_spritepages.inc"
                include "generated_m72_atlas.inc"
                include "generated_m72_sprites_atlas.inc"
                include "generated_m72_title_font.inc"
                include "generated_m72_stage.inc"
                include "generated_m72_stage_stream.inc"
                include "generated_target_pack.inc"
                include "generated_python_gameplay_tables.inc"
                include "player_intro_resident.asm"
RTypeResidentTables_End:
                ASSERT RTypeResidentTables_End <= #4000
                SAVEBIN "Build/resident_tables.bin", RTypeResidentTables_Start, RTypeResidentTables_End - RTypeResidentTables_Start

; Крупные enemy state machines исполняются из банков slot2. Core.bin уже
; сохранён, поэтому повторный ORG #8000 не меняет резидентный образ page #06:
; он только формирует отдельный бинарник, который spgbld кладёт в page #0A.
                ORG #8000
RTypeObjectBank1_Start:
                include "object_bank1.asm"
RTypeObjectBank1_End:
                ASSERT RTypeObjectBank1_End <= #C000
                SAVEBIN "Build/object_bank1.bin", RTypeObjectBank1_Start, RTypeObjectBank1_End - RTypeObjectBank1_Start

; Multipart boss handlers вынесены во второй независимый code bank. Каждый
; resident trampoline сам выбирает #0B и обязательно возвращает page #06.
                ORG #8000
RTypeObjectBank2_Start:
                include "object_bank2.asm"
RTypeObjectBank2_End:
                ASSERT RTypeObjectBank2_End <= #C000
                SAVEBIN "Build/object_bank2.bin", RTypeObjectBank2_Start, RTypeObjectBank2_End - RTypeObjectBank2_Start

; Последующие stage-specific handlers растут независимо от двух уже
; проверенных банков и отображаются resident trampoline-ами как page #0C.
                ORG #8000
RTypeObjectBank3_Start:
                include "object_bank3.asm"
RTypeObjectBank3_End:
                ASSERT RTypeObjectBank3_End <= #C000
                SAVEBIN "Build/object_bank3.bin", RTypeObjectBank3_Start, RTypeObjectBank3_End - RTypeObjectBank3_Start

; Late Stage-7 boss `$B7FB` вынесен в page #0D. Его восемь типов и terrain
; writers не отнимают место у уже проверенного Stage-2/5/6/7 банка #0C.
                ORG #8000
RTypeObjectBank4_Start:
                include "object_bank4.asm"
RTypeObjectBank4_End:
                ASSERT RTypeObjectBank4_End <= #C000
                SAVEBIN "Build/object_bank4.bin", RTypeObjectBank4_Start, RTypeObjectBank4_End - RTypeObjectBank4_Start

; Fixed weapons и player collision сканируют тот же live scheduler, но не
; раздувают resident Core: code и 80 предвычисленных `$F578`-записей живут
; в page #E5 после непересекающихся active/staging/sprite окон. Page #0F
; занята буфером RAWPAK и намеренно не используется для постоянного кода.
                ORG #8000
RTypeCollisionBank_Start:
                include "collision_bank.asm"
RTypeCollisionBank_End:
                ASSERT RTypeCollisionBank_End <= #C000
                SAVEBIN "Build/collision_bank.bin", RTypeCollisionBank_Start, RTypeCollisionBank_End - RTypeCollisionBank_Start

; Постоянные записи Force/Bits и их развернутые ROM-таблицы. Page #E6 следует
; за collision bank и не пересекается с active pack #49…#76, sprite ROM
; #77…#AF/#DE…#E4 и SD staging #B0…#DD.
                ORG #8000
RTypeFixedPlayerBank_Start:
                include "fixed_player_bank.asm"
RTypeFixedPlayerBank_End:
                ASSERT RTypeFixedPlayerBank_End <= #C000
                SAVEBIN "Build/fixed_player_bank.bin", RTypeFixedPlayerBank_Start, RTypeFixedPlayerBank_End - RTypeFixedPlayerBank_Start

; FAT32/SD-драйвер из HMM2 собирается отдельной overlay-страницей. Резидентные
; trampolines выше подменяют stack/page mappings до входа сюда.
                SLOT 3
                PAGE RTYPE_LOADER_PAGE
                ORG  #C000
RTypeLoaderOverlay_Start:
                include "sd_zc.asm"
                include "raw_pak.asm"
RTypeLoaderOverlay_End:
                ASSERT RTypeLoaderOverlay_End <= #FFFF
                SAVEBIN "Build/rtype_loader.bin", RTypeLoaderOverlay_Start, RTypeLoaderOverlay_End - RTypeLoaderOverlay_Start
