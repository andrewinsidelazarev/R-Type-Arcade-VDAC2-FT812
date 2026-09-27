; Загрузчик SPG релиза (VDAC2+, 2026-09-27): TS-Config 14 МГц, VDAC2 (FT812). Решение пользователя: «SPG → картинка
; заставки, скролл-бар индикатора загрузки основной игры, автодетект звуковой схемы», «основной код игры превращаем в
; PAK-файл», «скролл-бар как индикатор накопления Beam в игре», «картинку на экран выводим в pseudo DXT», «индикатор
; посередине нижней трети экрана», надпись ПЗУ-шрифтом FT812: «GS / TSFM», если есть GS, иначе «AY (No GS)» — «меньшим
; шрифтом слева внизу с отступом над синей панелью» (панель заставки «ZX EVOLUTION / TS-CONFIG»).
;
; В SPG — этот загрузчик (страница #05), страницы загрузчика пака (драйвер FAT32 и обработчик SD) и заставка; код игры —
; файл RTYPECOD.PAC (rtype_spg.py): сектор 0 — метка «RTYPECOD», число страниц и их номера, дальше страницы по 32 сектора.
; Порядок:
;   1. FT812 — стандартный режим TSLib VM_1024_768_59Hz, как раньше (решение пользователя 2026-09-16: без правки
;      развёртки), пустой список.
;   2. Заставка и шкала: страницы-носители SPG (плоскости pseudo-DXT1 и шкала BEAM, vdac2p_splash.py) — через DMA
;      ОЗУ→SPI подряд в RAM_G с адреса 0 (страница i — RAM_G i·16 КБ). Процессор носители не читает: DMA пака потом
;      пишет в них код, и в кэше TS-Conf не должно остаться их строк. Кадр: заставка и пустая шкала.
;   3. RTYPECOD.PAC — загрузчиком пака (LOADER_OPEN: поиск по карте по имени и размеру), страницы — через DMA SPI→RAM
;      по 32 сектора. После каждой — попытка определить плату GS (метод игры GsDetectOnce: команда #F3, ответ — бит 0
;      статуса #BB снят; до GS_PROBE_LIMIT попыток) и шкала: полная шкала BEAM открыта ножницами на долю
;      загруженного. Кадр — только когда прошлый уже показан (REG_DLSWAP = 0): чтение не ждёт развёртку.
;   4. Нулевые страницы — одна процессором, остальные — её копией через DMA ОЗУ→ОЗУ; решение о плате — в звуковую
;      страницу игры (GS_DETECTED, GS_PRESENT: игра плату заново не опрашивает).
;   5. Пак уровней и звуки — машиной, под шкалой (с 2026-09-27; пользователь: «перенести» чёрную паузу старта игры):
;      вызовы машины через страницу переключения (BootCall, rtype_switch.asm) — 0 (инициализация), 5 (открытие
;      RTYPELVL.PAC загрузчиком пака и тайлы кольца фона — DataOpen хоста, как в игре; игра его потом не повторяет) и
;      10 (звуки: сэмпл General Sound за вызов или блок эффектов AY). Загрузчик пака остаётся открытым на RTYPELVL.PAC.
;   6. Полная шкала и надпись — секунда показа, затем плавный уход в чёрное (≈0,55 с), пустой кадр и переход в
;      резидент кода p2c, как раньше.
; Шкала поделена по фазам: код, пак уровней, звуки (доли — ниже, BAR_*). Ошибка (пак не найден или не прочитан) —
; надпись вместо звуковой и остановка.
;
; Кадр — display list прямо в RAM_DL (без сопроцессора): четыре прохода pseudo-DXT1 (альфа кадра — номер цвета блока:
; L1-плоскости с COLOR_A 85 и 170, затем c1 с BLEND_FUNC(DST_ALPHA, ZERO) и c0 с BLEND_FUNC(ONE_MINUS_DST_ALPHA, ONE)),
; шкала ARGB1555, надпись — ячейками ПЗУ-шрифта FT812 (handle шрифта, ширины знаков — из таблицы метрик ПЗУ): CMD_TEXT
; не берётся, потому что его вершины ниже строки 511 при VERTEX_FORMAT 0 не проверены. Матрица битмапа ставится
; целиком (все шесть коэффициентов): шкала и надпись — при единичной.
                DEVICE ZXSPECTRUM4096
                define MAPPING_REGISTERS
TSLibPage       EQU #00
InterruptVA     EQU #4000
ResolutionWidthPtr EQU #41F3
ResolutionHeightPtr EQU #41F5
; Развёртка FT812 — стандартный режим TSLib VM_1024_768_59Hz без изменений (HCYCLE 1344, VCYCLE 806, 64 МГц:
; 59.08 Гц, строки 47.6 кГц), как у Zuma Deluxe и HMM2. Прежняя запись REG_VCYCLE = 866 давала 55 Гц, как у
; M72, но 1024×768 с такой кадровой частотой вне VESA, и часть мониторов изображение не показывала или
; показывала смещённым и растянутым. Решение пользователя 2026-09-16: только стандартный режим; игра, мелодии и
; эффекты идут по кадрам развёртки и быстрее аркады на 59.08 / 55.02 = 7.4 % (отступление на аппаратном пределе
; мониторов).
                include "../../Docs/TSLib/Include/TSConf.inc"
                include "../../Docs/TSLib/Include/Memory/Include.inc"
                include "../../Docs/TSLib/Include/Cache/Macro.inc"
                include "../../Docs/TSLib/Include/Video/Macro.inc"
                include "../../Docs/TSLib/Include/INT/Macro.inc"
                include "../../Docs/TSLib/Include/System/Macro.inc"
                include "../../Docs/TSLib/Include/FT/DL  Macro.inc"
                include "../../Docs/TSLib/Include/FT/812 Macro.inc"
                include "../../Build/V30Z80/rtype_boot.inc"
                include "../../Build/V30Z80/rtype_loader_entry.inc"
                include "../../Build/V30Z80/splash/splash.inc"

; --- геометрия экрана загрузки (физические пиксели 1024×768) --------------------------------------------------------
BEAM_X          EQU (1024-SPLASH_BEAM_W)/2      ; шкала — посередине нижней трети (строки 512…767, середина 640)
BEAM_Y          EQU 640-SPLASH_BEAM_H/2
SHADOW_DX       EQU 5                           ; тень шкалы: сдвиг вправо и вниз (второй силуэт — ещё на 2)
SHADOW_DY       EQU 6
SHADOW_ALPHA    EQU 104                         ; непрозрачность одного силуэта (из 255); вместе — ≈65 %
TEXT_FONT       EQU 28                         ; ПЗУ-шрифт FT812 (handle 16…31 — шрифты ПЗУ с включения)
TEXT_X          EQU 16                          ; надпись — слева внизу
PANEL_TOP       EQU 692                         ; верхняя кромка синей панели заставки (левый край, строка 692)
TEXT_GAP        EQU 8                           ; отступ низа строки шрифта над панелью
; Шкала — FillFixed = ширина·128 (7 дробных битов — ширина до 369 помещается в 16 бит), по фазам загрузки: код игры
; (RTYPECOD.PAC), открытие пака уровней, звуки. Доли — по замеру 2026-09-27 (модель загрузки vdac2p_boot_check.py и
; Unreal с платой GS на эмуляции её Z80): код ≈3 с (без платы — на 0,4 с дольше: ожидания ответа платы), звуки с
; платой GS ≈7 с (46 сэмплов, 600 КБ через порт платы: темп задаёт прошивка GS; модель с мгновенной платой — 3,4 с),
; блок эффектов AY без неё — 0,03 с; открытие пака на карте с кластерами 4…32 КБ — доли секунды (в модели и в Unreal
; образ с кластером в сектор — там цепочка FAT пака 28 МБ читается ≈3 с, и шкала ждёт на доле пака). Без платы
; шкала почти вся отдана коду. Решение о плате приходит во время чтения кода: цель шкалы для кода меняется, а шаг —
; остаток до цели на оставшиеся страницы (FillToward), поэтому шкала не прыгает.
BAR_FULL        EQU SPLASH_BEAM_W*128
BAR_CODE_GS     EQU BAR_FULL*30/100                     ; конец кода, плата GS есть или ещё не решено
BAR_OPEN_GS     EQU BAR_FULL*33/100                     ; пак уровней открыт
BAR_CODE_AY     EQU BAR_FULL*90/100                     ; платы нет
BAR_OPEN_AY     EQU BAR_FULL*98/100
BAR_SECTOR_GS   EQU (BAR_FULL-BAR_OPEN_GS)/GS_SECTORS_TOTAL     ; доля на сектор звука
BAR_SECTOR_AY   EQU (BAR_FULL-BAR_OPEN_AY)/AY_SECTORS_TOTAL
                ASSERT CODE_PAGE_COUNT < 128            ; делитель FillToward — меньше 128
; Вызовы машины (v30z80_runtime.asm, ApiCall) и ответ открытия пака (DATA_STATUS хоста).
API_INIT        EQU 0
API_DATA_OPEN   EQU 5
API_SOUND_PRELOAD EQU 10
DATA_READY      EQU 1
GS_PORT_CMD     EQU #00BB
GS_TIMEOUT      EQU #0800                       ; попыток ожидания статуса (как в игре, v30z80_gs.asm)
GS_PROBE_LIMIT  EQU 60                          ; попыток, прежде чем решить «платы нет» (как в игре)
HOLD_FRAMES     EQU 60                          ; показ полной шкалы с надписью, кадров развёртки (≈1 с)
FADE_STEP       EQU 8                           ; уход в чёрное: +8 непрозрачности за кадр — 32 кадра, ≈0,55 с
BOOT_PAGE       EQU #05                         ; страница этого загрузчика (окно W1)

; --- слова display list FT81x ------------------------------------------------------------------------------------
                MACRO DL_HANDLE h
                DD #05000000|(h)
                ENDM
                MACRO DL_SOURCE a
                DD #01000000|(a)
                ENDM
                MACRO DL_LAYOUT fmt, stride, h
                DD #07000000|((fmt)<<19)|(((stride)&#3FF)<<9)|((h)&#1FF)
                DD #28000000|((((stride)>>10)&3)<<2)|(((h)>>9)&3)
                ENDM
                MACRO DL_SIZE w, h
                DD #08000000|(((w)&#1FF)<<9)|((h)&#1FF)       ; NEAREST, BORDER
                DD #29000000|((((w)>>9)&3)<<2)|(((h)>>9)&3)
                ENDM
                MACRO DL_TRANSFORM a, e
                DD #15000000|((a)&#1FFFF), #16000000, #17000000, #18000000, #19000000|((e)&#1FFFF), #1A000000
                ENDM
                MACRO DL_BLEND src, dst
                DD #0B000000|((src)<<3)|(dst)
                ENDM
                MACRO DL_MASK r, g, b, a
                DD #20000000|((r)<<3)|((g)<<2)|((b)<<1)|(a)
                ENDM
                MACRO DL_VERTEX x, y
                DD #40000000|(((x)&#7FFF)<<15)|((y)&#7FFF)
                ENDM
FMT_ARGB1555    EQU 0
FMT_L1          EQU 1
FMT_RGB565      EQU 7
BL_ZERO         EQU 0
BL_ONE          EQU 1
BL_SRC_ALPHA    EQU 2
BL_DST_ALPHA    EQU 3
BL_ONE_MINUS_SRC_ALPHA EQU 4
BL_ONE_MINUS_DST_ALPHA EQU 5

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
                ; W3 содержит переведённый код, видео- и звуковой адаптеры: чтения этого окна тоже кэшируются.
                ; Тег кэша включает физическую страницу, поэтому PAGE3 не требует сброса.
                Cache_Setting EN_0000 | EN_4000 | EN_8000 | EN_C000
                SetPage0 #00
                SetPage1 BOOT_PAGE
                ; Стек — в странице загрузчика SPG (W1): загрузчик пака на выходе ставит в W0 страницу резидента машины.
                LD SP,#8000
                CALL Platform_Init
                ; Окончательная раскладка: FM-оверлей выключен, страницы — портами.
                DI
                XOR A
                LD BC,FMADDR
                OUT (C),A
                CALL FontMetrics                ; ширины знаков и высота ПЗУ-шрифта — для надписи
                CALL SplashUpload
.first:         CALL Screen                     ; заставка и пустая шкала
                JR C,.first
                ; --- код игры -----------------------------------------------------------------------------------------
                LD A,LOADER_PAGE_NUMBER
                LD BC,PAGE2
                OUT (C),A                       ; W2 — страница загрузчика пака, как у хоста
                LD A,BOOT_PAGE
                LD (LOADER_HOST_W1),A           ; загрузчик вернёт в W1 эту страницу
                LD HL,CodeFile
                CALL LOADER_OPEN
                OR A
                LD HL,TextNoFile
                JP NZ,Failure
                CALL GsProbe
                LD HL,CodePages
                LD (PagePointer),HL
                LD HL,1                         ; сектор 0 — заголовок, страницы — с сектора 1
                LD (PageSector),HL
                LD B,CODE_PAGE_COUNT
.page:          PUSH BC
                LD HL,(PagePointer)
                LD A,(HL)                       ; страница
                INC HL
                LD (PagePointer),HL
                LD HL,(PageSector)
                LD BC,32
                CALL LOADER_READ_DMA
                LD HL,TextReadError
                JP NZ,Failure
                LD HL,(PageSector)
                LD DE,32
                ADD HL,DE
                LD (PageSector),HL
                CALL GsProbe
                POP BC
                PUSH BC
                LD C,B                          ; C — страниц осталось, включая прочитанную
                LD HL,BAR_CODE_GS               ; цель шкалы к концу кода
                LD A,(GsDecided)
                OR A
                JR Z,.target
                LD A,(GsPresent)
                OR A
                JR NZ,.target
                LD HL,BAR_CODE_AY               ; платы нет — звуки прочитаются мигом
.target:        CALL FillToward
                CALL Screen                     ; прошлый кадр не показан — шкала подвинется со следующей страницей
                POP BC
                DJNZ .page
                ; --- нулевые страницы ---------------------------------------------------------------------------------
                CALL ZeroPages
                ; --- звуковая схема: решение — в игру ------------------------------------------------------------------
.decide:        LD A,(GsDecided)
                OR A
                JR NZ,.decided
                CALL GsProbe                    ; плата могла не проснуться к концу чтения — добираем попытки
                JR .decide
.decided:       LD A,SOUND_PAGE_NUMBER
                LD BC,PAGE3
                OUT (C),A
                LD A,1
                LD (GS_DETECTED_AT),A
                LD A,(GsPresent)
                LD (GS_PRESENT_AT),A
                ; --- пак уровней и звуки — машиной, под шкалой ---------------------------------------------------------
                LD A,API_INIT
                CALL MachineCall
                LD A,API_DATA_OPEN
                CALL MachineCall                ; E — DATA_STATUS
                LD A,E
                CP DATA_READY
                LD HL,TextNoLevels
                JP NZ,Failure
                LD HL,BAR_OPEN_GS
                LD DE,BAR_SECTOR_GS
                LD A,(GsPresent)
                OR A
                JR NZ,.opened
                LD HL,BAR_OPEN_AY
                LD DE,BAR_SECTOR_AY
.opened:        LD (SoundStep),DE
                LD C,1
                CALL FillToward                 ; шкала — до доли открытого пака
                CALL Screen
.sound:         LD A,API_SOUND_PRELOAD
                CALL MachineCall                ; DE — секторов прочитано, 0 — грузить больше нечего
                LD A,D
                OR E
                JR Z,.sounded
                LD HL,(SoundStep)
                LD B,H
                LD C,L
                LD HL,(FillFixed)
.sector:        ADD HL,BC                       ; FillFixed += секторов · доля
                DEC DE
                LD A,D
                OR E
                JR NZ,.sector
                LD (FillFixed),HL
                CALL Screen                     ; прошлый кадр не показан — шкала подвинется со следующим шагом
                JR .sound
.sounded:
                ; --- полная шкала и надпись — секунда показа ---------------------------------------------------------
                LD HL,SPLASH_BEAM_W*128
                LD (FillFixed),HL
.last:          CALL Screen
                JR C,.last
                CALL FtFrames
                LD (HoldStart),BC
.hold:          CALL FtFrames
                LD HL,(HoldStart)
                LD A,C
                SUB L
                CP HOLD_FRAMES
                JR C,.hold
                ; --- плавный уход в чёрное (пользователь: «после загрузки содержимое загрузочного экрана плавно увести
                ; в черное»): поверх всего — чёрный прямоугольник, непрозрачность +FADE_STEP за кадр развёртки -----------
                LD A,FADE_STEP
.fade:          LD (FadeAlpha),A
.fadeShow:      CALL Screen                     ; кадр — только после показа прошлого: шаг — кадр развёртки
                JR C,.fadeShow
                LD A,(FadeAlpha)
                CP 255
                JR Z,.blank
                ADD A,FADE_STEP
                JR NC,.fade
                LD A,255                        ; последний шаг — полностью чёрный
                JR .fade
                ; --- пустой кадр и переход в игру, как прежний загрузчик ---------------------------------------------
.blank:         CALL BlankScreen
                JR C,.blank
                DI
                LD A,RTYPE_B_DATA2
                LD BC,PAGE2
                OUT (C),A
                LD A,RTYPE_B_FIRST_BANK
                LD BC,PAGE3
                OUT (C),A
                LD SP,#3FFF                     ; как у прежнего загрузчика в миг перехода
                LD A,RTYPE_B_RESIDENT
                LD BC,PAGE0
                OUT (C),A
                LD A,RTYPE_B_FIRST_BANK
                JP RTYPE_B_START

; Ошибка: HL — надпись вместо звуковой (слева внизу), кадр с ней и остановка.
Failure:        LD (TextPointer),HL
.show:          CALL Screen
                JR C,.show
                DI
.halt:          JR .halt

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

; Вызов машины: A — номер вызова, HL и E — аргументы; DE — результат. Окно W3 — страница переключения; окно W1 и стек
; загрузчика восстанавливает её вход BootCall, окно W0 остаётся резидентом машины. Портит всё.
MachineCall:    LD D,A
                LD A,RTYPE_SWITCH_PAGE
                LD BC,PAGE3
                OUT (C),A
                LD A,D
                JP RTYPE_BOOT_CALL

; Шкала к цели HL за C шагов (1 ≤ C < 128): FillFixed += (HL − FillFixed) / C; цель не выше нынешней — без движения.
; Портит AF, BC, DE, HL.
FillToward:     LD DE,(FillFixed)
                OR A
                SBC HL,DE                       ; HL — остаток до цели
                RET C
                RET Z
                XOR A                           ; HL / C сдвигом: частное — в HL, остаток — в A (A < C < 128)
                LD B,16
.div:           ADD HL,HL
                RLA
                CP C
                JR C,.next
                SUB C
                INC L
.next:          DJNZ .div
                LD DE,(FillFixed)
                ADD HL,DE
                LD (FillFixed),HL
                RET

; --- заставка ---------------------------------------------------------------------------------------------------------
; Страницы-носители SPLASH_PAGE_LIST → RAM_G с адреса 0 подряд, по 16 КБ: DMA ОЗУ→SPI пакетами 32 × 512 байт.
; Портит всё.
SplashUpload:   LD HL,SplashPages
                LD D,0                          ; D — номер 16 КБ в RAM_G (адрес D·#4000)
.page:          LD A,(HL)
                OR A
                RET Z
                PUSH HL
                PUSH DE
                LD C,A                          ; C — страница-носитель
                FT_ON
                LD A,D
                RRCA
                RRCA
                AND #3F
                OR #80                          ; запись; биты 21…16 адреса
                OUT (SPI_DATA),A
                LD A,D
                RRCA
                RRCA
                AND #C0                         ; биты 15…14
                OUT (SPI_DATA),A
                XOR A
                OUT (SPI_DATA),A
                LD A,C
                CALL DmaPageToSpi
                FT_OFF
                POP DE
                POP HL
                INC HL
                INC D
                JR .page

; Страница A целиком (16 КБ) → SPI через DMA (FT812 уже выбран и принял адрес). Портит AF, BC.
DmaPageToSpi:   LD BC,DMASADDRX
                OUT (C),A
                XOR A
                LD BC,DMASADDRL
                OUT (C),A
                LD BC,DMASADDRH
                OUT (C),A
                LD A,255                        ; пакет — 256 слов
                LD BC,DMALEN
                OUT (C),A
                LD A,31                         ; 32 пакета
                LD BC,DMANUM
                OUT (C),A
                LD A,DMA_RAM_SPI
; Запуск DMA в режиме A и ожидание конца передачи. Портит AF, BC.
DmaRun:         LD BC,DMACTR
                OUT (C),A
.wait:          LD BC,DMASTATUS
                IN A,(C)
                AND DMA_WNR
                JR NZ,.wait
                RET

; --- нулевые страницы -----------------------------------------------------------------------------------------------
; Первая страница списка — процессором (LDIR в окне W3), остальные — её копией DMA ОЗУ→ОЗУ (32 × 512 байт). Портит всё.
ZeroPages:      LD HL,ZeroList
                LD A,(HL)
                OR A
                RET Z
                LD (ZeroSource),A
                LD BC,PAGE3
                OUT (C),A
                LD HL,#C000
                LD DE,#C001
                LD BC,#3FFF
                LD (HL),0
                LDIR
                LD HL,ZeroList+1
.page:          LD A,(HL)
                OR A
                RET Z
                INC HL
                PUSH HL
                LD BC,DMADADDRX
                OUT (C),A
                XOR A
                LD BC,DMADADDRL
                OUT (C),A
                LD BC,DMADADDRH
                OUT (C),A
                LD BC,DMASADDRL
                OUT (C),A
                LD BC,DMASADDRH
                OUT (C),A
                LD A,(ZeroSource)
                LD BC,DMASADDRX
                OUT (C),A
                LD A,255
                LD BC,DMALEN
                OUT (C),A
                LD A,31
                LD BC,DMANUM
                OUT (C),A
                LD A,DMA_RAM
                CALL DmaRun
                POP HL
                JR .page

; --- плата General Sound ----------------------------------------------------------------------------------------------
; Одна попытка, пока решение не принято (метод игры, v30z80_gs.asm GsDetectOnce): команда сброса #F3 в #BB; плата
; снимает бит 0 статуса, на шине без платы он не снимается и срабатывает таймаут. Ответила — плата есть; не ответила
; GS_PROBE_LIMIT раз — нет. Решение — надписью (TextPointer). Портит AF, BC, HL.
GsProbe:        LD A,(GsDecided)
                OR A
                RET NZ
                LD A,#F3
                LD BC,GS_PORT_CMD
                OUT (C),A
                LD HL,GS_TIMEOUT
.wait:          IN A,(C)
                RRCA
                JR NC,.present
                DEC HL
                LD A,H
                OR L
                JR NZ,.wait
                LD HL,GsProbes
                INC (HL)
                LD A,(HL)
                CP GS_PROBE_LIMIT
                RET C
                LD HL,TextAy                    ; платы нет: эффекты на AY, мелодий нет
                JR .decided
.present:       LD A,1
                LD (GsPresent),A
                LD HL,TextGs                    ; эффекты на GS, мелодии на TurboSound FM
.decided:       LD (TextPointer),HL
                LD A,1
                LD (GsDecided),A
                RET

; --- FT812 ------------------------------------------------------------------------------------------------------------
; REG_FRAMES → BC. Портит AF.
FtFrames:       LD A,(FT_REG_FRAMES>>16)&#FF
                LD DE,FT_REG_FRAMES&#FFFF
                JP FT.Read16

; Метрики ПЗУ-шрифта TEXT_FONT: указатель таблицы шрифтов — в #2FFFFC, блок шрифта n — 148 байт с номера 16: ширины
; знаков 0…127 (128 байт), формат, шаг строки, ширина и высота (по 4 байта). Верх надписи TextY = PANEL_TOP − TEXT_GAP −
; высота. Портит всё.
FontMetrics:    LD A,(FT_ROM_FONT_ADDR>>16)&#FF
                LD DE,FT_ROM_FONT_ADDR&#FFFF
                CALL FT.Read32                  ; BCDE — адрес таблицы
                LD HL,148*(TEXT_FONT-16)
                ADD HL,DE
                EX DE,HL                        ; DE — младшие 16 бит блока
                LD A,C
                ADC A,0                         ; A — биты 23…16 (перенос сложения)
                LD HL,Widths
                LD BC,144                       ; ширины, формат, шаг строки, ширина, высота
                CALL FT.ReadMem
                LD HL,PANEL_TOP-TEXT_GAP
                LD DE,(Widths+140)
                OR A
                SBC HL,DE
                LD (TextY),HL
                RET

; Кадр экрана загрузки, если прошлый уже показан (REG_DLSWAP = 0); CF = 1 — не показан, кадр не собран. Список — в
; DlBuffer: неизменная часть (DlHead), полная шкала в ножницах по FillFixed, надпись TextPointer (0 — нет), END и
; DISPLAY; затем в RAM_DL и REG_DLSWAP = кадр. Портит всё.
Screen:         LD A,(FT_REG_DLSWAP>>16)&#FF
                LD DE,FT_REG_DLSWAP&#FFFF
                CALL FT.Read8
                OR A
                SCF
                RET NZ
                LD HL,DlHead
                LD DE,DlBuffer
                LD BC,DlHeadEnd-DlHead
                LDIR
                ; ширина полной шкалы: FillFixed >> 7, не шире шкалы
                LD HL,(FillFixed)
                ADD HL,HL                       ; H — биты 14…7, перенос — бит 15
                LD A,H
                LD L,A
                LD H,0
                RL H                            ; HL = FillFixed >> 7
                LD BC,SPLASH_BEAM_W
                OR A
                SBC HL,BC
                ADD HL,BC
                JR C,.width
                LD H,B
                LD L,C
.width:         LD A,H
                OR L
                JR Z,.noFill                    ; 0 — полная шкала не рисуется
                PUSH HL
                LD HL,DlFill
                LD BC,4
                LDIR                            ; SCISSOR_XY(край шкалы)
                POP HL
                ; SCISSOR_SIZE(ширина HL, высота шкалы): #1C000000 | ширина << 12 | высота (высота < 256)
                LD A,SPLASH_BEAM_H
                LD (DE),A
                INC DE
                LD A,L
                ADD A,A
                ADD A,A
                ADD A,A
                ADD A,A                         ; биты 3…0 ширины → 7…4
                LD (DE),A
                INC DE
                LD A,L
                RRCA
                RRCA
                RRCA
                RRCA
                AND #0F
                LD C,A
                LD A,H
                ADD A,A
                ADD A,A
                ADD A,A
                ADD A,A
                OR C                            ; биты 11…4 ширины
                LD (DE),A
                INC DE
                LD A,#1C
                LD (DE),A
                INC DE
                LD HL,DlFillTail
                LD BC,DlFillTailEnd-DlFillTail
                LDIR                            ; полная шкала и ножницы — на весь экран
.noFill:        LD HL,(TextPointer)
                LD A,H
                OR L
                CALL NZ,TextWords
                LD A,(FadeAlpha)
                OR A
                JR Z,.noFade
                LD (FadeAlphaWord),A            ; COLOR_A(доля чёрного)
                LD HL,FadeWords
                LD BC,FadeWordsEnd-FadeWords
                LDIR                            ; чёрный прямоугольник на весь экран
.noFade:        LD HL,DlTail
                LD BC,DlTailEnd-DlTail
                LDIR
                EX DE,HL
                LD DE,DlBuffer
                OR A
                SBC HL,DE
                LD B,H
                LD C,L                          ; BC — длина списка
                LD HL,DlBuffer
                LD A,(FT_RAM_DL>>16)&#FF
                LD DE,FT_RAM_DL&#FFFF
                CALL FT.WriteMem
                LD A,FT_DLSWAP_FRAME
                LD DE,FT_REG_DLSWAP&#FFFF
                CALL FT.WriteReg8
                OR A                            ; CF = 0
                RET

; Пустой кадр (перед переходом в игру): как Screen, CF = 1 — прошлый ещё не показан. Портит всё.
BlankScreen:    LD A,(FT_REG_DLSWAP>>16)&#FF
                LD DE,FT_REG_DLSWAP&#FFFF
                CALL FT.Read8
                OR A
                SCF
                RET NZ
                LD HL,EmptyDL
                LD BC,12
                LD DE,0
                CALL FT.WriteDL
                LD A,FT_DLSWAP_FRAME
                LD DE,FT_REG_DLSWAP&#FFFF
                CALL FT.WriteReg8
                OR A
                RET

; Надпись HL (строка, 0 в конце) — ячейками ПЗУ-шрифта слева внизу (X = TEXT_X, Y = TextY): тень (чёрная, +2 по X и Y),
; затем белая. DE — буфер списка (на выходе — за словами надписи). Портит AF, BC, HL.
TextWords:      PUSH HL
                LD HL,TextShadowWords
                LD BC,8
                LDIR                            ; handle шрифта, чёрный
                LD HL,(TextY)
                INC HL
                INC HL
                LD (GlyphY),HL
                POP HL
                PUSH HL
                LD BC,TEXT_X+2
                CALL Glyphs                     ; тень
                LD HL,TextWhiteWords
                LD BC,4
                LDIR                            ; белый
                LD HL,(TextY)
                LD (GlyphY),HL
                POP HL
                LD BC,TEXT_X
; Знаки строки HL с X = BC, Y = GlyphY (слово): CELL(знак), VERTEX2F(x, y), x += ширина знака. Портит AF, BC, HL.
Glyphs:         LD A,(HL)
                OR A
                RET Z
                INC HL
                PUSH HL
                LD (DE),A                       ; CELL(знак): #06000000 | знак
                INC DE
                LD L,A                          ; L — знак
                XOR A
                LD (DE),A
                INC DE
                LD (DE),A
                INC DE
                LD A,#06
                LD (DE),A
                INC DE
                ; VERTEX2F(x, y) = #40000000 | x << 15 | y: байт 0 — y 7…0; байт 1 — y 14…8 и x 0 в бите 7;
                ; байт 2 — x 8…1; байт 3 — #40 | x 14…9
                LD A,(GlyphY)
                LD (DE),A
                INC DE
                LD A,C
                RRCA
                AND #80
                LD H,A
                LD A,(GlyphY+1)
                AND #7F
                OR H
                LD (DE),A
                INC DE
                LD A,B
                RRA                             ; бит 0 старшего байта x → CF
                LD A,C
                RRA
                LD (DE),A
                INC DE
                LD A,B
                SRL A
                OR #40
                LD (DE),A
                INC DE
                LD H,0                          ; x += ширина знака L
                PUSH BC
                LD BC,Widths
                ADD HL,BC
                POP BC
                LD A,(HL)
                ADD A,C
                LD C,A
                JR NC,.next
                INC B
.next:          POP HL
                JR Glyphs

; --- неизменные части списка -----------------------------------------------------------------------------------------
DlHead:         DD #02000000                    ; CLEAR_COLOR_RGB(0, 0, 0)
                DD #0F000000                    ; CLEAR_COLOR_A(0)
                DD #26000007                    ; CLEAR(1, 1, 1)
                DD #27000000                    ; VERTEX_FORMAT(0): вершины в целых пикселях
                ; handle 0, 1 — битовые плоскости L1 1024×768; 2, 3 — цвета блоков RGB565 256×192 (×4 матрицей);
                ; 4, 5 — пустая и полная шкала ARGB1555.
                DL_HANDLE 0
                DL_SOURCE SPLASH_B0
                DL_LAYOUT FMT_L1, 128, 768
                DL_SIZE 1024, 768
                DL_HANDLE 1
                DL_SOURCE SPLASH_B1
                DL_LAYOUT FMT_L1, 128, 768
                DL_SIZE 1024, 768
                DL_HANDLE 2
                DL_SOURCE SPLASH_C0
                DL_LAYOUT FMT_RGB565, 512, 192
                DL_SIZE 1024, 768
                DL_HANDLE 3
                DL_SOURCE SPLASH_C1
                DL_LAYOUT FMT_RGB565, 512, 192
                DL_SIZE 1024, 768
                DL_HANDLE 4
                DL_SOURCE SPLASH_BEAM_EMPTY
                DL_LAYOUT FMT_ARGB1555, SPLASH_BEAM_W*2, SPLASH_BEAM_H
                DL_SIZE SPLASH_BEAM_W, SPLASH_BEAM_H
                DL_HANDLE 5
                DL_SOURCE SPLASH_BEAM_FULL
                DL_LAYOUT FMT_ARGB1555, SPLASH_BEAM_W*2, SPLASH_BEAM_H
                DL_SIZE SPLASH_BEAM_W, SPLASH_BEAM_H
                DD #1F000001                    ; BEGIN(BITMAPS)
                DD #06000000                    ; CELL(0)
                ; номер цвета блока k — в альфу кадра: 85·(b0 + 2·b1)
                DL_TRANSFORM 256, 256
                DL_MASK 0, 0, 0, 1
                DL_BLEND BL_ONE, BL_ONE
                DD #10000000|85                 ; COLOR_A(85)
                DL_HANDLE 0
                DL_VERTEX 0, 0
                DD #10000000|170                ; COLOR_A(170)
                DL_HANDLE 1
                DL_VERTEX 0, 0
                ; цвет: c1·a + c0·(1 − a)
                DL_MASK 1, 1, 1, 0
                DD #10000000|255                ; COLOR_A(255)
                DL_TRANSFORM 64, 64             ; цвет блока — на 4×4 пикселя
                DL_BLEND BL_DST_ALPHA, BL_ZERO
                DL_HANDLE 3
                DL_VERTEX 0, 0
                DL_BLEND BL_ONE_MINUS_DST_ALPHA, BL_ONE
                DL_HANDLE 2
                DL_VERTEX 0, 0
                ; шкала и надпись — обычное наложение, единичная матрица
                DL_TRANSFORM 256, 256
                DL_MASK 1, 1, 1, 1
                DL_BLEND BL_SRC_ALPHA, BL_ONE_MINUS_SRC_ALPHA
                ; тень шкалы средствами FT812 (пользователь: «под шкалой BEAM сделай аппаратную тень»): силуэт шкалы —
                ; её битмап чёрным цветом и полупрозрачно, дважды со сдвигом вниз-вправо (край тени мягче)
                DD #04000000                    ; COLOR_RGB(0, 0, 0)
                DD #10000000|SHADOW_ALPHA       ; COLOR_A
                DL_HANDLE 5
                DL_VERTEX BEAM_X+SHADOW_DX+2, BEAM_Y+SHADOW_DY+2
                DL_VERTEX BEAM_X+SHADOW_DX, BEAM_Y+SHADOW_DY
                DD #04FFFFFF                    ; COLOR_RGB(255, 255, 255)
                DD #10000000|255                ; COLOR_A(255)
                DL_HANDLE 4
                DL_VERTEX BEAM_X, BEAM_Y
DlHeadEnd:
DlFill:         DD #1B000000|((BEAM_X&#7FF)<<11)|(BEAM_Y&#7FF)     ; SCISSOR_XY(край шкалы); за ним SCISSOR_SIZE
DlFillTail:     DL_HANDLE 5
                DL_VERTEX BEAM_X, BEAM_Y
                DD #1B000000                    ; SCISSOR_XY(0, 0)
                DD #1C800800                    ; SCISSOR_SIZE(2048, 2048)
DlFillTailEnd:
DlTail:         DD #21000000                    ; END
                DD #00000000                    ; DISPLAY
DlTailEnd:
; Уход в чёрное: чёрный прямоугольник на весь экран с непрозрачностью FadeAlpha (младший байт COLOR_A — от Screen).
FadeWords:      DD #21000000                    ; END (битмапы)
                DD #04000000                    ; COLOR_RGB(0, 0, 0)
FadeAlphaWord:  DD #10000000                    ; COLOR_A
                DD #1F000009                    ; BEGIN(RECTS)
                DL_VERTEX 0, 0
                DL_VERTEX 1023, 767
FadeWordsEnd:
TextShadowWords: DD #05000000|TEXT_FONT         ; BITMAP_HANDLE(шрифт)
                DD #04000000                    ; COLOR_RGB(0, 0, 0)
TextWhiteWords: DD #04FFFFFF                    ; COLOR_RGB(255, 255, 255)

EmptyDL:        FT_CLEAR_COLOR_RGB 0,0,0
                FT_CLEAR 1,1,1
                FT_DISPLAY

; Файл кода игры для LOADER_OPEN: короткое имя, размер, метка первого сектора (FILE_DESC загрузчика).
CodeFile:       DB "RTYPECODPAC"
                DD CODE_PAK_SIZE
                DB "RTYPECOD"
TextGs:         DB "GS / TSFM",0
TextAy:         DB "AY (No GS)",0
TextNoFile:     DB "RTYPECOD.PAC NOT FOUND",0
TextNoLevels:   DB "RTYPELVL.PAC NOT FOUND",0
TextReadError:  DB "SD READ ERROR",0
SplashPages:    SPLASH_PAGE_LIST
                DB 0
CodePages:      CODE_PAGE_LIST
ZeroList:       RTYPE_ZERO_PAGE_LIST
FillFixed:      DW 0                            ; доля шкалы: ширина ·128
SoundStep:      DW 0                            ; доля шкалы на сектор звука (BAR_SECTOR_GS или BAR_SECTOR_AY)
FadeAlpha:      DB 0                            ; уход в чёрное: непрозрачность прямоугольника (0 — нет)
PagePointer:    DW 0
PageSector:     DW 0
TextPointer:    DW 0                            ; надпись слева внизу (0 — нет)
TextY:          DW 0                            ; верх надписи (от высоты шрифта)
HoldStart:      DW 0
GlyphY:         DW 0
GsDecided:      DB 0
GsPresent:      DB 0
GsProbes:       DB 0
ZeroSource:     DB 0
Widths:         DS 144                          ; метрики ПЗУ-шрифта TEXT_FONT: ширины знаков, …, высота (+140)
DlBuffer:       DS 1024                         ; список кадра
CodeEnd:
                ASSERT CodeEnd < #7C00          ; выше — стек (до #8000)
                SAVEBIN "../../Build/V30Z80/rtype_boot.bin",#5000,CodeEnd-#5000
