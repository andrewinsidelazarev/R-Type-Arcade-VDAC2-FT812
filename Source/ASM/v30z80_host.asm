; Платформенная страница переведённой программы World ROM (SPG TS-Config + VDAC2): адаптеры
; видео M72 → FT812 и ввода. Логики игры здесь нет: состояние платы M72 (VRAM, палитры, буфер
; спрайтов, скроллы, растр) переводится в display list так же, как Python-версия выводит кадр
; (M72HqRenderer, модель Source/Tools/m72_ft812_compositor.py).
;
; Отображается в окно W3 только между кадрами (хуки HOST_BEFORE/HOST_AFTER резидента) и
; исполняется на стеке драйвера. Окна W1 и W2 адаптер занимает своими страницами и перед
; возвратом восстанавливает (W1 — рабочее ОЗУ V30, W2 — страница W2_PAGE).
;
; Кадр эталона (RTypeM72Machine.step_frame) — память в начале шага и скроллы нижней полосы
; после IRQ2 этого шага. Поэтому перед шагом (HostBefore) адаптер переносит изменения VRAM и
; палитр в свои структуры и собирает слова спрайтов, а после шага (HostAfter) — загружает
; палитры, собирает display list и переключает его.
;
; Изображения — двухпроходные ячейки PALETTED4444 (v30z80_video_assets.py): проход A — перо A с
; уровнем альфы, проход B — перо B; таблица палитры на (банк, палитру): запись
; `перо·16 + уровень` = цвет пера с альфой уровня. Ячейки всех палитр лежат на SD-карте в паке
; уровней RTYPELVL.PAC и загружаются при первом выводе: запись пака читает загрузчик
; (rtype_loader.asm, страница LOADER_PAGE в окне W2), поток zlib из его буфера уходит в FT812
; командой CMD_INFLATE (проходы A и B подряд). Карта слотов: (набор, палитра, код) → ячейка.
;
; Тайлы выводятся картинками групп и вертикальными полосами (v30z80_video_assets.py). Строка группы —
; 8 столбцов группы × строки карты 2k и 2k+1; класс — её непустые тайлы с одинаковыми палитрой, проходом
; приоритета и горизонтальным отражением. Класс из IMAGE_MIN тайлов и больше — одна картинка 107×60 (проход A —
; строки 0…29, проход B — 30…59), остальные тайлы — полосы 14×60 из двух тайлов столбца (пара одного класса —
; одна полоса). Картинки и полосы собирает сопроцессор FT812 командами CMD_MEMCPY из ячеек тайлов; отражение
; тайла по вертикали — копированием строк в обратном порядке, по горизонтали — матрицей при выводе. Одинаковые
; картинки и полосы — одна копия (таблицы с хешем). Слова слоя, прохода приоритета и полосы растра записываются
; в display list один раз — подпрограммой, которую основная часть вызывает один раз: у каждой вершины полосы и
; картинки (проход A, handle 0 и 1) сразу следом — вершина её прохода B (handle-псевдонимы 2 и 3 со сдвигом
; источника на 30 строк; VDAC2+, 2026-09-24 — раньше подпрограмма вызывалась дважды, при BITMAP_TRANSFORM_F = 0 и
; F = 30·256, и её слова состояния стоили на каждой строке развёртки вдвое). Причины — предел display list FT812 в
; 2048 команд и время рендера строки
; FT812: цена строки растёт с числом исполняемых команд списка, и на реальной плате при ≈2000 командах строки
; рвались; картинки групп дают ≈3 команды на 16 тайлов вместо ≈16.
;
; Потоки: для семьи (полосы, картинки), слоя, прохода приоритета (низкий — до спрайтов, высокий — после),
; вертикальной области j (строки полос 0–10, 11–21, 22–31) и группы g (столбцы 8g…8g+7) — слова
; (PALETTE_SOURCE, матрица отражения, VERTEX2II) по строкам полос; заголовок потока — начало каждой строки и
; состояние перед строкой (отражение·16 + палитра; UNKNOWN — палитра неизвестна, отражения нет): матрица, как и
; палитра, переходит из строки в строку. Координаты в словах — внутри областей FT812 по 512 пикселей, сдвиг
; скролла — VERTEX_TRANSLATE. Изменённая группа (пометки резидента, сверка с тенью VRAM) перестраивает одну
; строку полос потоков обеих семей.
;
; Спрайты: ячейка 27×60 (проходы A и B подряд), проход B — handle-псевдоним со сдвигом источника.
;
; Отступления на аппаратном пределе: ячейка тайла целиком выводится в том проходе, где
; выводится большинство её перьев (как модель compositor); позиции ячеек и картинок — целые физические
; пиксели в своих областях, тайлы внутри картинки — с шагом целых текселей (IMAGE_OFFSETS); проход B картинки
; или полосы выводится сразу за её проходом A (в столбце нахлёста тайлов разных картинок и полос тот, что выведен
; позже, ложится поверх обоими проходами — как тайл целиком у эталона M72HqRenderer); в столбце нахлёста тайлов
; одной картинки правый тайл заменяет тексел левого целиком;
; картинки слоя-прохода выводятся раньше его полос; при переполнении display list остаток кадра не выводится
; (VIDEO_DROPPED); ячейка без данных на SD или без места в RAM_G не выводится (VIDEO_MISSING); сбой
; сопроцессора FT812 — сброс сопроцессора (VIDEO_FAULTS).

                ORG #C000
HOST_ENTRY_BEFORE:                      ; #C000: хук перед шагом (ввод клавиатуры и видео)
                jp HostBefore
HOST_ENTRY_AFTER:                       ; #C003: после шага — display list
                jp HostAfter
HOST_ENTRY_VIDEO_BEFORE:                ; #C006: перед шагом — только видео (ввод даёт платформа)
                jp HostVideoBefore
HOST_ENTRY_VIDEO_RESET:                 ; #C009: RAM_G и handle FT812 занимал другой вывод
                jp HostVideoReset
HOST_ENTRY_DATA_OPEN:                   ; #C00C: открыть пак уровней на SD-карте (DE — состояние)
                jp HostDataOpen
HOST_ENTRY_VIDEO_FADE:                  ; #C00F: показанный кадр машины гаснет в чёрное
                jp HostVideoFade
HOST_ENTRY_VIDEO_SKIP:                  ; #C012: шаг с выводом — пропустить вывод (CF = 1)?
                jp HostVideoSkip

; --- константы ---------------------------------------------------------------------------------
                INCLUDE "rtype_loader.inc"
                INCLUDE "rtype_loader_entry.inc"
SPI_DATA        EQU #57
SPI_CTRL        EQU #77
FT_CS_ON        EQU #07
FT_CS_OFF       EQU #03
DMA_RAM_SPI     EQU #82
DL_LIMIT        EQU 8176-FADE_BYTES     ; байт display list до DISPLAY (место затемнения оставлено)
FADE_BYTES      EQU FADE_WORDS_END-FADE_WORDS
FADE_ALPHA_AT   EQU 24                  ; смещение слова COLOR_A в словах затемнения
MAIN_RESERVE    EQU 320+2*RING_WORDS*4  ; байт основной части (с кольцом фона двух полос), сбросов матрицы и возвратов подпрограмм (без спрайтов)
WAIT_TRIES      EQU 20000               ; опросов FT812 в ожидании (≈0,3 с на 14 МГц)
HEADER_SIZE     EQU 36                  ; начала 11 строк полос и конец (слова) + состояния перед 12 строками
HEADER_PAL      EQU 24
ROW_BUFFER_SIZE EQU 252                 ; 8 столбцов по две полосы · (PALETTE_SOURCE, матрица, VERTEX2II)
IROW_BUFFER_SIZE EQU 64                 ; IMAGE_REFS картинок · (PALETTE_SOURCE, матрица, VERTEX2II)
SLOT_SIZE       EQU 6                   ; запись тайла: непуст, набор·16 + палитра, слово, проход, fx
IMAGE_KEY_SIZE  EQU 34                  ; ключ картинки: набор·16 + палитра, fx, слова 16 слотов
; Страница состояния (VIDEO_STATE_PAGE, окно W1 #4000): заголовки потоков, копия буфера спрайтов,
; владельцы и кадры вывода ячеек спрайтов, сырая тень и цвета палитр, таблицы сдвигов (video.inc:
; TX_TABLE, TY_TABLE, SPRITE_XS — адреса в окне W1), места потоков полос (STREAM_LOC) и слова handle первого
; display list (DL_HANDLES) — тоже адреса окна W1, слова спрайтов.
SPRITE_TEMP     EQU #0E00               ; копия буфера спрайтов (#400 байт)
SPRITE_OWNER    EQU #1200               ; владелец ячейки спрайта (3 байта): набор·16 + палитра, код
SLOT_USED       EQU #1500               ; кадр последнего вывода ячейки спрайта
PAL_RAW         EQU #1600               ; 5-битные R, G, B каждого пера 32 таблиц
PAL_SHADOW      EQU #4000+#1C00         ; цвет 4 бита пера (G4·16 + B4, R4) 32 таблиц
; SPRITE_WORDS (video.inc) — слова спрайтов кадра после слов handle (DL_HANDLES_END: полосы, картинки, их псевдонимы
; прохода B, ячейки спрайтов, классы объектов) и блока защиты строки.
GUARD_ARGS      EQU DL_HANDLES_END      ; блок защиты строки FT812 (vdac2p_guard.asm): место JUMP, DL_SENT, байт спрайтов
SPRITE_WORDS_END EQU #3FF0
                ASSERT SPRITE_XS_OFFSET_END <= STREAM_LOC-#4000 && DL_HANDLES_END-#4000 <= SPRITE_WORDS
                ASSERT GUARD_ARGS+6 <= #4000+SPRITE_WORDS
; Страница тайлов (VIDEO_TILE_PAGE, окно W1 #4000 при перестройке).
STRIP_ENTRY     EQU 12                  ; запись полосы: +0 ключ (набор·16 + палитра, слово слота 0,
                                        ; слово слота 1), +5 следующая в корзине (номер + 1), +7 число
                                        ; ссылок, +9 кадр освобождения, +10 занята
STRIP_BUCKETS   EQU #2000               ; 1024 корзины хеша: первая полоса (номер + 1)
BUCKET_MASK     EQU 1023
CELL_OWNER      EQU #2800               ; владелец ячейки тайла (3 байта): набор·16 + палитра, код
IMAGE_TABLE     EQU #2A00               ; записи картинок
IMAGE_ENTRY     EQU 40                  ; запись картинки: +0 ключ (IMAGE_KEY_SIZE), +34 следующая в корзине
                                        ; (номер + 1), +36 число ссылок, +38 кадр освобождения, +39 занята
IMAGE_BUCKETS   EQU #3600               ; 128 корзин хеша картинок: первая картинка (номер + 1)
IBUCKET_MASK    EQU 127
; Рабочие записи строки в странице тайлов (адреса окна W1 на время перестройки строки).
SLOTS           EQU #4000+TILE_DATA_OFFSET ; 16 записей слотов строки группы (SLOT_SIZE байт)
                ASSERT high SLOTS == high (SLOTS+15*SLOT_SIZE) ; RowImages шагает по младшему байту адреса
IMAGE_KEY       EQU SLOTS+16*SLOT_SIZE  ; ключ картинки
IMAGE_KEY_SAVE  EQU IMAGE_KEY+IMAGE_KEY_SIZE
ROW_BUFFER      EQU #4000+#3800         ; буферы строк полос двух проходов
IROW_BUFFER     EQU #4000+#3A00         ; буферы строк картинок двух проходов
FREE_OWNER      EQU #FF
OBJ_OWNER       EQU #FE                 ; место пула спрайтов занято объектом (vdac2p_objects.asm): +1 — запись каталога
DATA_READY      EQU 1                   ; DATA_STATUS: пак открыт
DATA_FAILED     EQU 2                   ; пак не найден или не читается (код загрузчика — DATA_ERROR)
VRAM0_PAGE      EQU V30_PAGE_BASE+#34
VRAM1_PAGE      EQU V30_PAGE_BASE+#36
PAL0_PAGE       EQU V30_PAGE_BASE+#32
UNKNOWN         EQU #FF                 ; палитра перед строкой неизвестна
TRANSLATE_UNKNOWN EQU #55               ; старший байт сдвига, которого не бывает (#FF, 0, 1)
                ASSERT STRIPS*STRIP_ENTRY <= STRIP_BUCKETS && STRIP_BUCKETS+2048 <= CELL_OWNER
                ASSERT CELLS*3+CELL_OWNER <= IMAGE_TABLE && IMAGES*IMAGE_ENTRY+IMAGE_TABLE <= IMAGE_BUCKETS
                ASSERT IMAGE_BUCKETS+2*(IBUCKET_MASK+1) <= TILE_DATA_OFFSET && IMAGE_KEY_SIZE+6 == IMAGE_ENTRY
                ASSERT IMAGE_KEY_SAVE+IMAGE_KEY_SIZE <= ROW_BUFFER && ROW_BUFFER+2*ROW_BUFFER_SIZE <= IROW_BUFFER
                ASSERT IROW_BUFFER+2*IROW_BUFFER_SIZE <= #4000+TILE_TABLES_OFFSET
                ASSERT IMAGE_REFS == 4 && IHEADER_OFFSET >= 2*32*8*IMAGE_REFS*2 && IHEADER_OFFSET+96*HEADER_SIZE <= #4000

; --- вход перед кадром ---------------------------------------------------------------------------
HostBefore:
                ifdef RTYPE_MACHINE_INPUT
                call InputRead
                endif
HostVideoBefore:
                ld a,(VIDEO_READY)
                or a
                call z,VideoInit
                ; Кадр эталона: скроллы верхней полосы и выключение видео — в начале шага.
                ld hl,SCROLL_Y0
                ld de,TOP_SCROLL
                ld bc,8
                ldir
                ld a,(VID_OFF)
                ld (VIDEO_OFF_SNAP),a
                ; Показ прошлого списка здесь не ждётся (до кадрового импульса FT812): полосу, отпущенную в
                ; прошлом кадре, StripAlloc вытесняет, дождавшись показа сам (SWAP_PENDING), — ожидание
                ; только при нехватке полос.
                ld a,VIDEO_STATE_PAGE
                call Map1
                call PalettesCollect
                call RingService                ; кольцо фона ждёт полной записи (v30z80_ring.asm)
                call EarlyBefore                ; ранняя сборка: пришедшая полоса — на сверку (vdac2p_early.asm)
                call TilesUpdate
                call RingCatchUp                ; отложенные столбцы кольца — до вывода кадра (v30z80_ring.asm)
                call EarlyAfter                 ; ранняя сборка строки следующей полосы (vdac2p_early.asm)
                call SpritesBuild
                jp RestoreWindows

; Сброс видеоадаптера: полная инициализация перед следующим шагом с выводом.
HostVideoReset: xor a
                ld (VIDEO_READY),a
                ret

; Пропуск вывода при отставании от развёртки FT812 — отступление на аппаратном пределе скорости: логика M72
; исполняется каждый шаг (скорость игры как у эталона, пока процессор успевает её одну), display list строится,
; когда процессор догоняет развёртку. Долг SKIP_LAG — в кадрах развёртки: + кадры REG_FRAMES с прошлого шага с
; выводом, − 1 за шаг, в пределах 0…SKIP_LAG_MAX (отставание, которое не догнать, не копится). Долг есть и подряд
; пропущено меньше SKIP_MAX шагов — CF = 1: шаг без вывода (адаптер не зовётся ни до, ни после шага; пометки
; видеопамяти, палитр и буфер спрайтов копятся до следующего вывода). До инициализации видео (VIDEO_READY = 0) —
; вывод, долг 0. Модель сверки даёт кадр развёртки на кадр игры — пропусков нет. Портит всё.
SKIP_MAX        EQU 1
SKIP_LAG_MAX    EQU 2
HostVideoSkip:  ld a,#30
                ld de,#2004                     ; REG_FRAMES
                call FtRead16                   ; L — младший байт счётчика
                ld a,(SKIP_FRAMES)
                ld b,a                          ; B — счётчик прошлого шага
                ld a,l
                ld (SKIP_FRAMES),a              ; счётчик — для следующего шага
                ld a,(VIDEO_READY)
                or a
                jr z,.init
                ld a,l
                sub b                           ; A — кадров развёртки с прошлого шага
                ld hl,SKIP_LAG
                add a,(hl)
                jr c,.limit
                cp SKIP_LAG_MAX+1
                jr c,.step
.limit:         ld a,SKIP_LAG_MAX+1
.step:          sub 1                           ; шаг расходует кадр развёртки
                jr nc,.lag
                xor a                           ; впереди развёртки — долга нет
.lag:           ld (hl),a
                or a
                jr z,.render
                ld hl,SKIP_RUN
                ld a,(hl)
                cp SKIP_MAX
                jr nc,.render                   ; подряд пропущено SKIP_MAX — вывод
                inc (hl)
                scf
                ret
.init:          xor a
                ld (SKIP_LAG),a
.render:        xor a                           ; CF = 0
                ld (SKIP_RUN),a
                ret

; Затемнение показанного кадра машины перед выводом титула: титул загружает свои изображения в полосы,
; из которых читает этот кадр (v30z80_video_assets.py). Отступление на аппаратном пределе (RAM_G): в
; эталоне после последнего кадра игры сразу первый кадр титула. К display list в RAM_DL на место DISPLAY
; (DL_LAST) дописывается чёрный прямоугольник на весь экран; альфа растёт за FADE_STEPS переключений.
HostVideoFade:  ld a,(VIDEO_SHOWN)
                or a
                ret z
                xor a
                ld (VIDEO_SHOWN),a
                call FadeWaitSwap
                ld a,#30
                ld de,(DL_LAST)
                call FtOpenWrite
                ld hl,FADE_WORDS
                ld b,FADE_BYTES
.word:          ld a,(hl)                       ; слова — байтами (EmitWord считает предел кадра)
                out (SPI_DATA),a
                inc hl
                djnz .word
                call FtClose
                ld hl,FADE_ALPHAS
.step:          ld a,(hl)
                or a
                ret z
                push hl
                ld hl,(DL_LAST)
                ld de,FADE_ALPHA_AT
                add hl,de
                ex de,hl
                ld a,#30
                call FtOpenWrite
                pop hl
                push hl
                ld a,(hl)
                out (SPI_DATA),a                ; младший байт COLOR_A — альфа
                call FtClose
                ld a,2
                ld de,#2054                     ; REG_DLSWAP = DLSWAP_FRAME
                call FtWriteReg8
                call FadeWaitSwap
                pop hl
                inc hl
                jr .step

; Ждать показа запрошенного списка (REG_DLSWAP = 0), не дольше WAIT_TRIES опросов; SWAP_PENDING = 0.
; Портит всё.
FadeWaitSwap:   xor a
                ld (SWAP_PENDING),a
                ld hl,WAIT_TRIES
                ld (WAIT_LEFT),hl
.wait:          ld a,#30
                ld de,#2054
                call FtRead16
                ld a,l
                or a
                ret z
                call WaitTick
                jr nz,.wait
                ret

; --- вход после кадра ----------------------------------------------------------------------------
HostAfter:      call FrameEmit
                ld hl,VIDEO_FRAME
                inc (hl)
                jp RestoreWindows

; Открытие пака уровней по вызову платформы (после первого кадра титула, чтобы игра не ждала
; поиска по карте): DE — DATA_STATUS.
HostDataOpen:   ld a,V30_PAGE_BASE+WORK_PAGE
                call Map1
                ld a,(DATA_STATUS)
                or a
                call z,DataOpen
                ld a,(DATA_STATUS)
                ld e,a
                ld d,0
                jp RestoreWindows

; Загрузчик: поиск RTYPELVL.PAC по всей SD-карте по имени и размеру, таблица кусков файла.
; DATA_STATUS — DATA_READY или DATA_FAILED. Портит всё, окно W2.
DataOpen:       call LoaderMap
                call LOADER_INIT
                ld (DATA_ERROR),a
                or a
                ld a,DATA_READY
                jr z,.status
                ld a,DATA_FAILED
.status:        ld (DATA_STATUS),a
                cp DATA_READY
                ret nz
                call RingTilesLoad              ; родные тайлы фона (v30z80_ring.asm); не прочитались — фон ячейками
                ld a,0
                jr nz,.ring
                call RingInit                   ; таблицы «байт тайла → тексели с палитрой»
                ld a,1
                ifdef RTYPE_NO_RING
                xor a                           ; диагностика: фон ячейками, чтобы сравнить цену строки FT812
                endif
.ring:          ld (RING_ON),a
                ret

; W2 — страница загрузчика; загрузчик вернёт окно W1 хоста (HOST_W1). Сохраняет DE, HL; портит AF, BC.
LoaderMap:      ld a,LOADER_PAGE
                call Map2
                ld a,(HOST_W1)
                ld (LOADER_HOST_W1),a
                ret

; --- окна и SPI ----------------------------------------------------------------------------------
Map1:           ld (HOST_W1),a
                ld bc,PORT_PAGE1
                out (c),a
                ret
Map2:           ld bc,PORT_PAGE2
                out (c),a
                ret
RestoreWindows: ld a,V30_PAGE_BASE+WORK_PAGE
                call Map1
                ld a,(W2_PAGE)
                cp #FF
                ret z
                add a,V30_PAGE_BASE
                jr Map2

; Запись SPI в память FT812: A — старшие 6 бит адреса, DE — младшие 16. Портит AF, C.
FtOpenWrite:    ld c,a
                ld a,FT_CS_ON
                out (SPI_CTRL),a
                ld a,c
                or #80
                out (SPI_DATA),a
                ld a,d
                out (SPI_DATA),a
                ld a,e
                out (SPI_DATA),a
                ret
FtClose:        ld a,FT_CS_OFF
                out (SPI_CTRL),a
                ret
; Слово из памяти FT812: A:DE — адрес → HL. Портит AF, C.
FtRead16:       ld c,a
                ld a,FT_CS_ON
                out (SPI_CTRL),a
                ld a,c
                out (SPI_DATA),a
                ld a,d
                out (SPI_DATA),a
                ld a,e
                out (SPI_DATA),a
                out (SPI_DATA),a                ; пустой байт после адреса
                in a,(SPI_DATA)                 ; пустое чтение
                in a,(SPI_DATA)
                ld l,a
                in a,(SPI_DATA)
                ld h,a
                jr FtClose
; Байт в регистр FT812: DE — младшие 16 бит адреса #30xxxx, A — значение.
FtWriteReg8:    push af
                ld a,#30
                call FtOpenWrite
                pop af
                out (SPI_DATA),a
                jr FtClose
; Слово HL в регистр FT812: DE — младшие 16 бит адреса #30xxxx. Портит AF, C.
FtWriteReg16:   ld a,#30
                call FtOpenWrite
                ld a,l
                out (SPI_DATA),a
                ld a,h
                out (SPI_DATA),a
                jr FtClose

; DMA RAM→SPI в открытую запись: A — страница, HL — чётное смещение, BC — чётное число байт.
; Пакеты по 256 слов через число пакетов, остаток — отдельным запуском. Портит всё.
DmaToSpi:       ld (DMA_PAGE),a
                ld (DMA_OFFSET),hl
.loop:          ld a,b
                or c
                ret z
                ld a,b
                srl a                           ; полных пакетов по 512 байт
                jr z,.last
                push bc
                ld (DMA_NUMBER),a
                dec a
                ld e,a
                ld d,#FF
                call DmaStart
                ld a,(DMA_NUMBER)
                add a,a                         ; байт = число·512: старший байт + 2·число
                ld e,a
                ld hl,(DMA_OFFSET)
                add a,h
                ld h,a
                ld (DMA_OFFSET),hl
                pop bc
                ld a,b
                sub e
                ld b,a
                jr .loop
.last:          ld a,b
                rra
                ld a,c
                rra                             ; слов (< 256)
                dec a
                ld d,a
                ld e,0
; D — длина пакета в словах − 1, E — число пакетов − 1; DMA_PAGE, DMA_OFFSET — источник.
DmaStart:       call DmaSource
                ld a,DMA_RAM_SPI
; Запуск DMA в режиме A и ожидание конца передачи. Портит AF, BC.
DmaGo:          ld bc,DMACTR
                out (c),a
.wait:          ld bc,DMASTATUS
                in a,(c)
                and DMA_WNR
                jr nz,.wait
                ret
; Регистры источника (DMA_PAGE:DMA_OFFSET), длины пакета в словах − 1 (D) и числа пакетов − 1 (E). Портит AF, BC, HL.
DmaSource:      ld hl,(DMA_OFFSET)
                ld a,l
                ld bc,DMASADDRL
                out (c),a
                ld a,h
                ld bc,DMASADDRH
                out (c),a
                ld a,(DMA_PAGE)
                ld bc,DMASADDRX
                out (c),a
                ld a,d
                ld bc,DMALEN
                out (c),a
                ld a,e
                ld bc,DMANUM
                out (c),a
                ret

; DMA RAM→RAM в кэш: DMA_PAGE:DMA_OFFSET → VIDEO_CACHE_PAGE:COPY_TO (смещение в странице), BC байт; адреса и число
; байт чётные (DMA TS-Config передаёт слова). Пакеты по 256 слов через число пакетов, остаток — отдельным
; запуском, как DmaToSpi. Портит всё.
CacheCopy:        ld a,b
                or c
                ret z
                ld a,b
                srl a                           ; полных пакетов по 512 байт
                jr z,.last
                push bc
                ld (DMA_NUMBER),a
                dec a
                ld e,a
                ld d,#FF
                call CacheCopyRun
                ld a,(DMA_NUMBER)
                add a,a                         ; байт = число·512: старший байт + 2·число
                ld e,a
                ld hl,(DMA_OFFSET)
                add a,h
                ld h,a
                ld (DMA_OFFSET),hl
                ld hl,(COPY_TO)
                ld a,e
                add a,h
                ld h,a
                ld (COPY_TO),hl
                pop bc
                ld a,b
                sub e
                ld b,a
                jr CacheCopy
.last:          ld a,b
                rra
                ld a,c
                rra                             ; слов (< 256)
                dec a
                ld d,a
                ld e,0
; Один запуск RAM→RAM: D — слов в пакете − 1, E — пакетов − 1.
CacheCopyRun:     call DmaSource
                ld hl,(COPY_TO)
                ld a,l
                ld bc,DMADADDRL
                out (c),a
                ld a,h
                ld bc,DMADADDRH
                out (c),a
                ld a,VIDEO_CACHE_PAGE
                ld bc,DMADADDRX
                out (c),a
                ld a,DMA_RAM
                jp DmaGo

; --- display list: одна запись SPI в RAM_DL ------------------------------------------------------------
; Список не длиннее DL_LIMIT байт до DISPLAY: запись за RAM_DL (8 КБ) попала бы в регистры FT812
; с #302000 (частота, сброс сопроцессора — отказ вывода). Предел содержимого — DL_CAP (у
; подпрограмм меньше: место основной части и спрайтов оставлено). Первое непоместившееся слово
; или пакет заполняет список (DL_FULL, VIDEO_DROPPED): остальное содержимое не выводится, чтобы
; состояние палитры, сдвигов и матрицы не разошлось с пропущенными словами.
; Слово DE:HL (DE — старшие байты). Место: DL_SENT + 4 не больше DL_CAP (сравнение байтами, без 16-битного вычитания).
; Портит AF.
EmitWord:       ld a,(DL_FULL)
                or a
                ret nz
                push hl
                ld hl,(DL_SENT)
                inc hl
                inc hl
                inc hl
                inc hl                          ; HL — занято после слова
                ld a,(DL_CAP+1)
                cp h
                jr c,EmitFull                   ; старший байт предела меньше — места нет
                jr nz,.room
                ld a,(DL_CAP)
                cp l
                jr c,EmitFull
.room:          ld (DL_SENT),hl
                pop hl
; Слово DE:HL без учёта длины (DISPLAY в конце списка, запись после переоткрытия). Во время записи подпрограммы в
; кэш (CAPTURE) слово копируется и туда. Портит AF.
EmitRaw:        ld a,l
                out (SPI_DATA),a
                ld a,h
                out (SPI_DATA),a
                ld a,e
                out (SPI_DATA),a
                ld a,d
                out (SPI_DATA),a
                ld a,(CAPTURE)
                or a
                ret z
; Слово DE:HL в копию подпрограммы (CAPTURE_PTR в окне W2); места в слоте нет — запись копии прекращается
; (CAPTURE = 0, копия не станет годной). Портит AF.
CaptureWord:    push bc
                ld b,h
                ld c,l                          ; BC — младшее слово
                ld hl,CAPTURE_BASE
                ld a,(CAPTURE_PTR+1)
                sub (hl)                        ; старший байт занятого (слова по 4 байта: младший кратен 4)
                cp CACHE_DL_BYTES/256
                jr nc,.overflow
                ld hl,(CAPTURE_PTR)
                ld (hl),c
                inc hl
                ld (hl),b
                inc hl
                ld (hl),e
                inc hl
                ld (hl),d
                inc hl
                ld (CAPTURE_PTR),hl
                jr .done
.overflow:      xor a
                ld (CAPTURE),a
.done:          ld h,b
                ld l,c
                pop bc
                ret
                ASSERT CACHE_DL_BYTES % 256 == 0
EmitFull:       pop hl
DlFull:         ld a,1
                ld (DL_FULL),a
                push hl
                ld hl,(VIDEO_DROPPED)
                inc hl
                ld (VIDEO_DROPPED),hl
                pop hl
                ret
; Слово DE:HL на зарезервированном месте (JUMP, RETURN): выводится всегда, счёт DL_SENT. Портит AF.
EmitReserved:   push hl
                ld hl,(DL_SENT)
                inc hl
                inc hl
                inc hl
                inc hl
                ld (DL_SENT),hl
                pop hl
                jr EmitRaw

; Пакет потока: A — страница, HL — смещение, BC — байт. Во время записи подпрограммы в кэш пакет копируется и
; туда (DMA RAM→RAM). Портит всё.
DlBurst:        ld (DMA_PAGE),a
                ld a,(DL_FULL)
                or a
                ret nz
                ld (BURST_OFFSET),hl
                ld hl,(DL_SENT)
                add hl,bc
                ld de,(DL_CAP)
                inc de
                or a
                sbc hl,de
                jr nc,DlFull
                add hl,de
                ld (DL_SENT),hl
                ld a,(CAPTURE)
                or a
                call nz,CaptureBurst
                ld a,(DMA_PAGE)
                ld hl,(BURST_OFFSET)
                jp DmaToSpi

; Пакет DlBurst (DMA_PAGE, BURST_OFFSET, BC байт) в копию подпрограммы с CAPTURE_PTR; не помещается в слот —
; запись копии прекращается. Сохраняет BC; портит AF, DE, HL, DMA_OFFSET.
CaptureBurst:   push bc
                ld hl,(CAPTURE_PTR)
                ld a,(CAPTURE_BASE)
                ld d,a
                ld e,0
                or a
                sbc hl,de                       ; байт уже в копии
                add hl,bc
                ld de,CACHE_DL_BYTES+1
                or a
                sbc hl,de
                jr nc,.overflow
                ld hl,(CAPTURE_PTR)
                ld a,h
                sub #80
                ld d,a
                ld e,l
                ld (COPY_TO),de                 ; смещение приёмника в странице кэша
                add hl,bc
                ld (CAPTURE_PTR),hl
                ld hl,(BURST_OFFSET)
                ld (DMA_OFFSET),hl
                call CacheCopy
                pop bc
                ret
.overflow:      xor a
                ld (CAPTURE),a
                pop bc
                ret

; B слов из таблицы HL.
EmitTable:      push bc
                ld c,(hl)
                inc hl
                ld b,(hl)
                inc hl
                ld e,(hl)
                inc hl
                ld d,(hl)
                inc hl
                push hl
                ld h,b
                ld l,c
                call EmitWord
                pop hl
                pop bc
                djnz EmitTable
                ret

; --- инициализация ------------------------------------------------------------------------------------
; Пак уровней открывается, если ещё не открыт. Все группы VRAM и все палитры помечаются
; изменёнными (перестройка без сверки с тенью); заголовки потоков обеих семей: строки пустые, палитра
; перед строкой неизвестна; ячейки, полосы и картинки в RAM_G прежнего вывода недействительны (слова
; карты слотов владельцев — «ячейка не загружена», таблицы полос и картинок и ссылки позиций пусты);
; геометрия пуста; handle — в первый display list. На экране до первого DLSWAP ещё титул: его
; изображения лежат в картинках с номера GUARD_IMAGES (v30z80_video_assets.py), поэтому два кадра
; (TITLE_GUARD; второй — пока ждётся показ первого списка) картинки берутся только из первых.
VideoInit:      ld a,(DATA_STATUS)
                or a
                call z,DataOpen
                ld a,2
                ld (TITLE_GUARD),a
                ld a,1
                ld (SWAP_PENDING),a             ; список титула мог быть ещё не показан
                ld (VIDEO_READY),a
                ld (VIDEO_HANDLES),a
                ld (VIDEO_DIRTY),a
                ld (VIDEO_FORCE),a
                xor a
                ld (OBJ_VALID),a                ; пул объектов RAM_G недействителен (vdac2p_objects.asm)
                ld (RING_READY),a
                ld a,(RING_ON)
                ld (RING_FULL),a                ; кольцо фона — полная запись, когда титул уже не показан
                ld hl,VRAM_DIRTY0
                ld de,VRAM_DIRTY0+1
                ld bc,576-1
                ld (hl),#FF
                ldir
                ld hl,VRAM_DIRTY1
                ld de,VRAM_DIRTY1+1
                ld bc,576-1
                ld (hl),#FF
                ldir
                ld hl,PAL_DIRTY0
                ld de,PAL_DIRTY0+1
                ld bc,32-1
                ld (hl),#FF
                ldir
                ld hl,RETRY0
                ld de,RETRY0+1
                ld bc,64-1
                ld (hl),0
                ldir                            ; RETRY0 и RETRY1: всё и так перестраивается
                ld hl,VIS_ROWS_A
                ld de,VIS_ROWS_A+1
                ld bc,20-1
                ld (hl),#FF
                ldir                            ; видимость неизвестна — всё видно
                ld hl,0
                ld (STRIP_HAND),hl
                ld (IMAGE_HAND),hl
                ld (CELL_HAND),hl
                xor a
                ld (SPRITE_HAND),a
                ld hl,LAYER_STREAMS
                ld de,LAYER_STREAMS+1
                ld bc,8+24-1
                ld (hl),0
                ldir                            ; LAYER_STREAMS и REGION_GROUPS обеих семей
                ASSERT REGION_GROUPS == LAYER_STREAMS+8
                ld hl,GEOMETRY
                ld de,GEOMETRY+1
                ld bc,4*GEOMETRY_SIZE-1
                ld (hl),0
                ldir
                ld hl,CACHE_OK
                ld de,CACHE_OK+1
                ld bc,8-1
                ld (hl),0
                ldir                            ; копий подпрограмм нет
                ld hl,PAL_PENDING
                ld de,PAL_PENDING+1
                ld bc,64-1
                ld (hl),0
                ldir
                ; страница тайлов: ячейки тайлов свободны, полосы свободны, корзины пусты
                ld a,VIDEO_TILE_PAGE
                call Map1
                ld hl,#4000+CELL_OWNER
                ld bc,CELLS
                ld de,0
                call OwnersRelease
                ld hl,#4000
                ld de,#4001
                ld bc,CELL_OWNER-1
                ld (hl),0
                ldir
                ld hl,#4000+IMAGE_TABLE
                ld de,#4000+IMAGE_TABLE+1
                ld bc,TILE_DATA_OFFSET-IMAGE_TABLE-1
                ld (hl),0
                ldir                            ; картинки свободны, корзины картинок пусты (таблицы адресов целы)
                ; ссылки позиций на полосы
                ld a,VIDEO_POSITION_PAGE
                call Map1
                ld hl,#4000
                ld de,#4001
                ld bc,#4000-1
                ld (hl),0
                ldir
                ; страница картинок: ссылки строк групп пусты, заголовки потоков картинок пусты (места потоков целы)
                ld a,VIDEO_IMAGE_PAGE
                call Map1
                ld hl,#4000
                ld de,#4001
                ld bc,ISTREAM_LOC-#4000-1
                ld (hl),0
                ldir
                ld hl,#4000+IHEADER_OFFSET
                call HeadersUnknown
                ; страница состояния: ячейки спрайтов свободны, заголовки потоков пусты
                ld a,VIDEO_STATE_PAGE
                call Map1
                ld hl,#4000+SPRITE_OWNER
                ld bc,SPRITE_CELLS
                ld de,SPRITE_SLOT0
                call OwnersRelease
                ld hl,#4000
                ld de,#4001
                ld bc,SPRITE_TEMP-1
                ld (hl),0
                ldir
                ld hl,#4000+SLOT_USED
                ld de,#4000+SLOT_USED+1
                ld bc,SPRITE_CELLS-1
                ld (hl),0
                ldir
                ld hl,#4000+PAL_RAW
                ld de,#4000+PAL_RAW+1
                ld bc,32*16*3-1
                ld (hl),#FF                     ; сырая тень не совпадает ни с одним цветом
                ldir
                ld hl,#4000
; 96 обнулённых заголовков потоков с HL: состояние перед каждой строкой неизвестно. Портит AF, BC, DE, HL.
HeadersUnknown: ld b,96
.header:        push bc
                push hl
                ld de,HEADER_PAL
                add hl,de
                ld b,HEADER_SIZE-HEADER_PAL
.pal:           ld (hl),UNKNOWN
                inc hl
                djnz .pal
                pop hl
                ld de,HEADER_SIZE
                add hl,de
                pop bc
                djnz .header
                ret

; --- ввод ------------------------------------------------------------------------------------------------
; Клавиатура ZX и Kempston → IN0/IN1 M72 (активный ноль): вправо #0001, влево #0002, вниз
; #0004, вверх #0008, кнопка 2 (Force) #0040, кнопка 1 (огонь) #0080; START 1 — IN1 #0001,
; COIN 1 — IN1 #0004. Стрелки — Caps+5…8, QAOP; огонь — Space, Enter, M, Kempston-fire;
; Force — N; монета — 5, старт — 1 (как клавиши 5 и 1 Python-версии).
;
; Нужен только самостоятельному циклу машины Start/FrameLoop (промежуточный машинный SPG сборки,
; отладка): в выпускном SPG машину ведёт оболочка p2c через ApiCall, ввод даёт она, а этот вход
; не выполняется никогда. Собирается с -DRTYPE_MACHINE_INPUT; без него освобождает 184 байта
; страницы хоста (22.09.2026: основная часть страницы была заполнена до последнего байта).
                ifdef RTYPE_MACHINE_INPUT
InputRead:      ld e,0                          ; нажатые биты IN0 (1 — нажато)
                ld bc,#DFFE                     ; P O I U Y
                in a,(c)
                rra
                jr c,.noP
                set 0,e
.noP:           rra
                jr c,.noO
                set 1,e
.noO:           ld bc,#FBFE                     ; Q W E R T
                in a,(c)
                rra
                jr c,.noQ
                set 3,e
.noQ:           ld bc,#FDFE                     ; A S D F G
                in a,(c)
                rra
                jr c,.noA
                set 2,e
.noA:           ld bc,#FEFE                     ; Caps Z X C V
                in a,(c)
                rra
                jr c,.noCaps
                ld bc,#EFFE                     ; 0 9 8 7 6
                in a,(c)
                bit 2,a                         ; 8 — вправо
                jr nz,.no8
                set 0,e
.no8:           bit 4,a                         ; 6 — вниз
                jr nz,.no6
                set 2,e
.no6:           bit 3,a                         ; 7 — вверх
                jr nz,.no7
                set 3,e
.no7:           ld bc,#F7FE                     ; 1 2 3 4 5
                in a,(c)
                bit 4,a                         ; Caps+5 — влево
                jr nz,.noCaps
                set 1,e
.noCaps:        ld bc,#7FFE                     ; Space Sym M N B
                in a,(c)
                bit 0,a
                jr nz,.noSpace
                set 7,e
.noSpace:       bit 2,a
                jr nz,.noM
                set 7,e
.noM:           bit 3,a
                jr nz,.noN
                set 6,e
.noN:           ld bc,#BFFE                     ; Enter L K J H
                in a,(c)
                rra
                jr c,.noEnter
                set 7,e
.noEnter:       ld bc,#001F                     ; Kempston: 000FUDLR
                in a,(c)
                cp #FF
                jr z,.noKempston
                rra
                jr nc,.kr
                set 0,e
.kr:            rra
                jr nc,.kl
                set 1,e
.kl:            rra
                jr nc,.kd
                set 2,e
.kd:            rra
                jr nc,.ku
                set 3,e
.ku:            rra
                jr nc,.noKempston
                set 7,e
.noKempston:    ld a,e
                cpl
                ld (IN0),a
                ld a,#FF
                ld (IN0+1),a
                ld e,#FF                        ; биты IN1 (0 — нажато)
                ld bc,#F7FE
                in a,(c)
                rra
                jr c,.no1
                res 0,e                         ; START 1
.no1:           bit 3,a                         ; клавиша 5 (бит 4 до сдвига)
                jr nz,.no5
                res 2,e                         ; COIN 1
.no5:           ld a,(IN1)
                or #05
                and e
                ld (IN1),a
                ret
                endif

; --- палитры ---------------------------------------------------------------------------------------------
; Перед шагом: помеченные палитры (PAL_DIRTY — запись переводом) и перья (PEN_DIRTY — ядро переноса палитр)
; сверяются с сырой тенью (5-битные R, G, B), у изменённых перьев — цвет 4 бита (как M72HqRenderer._palette4) в
; PAL_SHADOW (G4·16 + B4, R4) и бит в PAL_PENDING. W1 — страница состояния.
PalettesCollect:
                ld a,(VIDEO_DIRTY)
                or a
                ret z
                ld hl,PAL_DIRTY0
                ld c,0                          ; таблица банк·16 + палитра
                ld b,32                         ; счётчик — в B: проход пустой таблицы без сверки с 32
.table:         ld a,(hl)
                or a
                jr z,.next
                ld (hl),0
                push hl
                push bc
                ld a,c
                rrca
                rrca
                rrca
                rrca
                and 1
                add a,PAL0_PAGE
                call Map2
                pop bc
                push bc
                ld a,c
                ld (PAL_TABLE),a
                call PaletteRead
                pop bc
                pop hl
.next:          inc hl
                inc c
                djnz .table
                ld hl,PEN_DIRTY0
                ld c,0
                ld b,32
.penTable:      ld e,(hl)
                inc hl
                ld d,(hl)
                ld a,d
                or e
                jr z,.penNext
                xor a
                ld (hl),a
                dec hl
                ld (hl),a
                inc hl
                ld (PEN_MASK),de
                push hl
                push bc
                ld a,c
                rrca
                rrca
                rrca
                rrca
                and 1
                add a,PAL0_PAGE
                call Map2
                pop bc
                push bc
                ld a,c
                ld (PAL_TABLE),a
                call PensRead
                pop bc
                pop hl
.penNext:       inc hl
                inc c
                djnz .penTable
                ret

; Перья PEN_MASK палитры PAL_TABLE (W2 — страница палитры банка): как у PaletteRead, только отмеченные. Портит всё.
PensRead:       ld c,0                          ; C — перо
                ld de,(PEN_MASK)                ; маска — в регистрах: пропуск неотмеченного пера без памяти
.pen:           ld a,d
                or e
                ret z
                srl d
                rr e
                jr nc,.next
                push de
                push bc
                ld a,(PAL_TABLE)
                ld l,a
                ld h,0
                ld d,h
                ld e,l
                add hl,hl
                add hl,de
                add hl,hl
                add hl,hl
                add hl,hl
                add hl,hl                       ; таблица·48
                ld a,c
                ld e,a
                add a,a
                add a,e
                ld e,a
                ld d,0
                add hl,de                       ; + перо·3
                ld de,#4000+PAL_RAW
                add hl,de
                ex de,hl                        ; DE — сырая тень пера
                ld a,(PAL_TABLE)
                and 15
                add a,a
                add a,a
                add a,a
                add a,a
                ld l,a
                ld h,#40
                add hl,hl                       ; #8000 + палитра·32
                ld a,c
                add a,a
                add a,l
                ld l,a
                jr nc,.word
                inc h                           ; HL — слово R пера
.word:          ld a,(hl)
                and 31
                ex de,hl
                cp (hl)
                jr nz,.changedR
                inc hl
                ex de,hl
                ld a,h
                add a,4
                ld h,a                          ; слово G (+#400)
                ld a,(hl)
                and 31
                ex de,hl
                cp (hl)
                jr nz,.changedG
                inc hl
                ex de,hl
                ld a,h
                add a,4
                ld h,a                          ; слово B (+#800)
                ld a,(hl)
                and 31
                ex de,hl
                cp (hl)
                jr z,.same
                dec hl                          ; тень → G, слово → G
                ex de,hl
                ld a,h
                sub 4
                ld h,a
                ex de,hl
.changedG:      dec hl                          ; тень → R, слово → R
                ex de,hl
                ld a,h
                sub 4
                ld h,a
                ex de,hl
.changedR:      ex de,hl                        ; HL — слово R, DE — тень R
                call PenStore
.same:          pop bc
                pop de                          ; маска перьев
.next:          inc c
                jr .pen

; Палитра PAL_TABLE (банк·16 + палитра); W2 — страница палитры банка. Перья сверяются с сырой
; тенью покомпонентно, изменённые записывает PenStore. Портит всё.
PaletteRead:    ld a,(PAL_TABLE)
                ld l,a
                ld h,0
                ld d,h
                ld e,l
                add hl,hl
                add hl,de
                add hl,hl
                add hl,hl
                add hl,hl
                add hl,hl                       ; таблица·48
                ld de,#4000+PAL_RAW
                add hl,de
                ex de,hl                        ; DE — сырая тень пера (R5, G5, B5)
                ld a,(PAL_TABLE)
                and 15
                add a,a
                add a,a
                add a,a
                add a,a
                ld l,a
                ld h,#40
                add hl,hl                       ; HL — слово R пера: #8000 + палитра·32
                ld bc,16*256                    ; B — перьев, C — перо
.pen:           ld a,(hl)
                and 31
                ex de,hl
                cp (hl)
                jr nz,.changedR
                inc hl
                ex de,hl
                ld a,h
                add a,4
                ld h,a                          ; слово G (+#400)
                ld a,(hl)
                and 31
                ex de,hl
                cp (hl)
                jr nz,.changedG
                inc hl
                ex de,hl
                ld a,h
                add a,4
                ld h,a                          ; слово B (+#800)
                ld a,(hl)
                and 31
                ex de,hl
                cp (hl)
                jr nz,.changedB
                inc hl
                ex de,hl
                ld a,h
                sub 8
                ld h,a
.nextPen:       inc hl
                inc hl
                inc c
                djnz .pen
                ret
.changedB:      dec hl                          ; тень → G, слово → G
                ex de,hl
                ld a,h
                sub 4
                ld h,a
                ex de,hl
.changedG:      dec hl                          ; тень → R, слово → R
                ex de,hl
                ld a,h
                sub 4
                ld h,a
                ex de,hl
.changedR:      ex de,hl                        ; HL — слово R, DE — тень R
                push bc
                call PenStore
                pop bc
                jr .nextPen

; Перо C палитры PAL_TABLE изменилось: HL — слово R пера (окно W2), DE — его сырая тень (W1).
; Сырая тень, цвет 4 бита в PAL_SHADOW (G4·16 + B4, R4), бит пера в PAL_PENDING. На выходе
; HL — слово R, DE — тень следующего пера. Портит AF, B.
PenStore:       ld a,(hl)
                and 31
                ld (de),a
                inc de
                call Color4
                ld b,a                          ; R4
                ld a,h
                add a,4
                ld h,a
                ld a,(hl)
                and 31
                ld (de),a
                inc de
                call Color4
                add a,a
                add a,a
                add a,a
                add a,a
                ld (PAL_G5),a                   ; G4·16
                ld a,h
                add a,4
                ld h,a
                ld a,(hl)
                and 31
                ld (de),a
                inc de
                call Color4
                push hl
                push de
                ld hl,PAL_G5
                or (hl)
                ld (PAL_B5),a                   ; G4·16 + B4
                ld a,(PAL_TABLE)
                ld l,a
                ld h,0
                add hl,hl
                add hl,hl
                add hl,hl
                add hl,hl
                add hl,hl                       ; таблица·32
                ld a,c
                add a,a
                ld e,a
                ld d,0
                add hl,de
                ld de,PAL_SHADOW
                add hl,de
                ld a,(PAL_B5)
                ld (hl),a
                inc hl
                ld (hl),b
                ; PAL_PENDING[таблица·2 + перо >> 3] |= 1 << (перо & 7)
                ld a,c
                and 7
                ld e,a
                ld d,0
                ld hl,VIDEO_BITS
                add hl,de
                ld b,(hl)
                ld a,(PAL_TABLE)
                add a,a
                ld e,a
                ld a,c
                cp 8
                jr c,.lowPens
                inc e
.lowPens:       ld hl,PAL_PENDING
                add hl,de
                ld a,(hl)
                or b
                ld (hl),a
                pop de
                pop hl
                ld a,h
                sub 8
                ld h,a
                ret

; A (0…31) → COLOR4[A]: 4 бита цвета, как M72HqRenderer._palette4. Сохраняет BC, DE, HL.
Color4:         push hl
                ld hl,COLOR4
                add a,l
                ld l,a
                jr nc,.noCarry
                inc h
.noCarry:       ld a,(hl)
                pop hl
                ret

; После шага: изменённые перья — 16 записей таблицы (уровни 0…15) каждое. Перья таблицы — по битам маски (DE, сдвиг
; вправо, C — перо); когда в маске битов не осталось, остальные перья таблицы не перебираются.
PalettesUpload: ld hl,PAL_PENDING
                ld b,32                         ; таблиц; номер нужен только при выводе пера
.table:         ld e,(hl)
                inc hl
                ld d,(hl)                       ; DE — перья таблицы; HL → старший байт
                ld a,d
                or e
                jr nz,.pens
.next:          inc hl
                djnz .table
                ret
.pens:          ld a,32
                sub b
                ld (PAL_TABLE),a
                push hl
                xor a
                ld (hl),a
                dec hl
                ld (hl),a                       ; PAL_PENDING таблицы = 0
                ld c,a                          ; C — перо
.pen:           srl d
                rr e                            ; CF — перо изменилось
                jr nc,.skip
                push bc
                push de
                ld a,c
                ld (PAL_PEN),a
                call PenUpload
                pop de
                pop bc
.skip:          inc c
                ld a,d
                or e
                jr nz,.pen
                pop hl
                jr .next

; Перо PAL_PEN таблицы PAL_TABLE: запись RAM_G по адресу таблица·512 + перо·32. Портит всё.
PenUpload:      ld a,(PAL_TABLE)
                add a,a                         ; старший байт таблица·512
                ld d,a
                ld a,(PAL_PEN)
                rrca
                rrca
                rrca
                and #1F                         ; перо·32 >> 8
                add a,d
                ld d,a
                ld a,(PAL_PEN)
                add a,a
                add a,a
                add a,a
                add a,a
                add a,a
                ld e,a
                xor a
                call FtOpenWrite
                ld a,(PAL_TABLE)
                ld l,a
                ld h,0
                add hl,hl
                add hl,hl
                add hl,hl
                add hl,hl
                add hl,hl                       ; таблица·32
                ld a,(PAL_PEN)
                add a,a
                ld e,a
                ld d,0
                add hl,de
                ld de,PAL_SHADOW
                add hl,de
                ld e,(hl)
                inc hl
                ld d,(hl)                       ; высокий полубайт старшего байта свободен под уровень
                ; Шестнадцать уровней пера — по четыре за оборот на OUT (C),r: 12 тактов против 15 у пары
                ; LD A,r / OUT (n),A. Счётчик остаётся в B: старший байт адреса порта не декодируется (при
                ; OUT (n),A там лежат сами данные). 671 такт против 859, кода — на 24 байта больше.
                ld c,SPI_DATA
                ld b,4
.level:         dup 4
                out (c),e
                out (c),d
                ld a,d
                add a,#10                       ; следующий уровень — прибавка к тому же байту
                ld d,a
                edup
                djnz .level
                call FtClose
                ld a,(PAL_TABLE)
                cp 16
                ret c                           ; палитры спрайтов (банк 0)
                ld a,(RING_ON)
                or a
                ret z
                jp RingLutPen                   ; палитра кольца фона (v30z80_ring.asm)

; --- тайлы: перестройка -------------------------------------------------------------------------------------
; Перед шагом: помеченные группы обоих слоёв. Строка полос k — строки карты 2k и 2k+1; группа строки
; полос помечена, если помечена в любой из двух строк. Пометки снимает GroupTake — только у тех групп,
; которые кадр берёт в перестройку; у отложенных они остаются до следующего кадра вместе с VIDEO_DIRTY
; (бюджет перестройки — в хвосте страницы). W1 — страница состояния на входе и выходе.
TilesUpdate:    ld a,(VIDEO_DIRTY)
                or a
                ret z
                xor a
                ld (VIDEO_DIRTY),a
                ld (TILE_LAYER),a
                ld a,CELL_BUDGET
                ld (CELL_LEFT),a                ; бюджет подгрузки — общий на кадр
                call RetryScan                  ; есть ли ждущие повтора группы
                call .layer
                ld a,1
                ld (TILE_LAYER),a
                call .layer
                xor a
                ld (VIDEO_FORCE),a
                ret
.layer:         ld a,TILE_BUDGET
                ld (TILE_LEFT),a                ; бюджеты групп на кадр — свои у каждого слоя (GroupTake)
                ld a,LAZY_BUDGET
                ld (LAZY_LEFT),a
                call LayerWindow                ; видимое окно слоя: VIS_GROUPS, VIS_ROW
                ld a,(TILE_LAYER)
                or a
                ld hl,VRAM_ROWS0
                jr z,.rows
                ld hl,VRAM_ROWS1
.rows:          ld b,32                         ; B — строк полос осталось (строка полос = 32 − B)
.strip:         ld a,(hl)
                inc hl
                or (hl)                         ; HL — строка карты 2k+1
                jr nz,.dirty
.next:          inc hl
                djnz .strip
                ret
.dirty:         ld (hl),0
                dec hl
                ld (hl),0
                inc hl
                ld a,32
                sub b
                ld (SCAN_ROW),a                 ; строка полос
                push bc
                push hl
                ld a,(SCAN_ROW)
                add a,a
                ld l,a
                ld h,0
                add hl,hl
                add hl,hl
                add hl,hl                       ; строка карты 2k · 8
                ld a,(TILE_LAYER)
                or a
                ld de,VRAM_DIRTY0
                jr z,.base
                ld de,VRAM_DIRTY1
.base:          add hl,de
                ld b,0
.group:         call GroupTake                  ; пометки группы и бюджет перестройки (v30z80_runtime.asm)
                jr nc,.nextGroup
                push hl
                push bc
                ld a,b
                ld (TILE_GROUP),a
                ld a,(SCAN_ROW)
                ld (TILE_ROW),a
                call RetryTake                  ; группа ждала полосы — без сверки с тенью
                ld hl,VIDEO_FORCE
                or (hl)
                ld (ROW_FORCE),a
                call StripRowRebuild
                pop bc
                pop hl
.nextGroup:     inc hl
                inc b
                ld a,b
                cp 8
                jr c,.group
                pop hl
                pop bc
                call RowRestore                 ; отложенной группе пометки строки возвращаются
                jr .next

; Бит повторной сборки группы TILE_GROUP строки полос TILE_ROW слоя TILE_LAYER (ставит StripFromSlots при
; нехватке полосы) снимается; A — #FF, если был, иначе 0. Портит F, D, E, HL.
RetryTake:      ld a,(TILE_ROW)
                ld e,a
                ld d,0
                ld a,(TILE_LAYER)
                or a
                ld hl,RETRY0
                jr z,.layer
                ld hl,RETRY1
.layer:         add hl,de
                ld a,(TILE_GROUP)
                inc a
                ld d,a
                ld a,#80
.bit:           rlca
                dec d
                jr nz,.bit
                ld e,a                          ; маска группы
                and (hl)
                ret z
                ld a,e
                cpl
                and (hl)
                ld (hl),a
                ld a,#FF
                ret

; Группа TILE_GROUP строки полос TILE_ROW слоя TILE_LAYER пересобирается в следующих кадрах без сверки с тенью:
; бит группы в RETRY0/RETRY1 и пометки строки карты 2k в VRAM_ROWS и VRAM_DIRTY слоя, VIDEO_DIRTY взведён.
; Зовут: нехватка полосы (StripFromSlots) и бюджет перестройки групп (каскад StripRowRebuild). Портит всё.
GroupRetry:     ld a,(TILE_ROW)
                ld e,a
                ld d,0
                ld a,(TILE_LAYER)
                or a
                ld hl,RETRY0
                jr z,.layer
                ld hl,RETRY1
.layer:         add hl,de
                ld a,(TILE_GROUP)
                ld b,a
                inc b
                ld a,#80
.bit:           rlca
                djnz .bit
                or (hl)
                ld (hl),a                       ; бит группы в байте строки полос
                ld a,(TILE_LAYER)
                or a
                ld hl,VRAM_ROWS0
                ld bc,VRAM_DIRTY0
                jr z,.marks
                ld hl,VRAM_ROWS1
                ld bc,VRAM_DIRTY1
.marks:         ld a,e
                add a,a
                ld e,a                          ; строка карты 2k
                add hl,de
                ld (hl),#FF
                ex de,hl
                add hl,hl
                add hl,hl
                add hl,hl                       ; 2k · 8
                add hl,bc
                ld a,(TILE_GROUP)
                ld e,a
                ld d,0
                add hl,de
                ld (hl),#FF
                ld a,1
                ld (VIDEO_DIRTY),a
                ret

; Группа B строки полос SCAN_ROW в окне слоя: CF = 1 — видна (перестраивать сразу, откладывать нельзя).
; Иначе CF = 0 и Z = 1 — срочная: строка в окне, но группа правее него по столбцам (войдёт при скролле —
; столбец карты это 8 пикселей, скролл не быстрее пикселя за кадр, то есть запас не меньше восьми кадров).
; Z = 0 — ожидающая: строка вне окна по вертикали, её не видно, пока окно не уедет. Строк полос в окне 17
; (256 строк текселей — 32 строки карты, с частичными по краям). Портит AF, C.
GroupInWindow:  ld a,(VIS_ROW2)                 ; строки полосы после растрового разрыва — видны всегда
                ld c,a
                ld a,(SCAN_ROW)
                sub c
                and 31
                ld c,a
                ld a,(VIS_ROWS2)
                cp c
                jr z,.top
                jr c,.top
                scf
                ret                             ; строка в нижней полосе — группу не откладывать
.top:           ld a,(VIS_ROW)
                ld c,a
                ld a,(SCAN_ROW)
                sub c
                and 31                          ; строк полос от верха окна по кругу
                cp 17
                jr nc,.far                      ; строка вне окна по вертикали — ждёт сдвига окна
                ld c,b
                inc c
                ld a,(VIS_GROUPS)
.bit:           rrca
                dec c
                jr nz,.bit
                ret c                           ; строка в окне и группа в маске — видна
                xor a                           ; правее окна: CF = 0, Z = 1 — срочная
                ret
.far:           or a                            ; CF = 0, Z = 0 — ожидающая
                ret
; Строка полос TILE_ROW (строки карты 2k, 2k+1) группы TILE_GROUP слоя TILE_LAYER в потоках картинок и
; полос низкого и высокого прохода. Если тайлы совпадают с тенью VRAM (и ROW_FORCE = 0) — ничего не
; меняется; если состояние (палитра, отражение) в конце строки изменилось — перестраиваются и следующие
; строки полос области (каскад, бюджетом перестройки не ограничен).
StripRowRebuild:
                ld a,(TILE_LAYER)
                or a
                ld a,VRAM0_PAGE
                jr z,.page
                ld a,VRAM1_PAGE
.page:          call Map2
                ld a,(TILE_LAYER)
                add a,VIDEO_SHADOW_PAGE0
                call Map1
                ld a,(TILE_ROW)
                add a,a
                ld h,a                          ; строка карты 2k · 256 = 2k·64 тайлов · 4 байта
                ld a,(TILE_GROUP)
                add a,a
                add a,a
                add a,a
                add a,a
                add a,a
                ld l,a                          ; + группа·8 тайлов · 4 байта
                ld (TILE_OFFSET),hl
                ld a,(ROW_FORCE)
                or a
                jr nz,.fill
                ; Сверка идёт прямо между окнами: VRAM в W2, тень в W1 — копия в TILE_TEMP нужна только
                ; изменившейся группе (её читает RingGroup, пока тень ещё старая). Помеченная, но не
                ; изменившаяся группа экономит два LDIR по 32 байта.
                ld a,h
                add a,#80
                ld h,a                          ; HL — строка 2k в VRAM
                ld de,(TILE_OFFSET)
                ld a,d
                add a,#40
                ld d,a                          ; DE — строка 2k тени
                ld b,8
.compare0:      ld a,(de)                       ; по четыре байта за оборот: 36 тактов на байт вместо 46
                cp (hl)
                jr nz,.fill
                inc hl
                inc de
                ld a,(de)
                cp (hl)
                jr nz,.fill
                inc hl
                inc de
                ld a,(de)
                cp (hl)
                jr nz,.fill
                inc hl
                inc de
                ld a,(de)
                cp (hl)
                jr nz,.fill
                inc hl
                inc de
                djnz .compare0
                ld hl,(TILE_OFFSET)
                ld a,h
                add a,#81
                ld h,a                          ; строка 2k+1 в VRAM
                ld de,(TILE_OFFSET)
                ld a,d
                add a,#41
                ld d,a                          ; строка 2k+1 тени
                ld b,8
.compare1:      ld a,(de)                       ; по четыре байта за оборот: 36 тактов на байт вместо 46
                cp (hl)
                jr nz,.fill
                inc hl
                inc de
                ld a,(de)
                cp (hl)
                jr nz,.fill
                inc hl
                inc de
                ld a,(de)
                cp (hl)
                jr nz,.fill
                inc hl
                inc de
                ld a,(de)
                cp (hl)
                jr nz,.fill
                inc hl
                inc de
                djnz .compare1
                ld a,VIDEO_STATE_PAGE
                jp Map1                         ; группа не изменилась
                ; 64 байта двух строк: VRAM (W2) → TILE_TEMP (строка 2k+1 — на #100 дальше)
.fill:          ld a,(ROW_SPEC)                 ; VDAC2+: у ранней сборки (бит 0) TILE_TEMP уже заполнен предсказанием
                rrca
                jr c,.changed
                ld hl,(TILE_OFFSET)
                ld a,h
                add a,#80
                ld h,a
                ld de,TILE_TEMP
                ld bc,32
                ldir
                ld hl,(TILE_OFFSET)
                ld a,h
                add a,#81
                ld h,a
                ld bc,32
                ldir
.changed:       ld hl,SP_BUSY                   ; VDAC2+: перестроек строк в кадре (ранняя сборка ждёт лёгкого)
                inc (hl)
                ld a,(TILE_LAYER)
                ld hl,RING_ON
                and (hl)
                call nz,RingGroup               ; слой 1: изменённые тайлы — в кольцо фона (v30z80_ring.asm)
                ld hl,(TILE_OFFSET)
                ld a,h
                add a,#40
                ld d,a
                ld e,l
                ld hl,TILE_TEMP
                ld bc,32
                ldir                            ; TILE_TEMP → тень строки 2k
                ld hl,(TILE_OFFSET)
                ld a,h
                add a,#41
                ld d,a
                ld e,l
                ld hl,TILE_TEMP+32
                ld bc,32
                ldir                            ; и строки 2k+1
                ld a,(TILE_LAYER)
                ld hl,RING_ON
                and (hl)
                call nz,RingMask                ; тайлы низкого прохода фона выводит кольцо
                ld a,(TILE_ROW)
                ld e,a
                ld d,0
                ld hl,STRIP_REGION
                add hl,de
                ld a,(hl)
                ld (TILE_REGION),a
                ld hl,STRIP_INDEX
                add hl,de
                ld a,(hl)
                ld (TILE_RR),a
                ld a,VIDEO_TILE_PAGE
                call Map1                       ; W1 — таблицы полос и картинок на время строки
                xor a
                ld (TILE_COLUMN),a
                ld (ROW_FAILED),a
                ld (UNDO_COUNT),a
                ld (IUNDO_VALID),a
                ; пустая строка без ссылок — только состояния после строки: сначала быстрая проверка одинаковых тайлов
                call RowUniformEmpty
                jr nz,.slots
                call RowRefsZero
                jr z,.empty
.slots:         call SlotsRead
                call RowEmptyCheck
                jr z,.empty
                call RowStates                  ; состояния перед строкой из заголовков, буферы строк пусты
                ld a,VIDEO_TILE_PAGE
                call Map1
                call PositionVisibility         ; видимость строки группы — для ссылок картинок и полос
                call RowImages                  ; классы от IMAGE_MIN тайлов — картинками
.column:        call ColumnStrips
                ld hl,TILE_COLUMN
                inc (hl)
                ld a,(hl)
                cp 8
                jr c,.column
                ld a,(ROW_FAILED)
                or a
                jr z,.splice
                ; Полосы не хватило: строка не меняется — ссылки позиций возвращаются, потоки прежние
                ; (показанный кусок группы остаётся целым), повтор — в следующих кадрах (RETRY0/RETRY1).
                call RowUndo
                ld a,VIDEO_STATE_PAGE
                jp Map1
.splice:        xor a
                ld (CASCADE),a
                ld (STREAM_FAMILY),a
                ld (STREAM_KIND),a
                call StreamSplice
                ld a,1
                ld (STREAM_KIND),a
                call StreamSplice
                ld a,1
                ld (STREAM_FAMILY),a
                xor a
                ld (STREAM_KIND),a
                call StreamSplice
                ld a,1
                ld (STREAM_KIND),a
                call StreamSplice
                jr .cascade
.empty:         call RowEmptyStates
.cascade:       ld a,VIDEO_STATE_PAGE
                call Map1
                ld a,(CASCADE)
                or a
                ret z
                ; следующая строка полос той же области — без сверки с тенью
                ld a,(TILE_REGION)
                ld e,a
                ld d,0
                ld hl,REGION_ROWS
                add hl,de
                ld a,(TILE_RR)
                inc a
                cp (hl)
                ret nc
                ld a,(ROW_SPEC)                 ; VDAC2+: у ранней сборки каскад в той же области — за ней (CASCADE = 2)
                or a
                jr z,.cascadeRow
                ld a,2
                ld (CASCADE),a
                ret
.cascadeRow:    ld hl,TILE_ROW
                inc (hl)
                ; Каскад бюджетом не ограничивается: у следующей строки области изменилось состояние потока,
                ; и отложить её нельзя — склейка потоков области разъедется (проверено в эмуляторе: с
                ; отложенным каскадом игровое поле не выводилось совсем).
                ld a,1
                ld (ROW_FORCE),a
                jp StripRowRebuild

; Пустая строка группы без ссылок: все 16 слотов SLOTS пусты (SlotsRead), ссылки строки группы на картинки и 8 позиций на
; полосы — нули. Тогда ни прежних, ни новых слов у строки нет, и полная перестройка (картинки, полосы, ссылки,
; склейки) ничего не меняет, кроме состояний после строки (RowEmptyStates). Z — да (окно W2 — страница позиций:
; RowEmptyStates ставит в W1 страницу картинок, и одна страница в двух окнах не нужна). W1 — страница тайлов. Портит
; AF, BC, DE, HL, окно W2.
RowEmptyCheck:  ld hl,SLOTS
                ld de,SLOT_SIZE
                ld b,16
.slot:          ld a,(hl)                       ; +0 — непуст
                or a
                ret nz
                add hl,de
                djnz .slot
; Ссылки строки группы на картинки и 8 позиций на полосы — нули? Z — да (окно W2 — страница позиций). Портит AF, BC, DE,
; HL, окно W2.
RowRefsZero:    ld a,VIDEO_IMAGE_PAGE
                call Map2
                ld a,(TILE_LAYER)
                add a,a
                add a,a
                add a,a
                add a,a
                add a,a                         ; слой·32
                ld hl,TILE_ROW
                add a,(hl)
                ld l,a
                ld h,0
                add hl,hl
                add hl,hl
                add hl,hl                       ; (слой·32 + строка)·8
                ld a,(TILE_GROUP)
                ld e,a
                ld d,0
                add hl,de
                add hl,hl
                add hl,hl
                add hl,hl                       ; ·2·IMAGE_REFS (как ImagePositionUpdate)
                ld de,#8000
                add hl,de
                ld b,2*IMAGE_REFS
.image:         ld a,(hl)
                or a
                ret nz
                inc hl
                djnz .image
                ld a,VIDEO_POSITION_PAGE
                call Map2
                ld a,(TILE_LAYER)
                add a,a
                add a,a
                add a,a
                add a,a
                add a,a                         ; слой·#20
                ld hl,TILE_ROW
                add a,(hl)
                add a,#80
                ld h,a
                ld a,(TILE_GROUP)
                add a,a
                add a,a
                add a,a
                add a,a
                add a,a
                ld l,a                          ; группа·32: 8 столбцов по 4 байта (как PositionUpdate)
                ld b,8*4
.position:      ld a,(hl)
                or a
                ret nz
                inc hl
                djnz .position
                ret                             ; Z — последний байт нулевой
                ASSERT IMAGE_REFS == 4

; Все 16 тайлов строки группы (TILE_TEMP, по 4 байта: слово кода, атрибут) одного кода и палитры (биты отражений и
; режима атрибута пустоту не меняют) — и ячейка этого кода пуста (CellFlags, как SlotRead)? Z — да: все слоты пусты без
; SlotsRead. Портит всё, кроме IX; окно W2.
RowUniformEmpty:
                ld hl,TILE_TEMP
                ld e,(hl)                       ; младший байт кода
                inc hl
                ld a,(hl)
                and #0F|RING_MARK
                ld d,a                          ; старшие 4 бита кода и маска кольца (биты 14, 15 — отражения)
                inc hl
                ld a,(hl)
                and #0F
                ld c,a                          ; палитра
                ld hl,TILE_TEMP+4
                ld b,15
.tile:          ld a,(hl)
                cp e
                ret nz
                inc hl
                ld a,(hl)
                and #0F|RING_MARK
                cp d
                ret nz
                inc hl
                ld a,(hl)
                and #0F
                cp c
                ret nz
                inc hl
                inc hl
                djnz .tile
                bit 5,d
                jr z,.cell
                xor a                           ; все 16 — маска кольца фона: строка пуста (Z)
                ret
.cell:          ld a,(TILE_LAYER)
                add a,a
                add a,a
                add a,a
                add a,a
                add a,c                         ; набор (слой)·16 + палитра
                ex de,hl                        ; HL — код
                jp CellFlags                    ; Z — пуста (или нет данных, как у SlotRead)

; Состояния после пустой строки без ссылок у четырёх потоков (семья, проход) — как StreamSplice пустой строки: начало
; строки свободно (UNKNOWN или бит выбора #20) — известное состояние после неё получает бит выбора; иначе состояние
; после строки становится состоянием перед ней (при смене — CASCADE: следующие строки области перестраиваются).
; Изменённое состояние снимает копии подпрограмм, которые его выводят (CacheInvalidate). Портит всё, окно W1.
RowEmptyStates: xor a
                ld (CASCADE),a
                ld (STREAM_FAMILY),a
.family:        ld a,(STREAM_FAMILY)
                or a
                ld a,VIDEO_STATE_PAGE
                jr z,.page
                ld a,VIDEO_IMAGE_PAGE
.page:          call Map1
                xor a
                ld (STREAM_KIND),a
.kind:          call StreamHeader
                ld de,HEADER_PAL
                add hl,de
                ld a,(TILE_RR)
                ld e,a
                ld d,0
                add hl,de                       ; HL → состояние перед строкой
                ld a,(hl)
                inc hl                          ; HL → состояние после строки
                cp UNKNOWN
                jr z,.open
                bit 5,a
                jr nz,.open
                cp (hl)
                jr z,.next                      ; то же состояние
                ld (hl),a
                ld a,1
                ld (CASCADE),a
                jr .changed
.open:          ld a,(hl)
                cp UNKNOWN
                jr z,.next
                bit 5,a
                jr nz,.next                     ; бит выбора уже стоит
                or #20
                ld (hl),a
.changed:       call CacheInvalidate
.next:          ld hl,STREAM_KIND
                inc (hl)
                ld a,(hl)
                cp 2
                jr c,.kind
                ld hl,STREAM_FAMILY
                inc (hl)
                ld a,(hl)
                cp 2
                jr c,.family
                ret

; Столбец TILE_COLUMN строки полос: тайлы строк 2k (слот 0) и 2k+1 (слот 1) из SLOTS (у тайлов картинок
; RowImages снял признак «непуст»). Пара непустых тайлов с одинаковыми палитрой, проходом приоритета и
; отражением по горизонтали — одна полоса, иначе каждый непустой тайл — своя полоса (второй слот пуст). Слова
; полос — в буферы строк проходов, ссылки — в страницу позиций. После нехватки полосы в строке (ROW_FAILED)
; остальные столбцы не собираются. W1 — страница тайлов. Портит всё.
ColumnStrips:   ld a,(ROW_FAILED)
                or a
                ret nz
                ld hl,0
                ld (NEW_REFS),hl
                ld (NEW_REFS+2),hl
                ld a,(TILE_COLUMN)
                add a,a
                ld l,a
                add a,a
                add a,l
                add a,a                         ; столбец·12 — слоты столбца в SLOTS
                ld l,a
                ld h,0
                ld de,SLOTS
                add hl,de
                ld de,SLOT_INFO
                ld bc,2*SLOT_SIZE               ; двенадцать LDI — 192 такта против 257 у LDIR
                ldi
                ldi
                ldi
                ldi
                ldi
                ldi
                ldi
                ldi
                ldi
                ldi
                ldi
                ldi
                ld a,(SLOT_INFO)
                ld b,a
                ld a,(SLOT_INFO+SLOT_SIZE)
                and b
                jr z,.separate                  ; пустой слот
                ld a,(SLOT_INFO+1)
                ld b,a
                ld a,(SLOT_INFO+SLOT_SIZE+1)
                cp b
                jr nz,.separate                 ; палитры
                ld a,(SLOT_INFO+4)
                ld b,a
                ld a,(SLOT_INFO+SLOT_SIZE+4)
                cp b
                jr nz,.separate                 ; проходы приоритета
                ld a,(SLOT_INFO+5)
                ld b,a
                ld a,(SLOT_INFO+SLOT_SIZE+5)
                cp b
                jr nz,.separate                 ; отражения по горизонтали
                ld a,3
                call StripFromSlots
                jp PositionUpdate
.separate:      ld a,(SLOT_INFO)
                or a
                ld a,1
                call nz,StripFromSlots
                ld a,(SLOT_INFO+SLOT_SIZE)
                or a
                ld a,2
                call nz,StripFromSlots
                jp PositionUpdate

; Тайл A (0…15) в TILE_TEMP → запись IX: +0 непуст (1/0), +1 набор·16 + палитра, +2 слово слота
; (бит 15 — есть, бит 14 — fy, код), +4 проход приоритета, +5 fx. Признаки проходов — CellFlags.
; Портит всё, кроме IX.
SlotRead:       add a,a
                add a,a
                ld e,a
                ld d,0
                ld hl,TILE_TEMP
                add hl,de
                ld e,(hl)
                inc hl
                ld d,(hl)                       ; слово кода: бит 14 — fx, бит 15 — fy
                ld a,d
                ld (SLOT_HIGH),a
                inc hl
                ld c,(hl)                       ; атрибут
                ld (ix+0),0
                xor a
                bit 6,d
                jr z,.noFx
                inc a
.noFx:          ld (ix+5),a
                ld a,d
                and #80
                rrca
                or #80
                ld b,a
                ld a,d
                and #0F
                or b
                ld (ix+3),a                     ; есть, fy, код
                ld (ix+2),e
                ld a,c
                and 15
                ld b,a
                ld a,(TILE_LAYER)
                add a,a
                add a,a
                add a,a
                add a,a
                add a,b
                ld (ix+1),a                     ; набор (слой)·16 + палитра
                ld a,c
                rlca
                rlca
                and 3
                ld b,a
                ld a,(TILE_LAYER)
                add a,a
                add a,a
                add a,b
                ld e,a
                ld d,0
                ld hl,PASS_TABLE
                add hl,de
                ld a,(hl)
                ld (ix+4),a                     ; проход: PASS_TABLE[слой·4 + режим]
                ld a,(SLOT_HIGH)
                and RING_MARK
                ret nz                          ; маска кольца фона (v30z80_ring.asm): слот пуст
                ld a,(ix+3)
                and #0F
                ld h,a
                ld l,(ix+2)
                ld a,(ix+1)
                call CellFlags
                ret z
                ld (ix+0),1
                ret

; 16 тайлов строки группы → записи SLOTS (как SlotRead): слот s — столбец s >> 1, строка карты 2k + (s & 1)
; (тайл TILE_TEMP: столбец + 8·строка). Портит всё.
SlotsRead:      ld ix,SLOTS
                ld b,0
.slot:          push bc
                ld a,b
                and 1
                jr z,.top
                ld a,8
.top:           ld c,a
                ld a,b
                srl a
                add a,c
                call SlotRead
                ld de,SLOT_SIZE
                add ix,de
                pop bc
                inc b
                ld a,b
                cp 16
                jr c,.slot
                ret

; Классы строки группы (слоты SLOTS): непустые тайлы с одинаковыми набором·16 + палитрой, проходом приоритета
; и fx. Класс из IMAGE_MIN тайлов и больше (не больше IMAGE_REFS классов) — картинка группы: ключ — набор·16 +
; палитра, fx и слова 16 слотов (слот не из класса — 0); картинка из таблицы или новая со сборкой (ImageFind).
; Слоты класса — в IMAGE_MASK, у них в SLOTS снимается признак «непуст» (полос у них нет), слова — в буфер строки
; картинок прохода, ссылка — в NEW_IREFS; картинки не хватило — класс остаётся полосам. Затем ссылки строки группы
; (ImagePositionUpdate). W1 — страница тайлов. Портит всё.
RowImages:      ld hl,0
                ld (IMAGE_MASK),hl
                ld (CLASS_DONE),hl
                ld (NEW_IREFS),hl
                ld (NEW_IREFS+2),hl
                ld (NEW_IREFS+4),hl
                ld (NEW_IREFS+6),hl
                xor a
                ld (IREF_COUNT),a
                ld (CLASS_SLOT),a
                ld hl,SLOTS
                ld (CLASS_RECORD),hl
                ld hl,1
                ld (CLASS_BIT),hl
.slot:          ld hl,(CLASS_RECORD)
                ld a,(hl)
                or a
                jp z,.next                      ; пустой
                ld de,(CLASS_BIT)
                ld bc,(CLASS_DONE)
                ld a,b
                and d
                jp nz,.next                     ; слот уже в своём классе
                ld a,c
                and e
                jp nz,.next
                ; класс слота: набор·16 + палитра, проход, fx
                inc hl
                ld a,(hl)
                ld (IMAGE_KEY),a
                inc hl
                inc hl
                inc hl
                ld a,(hl)
                ld (CLASS_PASS),a
                inc hl
                ld a,(hl)
                ld (IMAGE_KEY+1),a
                ld hl,IMAGE_KEY+2
                ld de,IMAGE_KEY+3
                ld bc,IMAGE_KEY_SIZE-3
                ld (hl),0
                ldir
                ld hl,0
                ld (CLASS_MASK),hl
                ; члены класса — слоты от CLASS_SLOT: IX — запись, HL — слово ключа, DE — бит, B — слот
                ld ix,(CLASS_RECORD)
                ld a,(CLASS_SLOT)
                ld b,a
                add a,a
                ld e,a
                ld d,0
                ld hl,IMAGE_KEY+2
                add hl,de
                ld de,(CLASS_BIT)
                ld c,0                          ; C — тайлов класса
.member:        ld a,(ix+0)
                or a
                jr z,.memberNext
                ld a,(IMAGE_KEY)
                cp (ix+1)
                jr nz,.memberNext               ; набор·16 + палитра
                ld a,(CLASS_PASS)
                cp (ix+4)
                jr nz,.memberNext               ; проход
                ld a,(IMAGE_KEY+1)
                cp (ix+5)
                jr nz,.memberNext               ; fx
                ld a,(ix+2)
                ld (hl),a
                inc hl
                ld a,(ix+3)
                ld (hl),a
                dec hl                          ; слово слота — в ключ
                ld a,(CLASS_MASK)
                or e
                ld (CLASS_MASK),a
                ld a,(CLASS_MASK+1)
                or d
                ld (CLASS_MASK+1),a
                inc c
.memberNext:    inc hl
                inc hl
                sla e
                rl d
                ld a,ixl                        ; все 16 записей в одной странице 256 байт (ASSERT ниже),
                add a,SLOT_SIZE                 ; поэтому шаг — по младшему байту: 23 такта вместо 46 у
                ld ixl,a                        ; push de / ld de,SLOT_SIZE / add ix,de / pop de
                inc b
                ld a,b
                cp 16
                jr c,.member
                ld a,c
                ld (CLASS_COUNT),a
                ld hl,(CLASS_DONE)
                ld de,(CLASS_MASK)
                ld a,h
                or d
                ld h,a
                ld a,l
                or e
                ld l,a
                ld (CLASS_DONE),hl
                ld a,(CLASS_COUNT)
                cp IMAGE_MIN
                jr c,.next                      ; мало тайлов — полосы
                ld a,(IREF_COUNT)
                cp IMAGE_REFS
                jr nc,.next
                call ImageFind
                jr c,.next                      ; картинок нет — класс идёт полосами
                ld (IMAGE_CURRENT),hl
                inc hl
                ex de,hl                        ; DE — ссылка (номер + 1)
                ld a,(IREF_COUNT)
                add a,a
                ld c,a
                ld b,0
                ld hl,NEW_IREFS
                add hl,bc
                ld (hl),e
                inc hl
                ld (hl),d
                ld hl,IREF_COUNT
                inc (hl)
                ld hl,(IMAGE_MASK)
                ld de,(CLASS_MASK)
                ld a,h
                or d
                ld h,a
                ld a,l
                or e
                ld l,a
                ld (IMAGE_MASK),hl
                call ImageAppend
.next:          ld hl,(CLASS_RECORD)
                ld de,SLOT_SIZE
                add hl,de
                ld (CLASS_RECORD),hl
                ld hl,(CLASS_BIT)
                add hl,hl
                ld (CLASS_BIT),hl
                ld hl,CLASS_SLOT
                inc (hl)
                ld a,(hl)
                cp 16
                jp c,.slot
                ; слоты картинок полосам не достаются
                ld hl,(IMAGE_MASK)
                ld ix,SLOTS
                ld b,16
                ld de,SLOT_SIZE
.clear:         srl h
                rr l
                jr nc,.keep
                ld (ix+0),0
.keep:          add ix,de
                djnz .clear
                jp ImagePositionUpdate

; Слова картинки IMAGE_CURRENT (ключ IMAGE_KEY, проход CLASS_PASS) в буфер строки картинок: PALETTE_SOURCE при
; смене палитры, матрица при смене отражения, VERTEX2II (слот IMAGE_SLOT0 + номер, x — столбец 8·группа). Портит
; всё.
ImageAppend:    ld a,1
                ld (STREAM_FAMILY),a
                ld a,(CLASS_PASS)
                ld (STREAM_KIND),a
                ld a,(IMAGE_KEY)
                call RowPalette
                ld a,(IMAGE_KEY+1)
                call RowTransform
                ld a,(TILE_GROUP)
                add a,a
                add a,a
                add a,a
                ld c,a
                ld b,0                          ; BC — столбец 8·группа
                ld hl,COL_X3
                add hl,bc
                ld d,(hl)                       ; байт 3 = #80 | x >> 3
                ld hl,COL_X2
                add hl,bc
                ld a,(hl)
                ld hl,TILE_ROW
                ld c,(hl)                       ; BC — строка полос
                ld hl,STRIP_Y2
                add hl,bc
                or (hl)
                ld e,a                          ; байт 2 = y >> 4 | (x & 7) << 5
                ld hl,STRIP_Y1
                add hl,bc
                ld a,(hl)
                ld hl,(IMAGE_CURRENT)
                ld bc,IMAGE_SLOT0
                add hl,bc
                or h
                ld h,a                          ; байт 1 = слот >> 8 | Y1
                jp RowPair

; Состояние перед строкой TILE_RR для обеих семей и проходов. Байт заголовка: UNKNOWN — начало строки свободно;
; выбор·#20 + отражение·16 + палитра — с битом выбора начало тоже свободно (пустые строки перед ней ничего не
; выводят): строка открыта (ROW_OPEN), палитру и отражение начала задаст её первое слово (ROW_START); без бита —
; ROW_PAL, ROW_FLIP. Буферы строк пусты. Заголовки полос — в странице состояния, картинок — в странице картинок
; (окно W1). На выходе W1 — страница состояния. Портит всё.
RowStates:      xor a
                ld (STREAM_FAMILY),a
.family:        ld a,(STREAM_FAMILY)
                or a
                ld a,VIDEO_STATE_PAGE
                jr z,.page
                ld a,VIDEO_IMAGE_PAGE
.page:          call Map1
                xor a
                ld (STREAM_KIND),a
.kind:          call StreamHeader
                ld de,HEADER_PAL
                add hl,de
                ld a,(TILE_RR)
                ld e,a
                ld d,0
                add hl,de
                ld b,(hl)                       ; байт состояния
                call RowIndex
                ld hl,ROW_LEN
                add hl,de
                ld (hl),0
                ld hl,ROW_START
                add hl,de
                ld (hl),UNKNOWN
                ld hl,ROW_FLIP
                add hl,de
                ld (hl),0
                ld hl,ROW_OPEN
                add hl,de
                ld (hl),1
                ld hl,ROW_PAL
                add hl,de
                ld (hl),UNKNOWN
                ld a,b
                cp UNKNOWN
                jr z,.nextKind                  ; начало свободно
                bit 5,a
                jr nz,.nextKind                 ; выбор строки — начало снова свободно
                and 15
                ld (hl),a
                ld hl,ROW_OPEN
                add hl,de
                ld (hl),0
                ld a,b
                rrca
                rrca
                rrca
                rrca
                and 1
                ld hl,ROW_FLIP
                add hl,de
                ld (hl),a
.nextKind:      ld hl,STREAM_KIND
                inc (hl)
                ld a,(hl)
                cp 2
                jr c,.kind
                ld hl,STREAM_FAMILY
                inc (hl)
                ld a,(hl)
                cp 2
                jr c,.family
                ld a,VIDEO_STATE_PAGE
                jp Map1

; Индекс буфера строки: семья·2 + проход → DE. Портит AF.
RowIndex:       ld a,(STREAM_FAMILY)
                add a,a
                ld e,a
                ld a,(STREAM_KIND)
                add a,e
                ld e,a
                ld d,0
                ret

; PALETTE_SOURCE в буфер строки (семья STREAM_FAMILY, проход STREAM_KIND), если палитра A (набор·16 + палитра)
; другая; у открытой строки палитра первого слова — палитра начала строки, слова нет. Портит всё.
RowPalette:     and 15
                ld b,a
                call RowIndex
                ld hl,ROW_OPEN
                add hl,de
                ld a,(hl)
                ld hl,ROW_PAL
                add hl,de
                or a
                jr z,.known
                ld (hl),b
                ret
.known:         ld a,b
                cp (hl)
                ret z
                ld (hl),a
                add a,16                        ; таблица банка 1
                add a,a
                ld h,a
                ld l,0
                ld de,#2A00                     ; PALETTE_SOURCE (16 + палитра)·512
                jp RowWord

; Полоса из слотов маски A (бит 0 — слот 0, бит 1 — слот 1): ключ — набор·16 + палитра и слова
; слотов (пустой слот — 0); полоса из таблицы или новая со сборкой; слова — в буфер строки прохода,
; ссылка — в NEW_REFS. Портит всё.
StripFromSlots: ld (STRIP_MASK),a
                ld ix,SLOT_INFO
                rrca
                jr c,.first
                ld ix,SLOT_INFO+SLOT_SIZE
.first:         ld a,(ix+1)
                ld (KEY_SETPAL),a
                ld a,(ix+4)
                ld (STRIP_PASS),a
                ld a,(ix+5)
                ld (STRIP_FX),a
                ld hl,0
                ld a,(STRIP_MASK)
                rrca
                jr nc,.noSlot0
                ld hl,(SLOT_INFO+2)
.noSlot0:       ld (KEY_W0),hl
                ld hl,0
                ld a,(STRIP_MASK)
                and 2
                jr z,.noSlot1
                ld hl,(SLOT_INFO+SLOT_SIZE+2)
.noSlot1:       ld (KEY_W1),hl
                call StripFind
                jr c,.missing
                ld (STRIP_CURRENT),hl
                inc hl
                ld de,(NEW_REFS)
                ld a,d
                or e
                jr nz,.second
                ld (NEW_REFS),hl
                jr .words
.second:        ld (NEW_REFS+2),hl
.words:         ld a,(STRIP_PASS)
                ld (STREAM_KIND),a
                jp StripAppend
.missing:       ld hl,(VIDEO_MISSING)
                inc hl
                ld (VIDEO_MISSING),hl
                ld a,1
                ld (ROW_FAILED),a
                ; Полосы не хватило (все заняты показанным кадром): строка полос группы пересобирается в
                ; следующих кадрах без сверки с тенью, пока место не освободится, — иначе дыра оставалась
                ; до изменения тайлов.
                jp GroupRetry

; Слова полосы STRIP_CURRENT в буфер строки полос прохода STREAM_KIND: PALETTE_SOURCE при смене палитры,
; матрица при смене отражения по горизонтали, VERTEX2II (слот — STRIP_SLOT0 + номер полосы).
; Портит всё.
StripAppend:    xor a
                ld (STREAM_FAMILY),a
                ld a,(KEY_SETPAL)
                call RowPalette
                ld a,(STRIP_FX)
                call RowTransform
                ld a,(TILE_GROUP)
                add a,a
                add a,a
                add a,a
                ld hl,TILE_COLUMN
                add a,(hl)
                ld c,a
                ld b,0                          ; BC — столбец
                ld hl,COL_X3
                add hl,bc
                ld d,(hl)                       ; байт 3 = #80 | x >> 3
                ld hl,COL_X2
                add hl,bc
                ld a,(hl)                       ; (x & 7) << 5
                ld hl,TILE_ROW
                ld c,(hl)                       ; BC — строка полос
                ld hl,STRIP_Y2
                add hl,bc
                or (hl)
                ld e,a                          ; байт 2 = y >> 4 | (x & 7) << 5
                ld hl,STRIP_Y1
                add hl,bc
                ld a,(hl)                       ; (y & 15) << 4
                ld hl,(STRIP_CURRENT)
                or h
                ld h,a                          ; байт 1 = слот >> 8 | Y1
                jp RowPair

; Номер потока прохода STREAM_KIND текущих слоя, области, группы:
; ((слой·2 + проход)·3 + область)·8 + группа → A. Портит C.
StreamNumber:   ld a,(TILE_LAYER)
                add a,a
                ld c,a
                ld a,(STREAM_KIND)
                add a,c
                ld c,a
                add a,a
                add a,c
                ld c,a
                ld a,(TILE_REGION)
                add a,c
                add a,a
                add a,a
                add a,a
                ld c,a
                ld a,(TILE_GROUP)
                add a,c
                ret

; Заголовок потока семьи STREAM_FAMILY прохода STREAM_KIND → HL. Портит AF, C, DE.
StreamHeader:   call StreamNumber
; Заголовок потока семьи STREAM_FAMILY номер A → HL: #4000 + номер·HEADER_SIZE в странице состояния (полосы)
; или с IHEADER_OFFSET в странице картинок (окно W1). Портит AF, DE.
HeaderOf:       ld l,a
                ld h,0
                add hl,hl
                add hl,hl
                ld d,h
                ld e,l
                add hl,hl
                add hl,hl
                add hl,hl
                add hl,de                       ; номер·36
                ld de,#4000
                ld a,(STREAM_FAMILY)
                or a
                jr z,.base
                ld de,#4000+IHEADER_OFFSET
.base:          add hl,de
                ret
                ASSERT HEADER_SIZE == 36

; Матрица отражения в буфере строки (семья STREAM_FAMILY, проход STREAM_KIND): A — нужное отражение по
; горизонтали (0/1), ROW_FLIP — текущее; при смене — BITMAP_TRANSFORM_A и C семьи (TILE_TRANSFORMS или
; IMAGE_TRANSFORMS). У открытой строки (после RowPalette первого слова) отражение первого слова — отражение
; начала: слов нет, начало строки выбрано (ROW_START = #20 + отражение·16 + палитра). Портит всё.
RowTransform:   ld b,a
                call RowIndex
                ld hl,ROW_OPEN
                add hl,de
                ld a,(hl)
                or a
                jr z,.known
                ld (hl),0
                ld hl,ROW_FLIP
                add hl,de
                ld (hl),b
                ld a,b
                add a,a
                add a,a
                add a,a
                add a,a
                ld hl,ROW_PAL
                add hl,de
                or (hl)
                or #20
                ld hl,ROW_START
                add hl,de
                ld (hl),a
                ret
.known:         ld hl,ROW_FLIP
                add hl,de
                ld a,(hl)
                cp b
                ret z
                ld (hl),b
                call TransformTable
                ld a,b
                or a
                jr z,.words
                ld de,8
                add hl,de                       ; зеркальная пара слов
.words:         call .word
.word:          ld e,(hl)
                inc hl
                ld d,(hl)
                inc hl
                push de
                ld e,(hl)
                inc hl
                ld d,(hl)
                inc hl
                ex (sp),hl                      ; HL — младшее слово, в стеке — следующее слово таблицы
                call RowWord
                pop hl
                ret
; Пары слов матрицы семьи STREAM_FAMILY → HL. Портит AF.
TransformTable: ld hl,TILE_TRANSFORMS
                ld a,(STREAM_FAMILY)
                or a
                ret z
                ld hl,IMAGE_TRANSFORMS
                ret
; Буфер строки семьи STREAM_FAMILY прохода STREAM_KIND: HL → длина (ROW_LEN), BC — начало, D — размер. Портит AF,
; E.
RowSlot:        call RowIndex
                ld hl,ROW_LEN
                add hl,de
                ld a,(STREAM_FAMILY)
                or a
                jr nz,.image
                ld bc,ROW_BUFFER
                ld d,ROW_BUFFER_SIZE
                ld a,(STREAM_KIND)
                or a
                ret z
                ld bc,ROW_BUFFER+ROW_BUFFER_SIZE
                ret
.image:         ld bc,IROW_BUFFER
                ld d,IROW_BUFFER_SIZE
                ld a,(STREAM_KIND)
                or a
                ret z
                ld bc,IROW_BUFFER+IROW_BUFFER_SIZE
                ret
; Вершина прохода A (VERTEX2II DE:HL, handle 0 или 1) и следом вершина её прохода B — handle-псевдоним (handle + 2:
; байт 1 + 1, v30z80_video_assets.STRIP_HANDLE_B, IMAGE_HANDLE_B) — в буфер строки семьи STREAM_FAMILY прохода
; STREAM_KIND. Портит всё.
RowPair:        push hl
                push de
                call RowWord
                pop de
                pop hl
                inc h                           ; проход B: handle + 2
                ASSERT STRIP_HANDLE_B == STRIP_SLOT0/128+2 && IMAGE_HANDLE_B == IMAGE_SLOT0/128+2
; Слово DE:HL в буфер строки семьи STREAM_FAMILY прохода STREAM_KIND.
RowWord:        push hl
                push de
                call RowSlot
                ld a,(hl)
                cp d
                jr nc,.full
                add a,4
                ld (hl),a
                sub 4
                ld l,a
                ld h,0
                add hl,bc
                pop de
                pop bc
                ld (hl),c
                inc hl
                ld (hl),b
                inc hl
                ld (hl),e
                inc hl
                ld (hl),d
                ret
.full:          pop de
                pop hl
                ld hl,(VIDEO_OVERFLOW)
                inc hl
                ld (VIDEO_OVERFLOW),hl
                ret

; Буфер строки семьи STREAM_FAMILY прохода STREAM_KIND → поток: сдвиг хвоста, начала следующих строк,
; счётчики непустых потоков, состояние (отражение·16 + палитра) перед следующей строкой (CASCADE = 1 при его
; смене). Окно W1 — страница заголовков семьи (ставится здесь), W2 — страница потока. Портит всё.
StreamSplice:   ld a,(STREAM_FAMILY)
                or a
                ld a,VIDEO_STATE_PAGE
                jr z,.headerPage
                ld a,VIDEO_IMAGE_PAGE
.headerPage:    call Map1
                call StreamNumber
                ld (SPLICE_NUMBER),a
                call HeaderOf
                ld (SPLICE_HEADER),hl
                ld a,(TILE_REGION)
                ld e,a
                ld d,0
                ld hl,REGION_ROWS
                add hl,de
                ld a,(hl)
                ld (SPLICE_ROWS),a
                ld hl,(SPLICE_HEADER)
                ld a,(TILE_RR)
                ld e,a
                add hl,de
                add hl,de
                ld e,(hl)
                inc hl
                ld d,(hl)
                inc hl
                ld (SPLICE_START),de
                ld e,(hl)
                inc hl
                ld d,(hl)
                ld (SPLICE_END),de
                ld hl,(SPLICE_HEADER)
                ld a,(SPLICE_ROWS)
                ld e,a
                ld d,0
                add hl,de
                add hl,de
                ld e,(hl)
                inc hl
                ld d,(hl)
                ld (SPLICE_USED),de
                call RowIndex
                ld hl,ROW_LEN
                add hl,de
                ld a,(hl)
                ld (SPLICE_NEW),a
                ; разность = новая − старая
                ld hl,(SPLICE_END)
                ld de,(SPLICE_START)
                or a
                sbc hl,de
                ex de,hl
                ld l,a
                ld h,0
                or a
                sbc hl,de
                ld (SPLICE_DELTA),hl
                ld de,(SPLICE_USED)
                add hl,de
                ld de,STREAM_CAPACITY+1
                ld a,(STREAM_FAMILY)
                or a
                jr z,.capacity
                ld de,ISTREAM_CAPACITY+1
.capacity:      or a
                sbc hl,de
                jr c,.fits
                ld hl,(VIDEO_OVERFLOW)
                inc hl
                ld (VIDEO_OVERFLOW),hl
                ret
.fits:          call CacheInvalidate            ; копии подпрограмм, которые видят эту строку, — не годны
                ; поток пуст → непуст или обратно: счётчик LAYER_STREAMS и маска групп REGION_GROUPS
                ld hl,(SPLICE_USED)
                ld a,h
                or l
                ld b,a
                ld de,(SPLICE_DELTA)
                add hl,de
                ld c,0
                ld a,b
                or a
                jr nz,.wasUsed
                ld a,h
                or l
                jr z,.counted
                inc c
                jr .count
.wasUsed:       ld a,h
                or l
                jr nz,.counted
                dec c
.count:         ld a,(TILE_LAYER)
                add a,a
                ld b,a
                ld a,(STREAM_KIND)
                add a,b
                ld e,a
                ld d,0                          ; DE — слой-проход
                ld hl,LAYER_STREAMS
                ld a,(STREAM_FAMILY)
                or a
                jr z,.layerStreams
                ld hl,LAYER_STREAMS+4
.layerStreams:  add hl,de
                ld a,(hl)
                add a,c
                ld (hl),a
                ld a,e
                add a,a
                add a,e                         ; слой-проход·3
                ld hl,TILE_REGION
                add a,(hl)
                ld e,a
                ld hl,REGION_GROUPS
                ld a,(STREAM_FAMILY)
                or a
                jr z,.regionGroups
                ld hl,REGION_GROUPS+12
.regionGroups:  add hl,de                       ; маска групп (семья, слой-проход, область)
                ld a,(TILE_GROUP)
                ld b,a
                inc b
                ld a,#80
.bit:           rlca
                djnz .bit                       ; бит группы
                bit 7,c
                jr nz,.clear
                or (hl)
                ld (hl),a
                jr .counted
.clear:         cpl
                and (hl)
                ld (hl),a
.counted:       ; страница и начало потока
                ld a,(SPLICE_NUMBER)
                ld l,a
                ld h,0
                ld d,h
                ld e,l
                add hl,hl
                add hl,de
                ld de,STREAM_LOC
                ld a,(STREAM_FAMILY)
                or a
                jr z,.location
                ld de,ISTREAM_LOC
.location:      add hl,de
                ld a,(hl)
                inc hl
                ld e,(hl)
                inc hl
                ld d,(hl)
                ld hl,#8000
                add hl,de
                ld (SPLICE_BASE),hl
                call Map2
                ld hl,(SPLICE_DELTA)
                ld a,h
                or l
                jr z,.copy
                ld hl,(SPLICE_USED)
                ld de,(SPLICE_END)
                or a
                sbc hl,de
                ld b,h
                ld c,l                          ; длина хвоста
                ld a,b
                or c
                jr z,.moved
                ld a,(SPLICE_DELTA+1)
                rlca
                jr c,.down
                ld hl,(SPLICE_USED)
                dec hl
                ld de,(SPLICE_BASE)
                add hl,de                       ; последний байт хвоста
                push hl
                ld de,(SPLICE_DELTA)
                add hl,de
                ex de,hl
                pop hl
                lddr
                jr .moved
.down:          ld hl,(SPLICE_END)
                ld de,(SPLICE_BASE)
                add hl,de
                push hl
                ld de,(SPLICE_DELTA)
                add hl,de
                ex de,hl
                pop hl
                ldir
.moved:         ld a,(TILE_RR)
                ld b,a
                ld a,(SPLICE_ROWS)
                sub b                           ; строк rr+1 … R включительно
                ld b,a
                ld hl,(SPLICE_HEADER)
                ld a,(TILE_RR)
                inc a
                ld e,a
                ld d,0
                add hl,de
                add hl,de
.adjust:        ld e,(hl)
                inc hl
                ld d,(hl)
                push hl
                ld hl,(SPLICE_DELTA)
                add hl,de
                ex de,hl
                pop hl
                ld (hl),d
                dec hl
                ld (hl),e
                inc hl
                inc hl
                djnz .adjust
.copy:          ld a,(SPLICE_NEW)
                or a
                jr z,.palette
                ld a,VIDEO_TILE_PAGE
                call Map1                       ; буфер строки — в странице тайлов
                call RowSlot
                ld a,(SPLICE_NEW)
                ld hl,(SPLICE_START)
                ld de,(SPLICE_BASE)
                add hl,de
                ex de,hl
                ld h,b
                ld l,c
                ld c,a
                ld b,0
                ldir
                ld a,(STREAM_FAMILY)
                or a
                ld a,VIDEO_STATE_PAGE
                jr z,.headerBack
                ld a,VIDEO_IMAGE_PAGE
.headerBack:    call Map1                       ; снова заголовки семьи
.palette:       ; выбранное начало строки — в заголовок этой строки (строки перед ней пусты: CASCADE не нужен)
                ld hl,(SPLICE_HEADER)
                ld de,HEADER_PAL
                add hl,de
                ld a,(TILE_RR)
                ld e,a
                ld d,0
                add hl,de
                ld (SPLICE_STATE),hl            ; состояние перед строкой; следующий байт — после неё
                call RowIndex
                ld hl,ROW_START
                add hl,de
                ld a,(hl)
                cp UNKNOWN
                jr z,.startKept
                ld hl,(SPLICE_STATE)
                ld (hl),a
.startKept:     ld hl,ROW_OPEN
                add hl,de
                ld a,(hl)
                or a
                jr z,.endState
                ; пустая открытая строка: состояние после неё свободно — известное начало следующей строки
                ; становится выбором (слова той строки прежние), без CASCADE
                ld hl,(SPLICE_STATE)
                inc hl
                ld a,(hl)
                cp UNKNOWN
                ret z
                or #20
                ld (hl),a
                ret
.endState:      ; состояние в конце строки: отражение·16 + палитра
                ld hl,ROW_FLIP
                add hl,de
                ld a,(hl)
                add a,a
                add a,a
                add a,a
                add a,a
                ld hl,ROW_PAL
                add hl,de
                or (hl)
                ld b,a
                ld hl,(SPLICE_STATE)
                inc hl
                ld a,(hl)
                cp b
                ret z
                ld (hl),b                       ; пустые строки дальше переносят его только перестройкой
                ld a,1
                ld (CASCADE),a
                ret

; --- таблица полос --------------------------------------------------------------------------------------------
; Корзина ключа KEY_* (W1 — страница тайлов) → HL — адрес слова корзины. Портит AF, DE.
KeyHash:        ld hl,(KEY_W1)
                ld d,h
                ld e,l
                add hl,hl
                add hl,de                       ; W1·3
                ld de,(KEY_W0)
                add hl,de
                ld a,d
                rlca
                rlca
                rlca
                add a,l
                ld l,a                          ; перемешать старший байт W0
                ld a,(KEY_SETPAL)
                ld e,a
                ld d,0
                add hl,de
                add hl,de
                add hl,de
                add hl,de
                add hl,de                       ; + набор·16 + палитра, умноженные на 5
                ld a,h
                and high BUCKET_MASK
                ld h,a
                add hl,hl
                ld de,#4000+STRIP_BUCKETS
                add hl,de
                ret

; HL — номер полосы → HL — её запись (W1). Портит DE.
StripAddress:   ld d,h
                ld e,l
                add hl,hl
                add hl,de
                add hl,hl
                add hl,hl                       ; ·12
                ld de,#4000
                add hl,de
                ret
                ASSERT STRIP_ENTRY == 12

; Полоса с ключом KEY_*: поиск в цепочке корзины; нет — новая полоса (StripAlloc), сборка
; (StripCompose) и включение в корзину. Выход: HL — номер, CF = 0; CF = 1 — полос нет. Портит всё.
StripFind:      call KeyHash
                ld (BUCKET_PTR),hl
                ld e,(hl)
                inc hl
                ld d,(hl)                       ; первая в корзине (номер + 1)
.chain:         ld a,d
                or e
                jr z,.new
                dec de
                push de                         ; номер
                ex de,hl
                call StripAddress
                push hl                         ; запись
                ld de,KEY_SETPAL
                ld b,5
.compare:       ld a,(de)
                cp (hl)
                jr nz,.differ
                inc hl
                inc de
                djnz .compare
                pop hl
                pop hl                          ; номер найденной
                or a
                ret
.differ:        pop hl
                ld de,5
                add hl,de
                ld e,(hl)
                inc hl
                ld d,(hl)                       ; следующая в корзине
                pop af                          ; снять номер
                jr .chain
.new:           call StripAlloc
                ret c
                push hl
                call StripAddress
                ex de,hl
                ld hl,KEY_SETPAL
                ld bc,5
                ldir                            ; ключ
                ld hl,(BUCKET_PTR)
                ld a,(hl)
                ld (de),a
                inc hl
                inc de
                ld a,(hl)
                ld (de),a                       ; следующая — прежняя первая в корзине
                pop de
                push de
                inc de
                ld (hl),d
                dec hl
                ld (hl),e                       ; первая в корзине — новая (номер + 1)
                pop hl
                push hl
                call StripCompose
                pop hl
                or a
                ret

; Свободная полоса: по кругу от STRIP_HAND — не занятая либо без ссылок позиций, отпущенная видимой
; позицией не позже прошлого кадра (отпущенную в прошлом кадре — после показа прошлого списка,
; SWAP_PENDING/FadeWaitSwap; её не видят ни показанный, ни собираемый display list) и не взятая первым слотом
; собираемого столбца (NEW_REFS: ссылки столбца прибавляются после обоих слотов, VDAC2+ 2026-09-27);
; вытесняемая удаляется из корзины. Выход: HL — номер, CF = 0; CF = 1 — нет. Портит всё.
StripAlloc:     ld hl,STRIPS
                ld (ALLOC_TRIES),hl
.try:           ld hl,(STRIP_HAND)
                ld (ALLOC_PAIR),hl
                inc hl
                ld de,STRIPS
                or a
                sbc hl,de
                add hl,de
                jr c,.hand
                ld hl,0
.hand:          ld (STRIP_HAND),hl
                ld hl,(ALLOC_PAIR)
                call StripAddress
                ld (ALLOC_OWNER),hl
                ld de,10
                add hl,de
                ld a,(hl)
                or a
                jr z,.take                      ; не занята
                dec hl
                dec hl
                dec hl                          ; +7 — число ссылок
                ld a,(hl)
                inc hl
                or (hl)
                jr nz,.busy
                call StripColumnTaken           ; взята первым слотом этого столбца — её ссылка ещё не прибавлена
                jr z,.busy
                inc hl                          ; +9 — кадр освобождения
                ld a,(VIDEO_FRAME)
                sub (hl)
                jr z,.busy                      ; отпущена в этом кадре
                dec a
                jr nz,.evict                    ; два кадра и раньше: её не выводит ни один список
                ld a,(SWAP_PENDING)             ; в прошлом кадре: прошлый список должен быть уже показан
                or a
                call nz,FadeWaitSwap
.evict:         call StripUnlink
                jr .take
.busy:          ld hl,(ALLOC_TRIES)
                dec hl
                ld (ALLOC_TRIES),hl
                ld a,h
                or l
                jr nz,.try
                scf
                ret
.take:          ld hl,(ALLOC_OWNER)
                ld de,7
                add hl,de
                xor a
                ld (hl),a
                inc hl
                ld (hl),a                       ; ссылок нет
                inc hl
                ld a,(VIDEO_FRAME)
                ld (hl),a                       ; без ссылок новая полоса два кадра не вытесняется
                inc hl
                ld (hl),1                       ; занята
                ld hl,(ALLOC_PAIR)
                or a
                ret

; Полоса ALLOC_PAIR (запись ALLOC_OWNER) — из цепочки своей корзины. Портит всё.
StripUnlink:    ld hl,KEY_SETPAL
                ld de,KEY_SAVE
                ld bc,5
                ldir
                ld hl,(ALLOC_OWNER)
                ld de,KEY_SETPAL
                ld bc,5
                ldir
                call KeyHash                    ; HL — корзина вытесняемой
                ld de,(ALLOC_PAIR)
                inc de                          ; её ссылка (номер + 1)
.walk:          ld c,(hl)
                inc hl
                ld b,(hl)
                dec hl                          ; HL — поле ссылки, BC — ссылка
                ld a,b
                or c
                jr z,.restore
                ld a,c
                cp e
                jr nz,.next
                ld a,b
                cp d
                jr nz,.next
                push hl
                ld hl,(ALLOC_OWNER)
                ld bc,5
                add hl,bc
                ld c,(hl)
                inc hl
                ld b,(hl)                       ; следующая за вытесняемой
                pop hl
                ld (hl),c
                inc hl
                ld (hl),b
                jr .restore
.next:          push de
                dec bc
                ld h,b
                ld l,c
                call StripAddress
                ld de,5
                add hl,de                       ; поле «следующая» полосы цепочки
                pop de
                jr .walk
.restore:       ld hl,KEY_SAVE
                ld de,KEY_SETPAL
                ld bc,5
                ldir
                ret

; --- сборка полосы в RAM_G -----------------------------------------------------------------------------------
; Полоса HL с ключом KEY_*: CMD_MEMSET нулями, затем для слота с тайлом — ячейка (CellEnsure) и
; CMD_MEMCPY проходов A и B в строки слота (отражение по вертикали — 15 строк в обратном порядке).
; Команды каждого слота встают в очередь сопроцессора сразу после загрузки его ячейки: следующая
; загрузка в ту же ячейку исполнится позже копирования. Портит всё.
StripCompose:   call StripRamAddress
                ld (STRIP_ADDRESS),de
                ld (STRIP_ADDRESS+2),a
                ld hl,16
                call CmdRoom
                call CmdOpen
                ld hl,#FF1B
                ld de,#FFFF
                call EmitRaw                    ; CMD_MEMSET
                ld hl,STRIP_ADDRESS
                call Out24
                ld hl,0
                ld de,0
                call EmitRaw                    ; значение 0
                ld hl,STRIP_BYTES
                ld de,0
                call EmitRaw
                call FtClose
                ld a,1
                ld (VIDEO_UPLOADED),a
                xor a
                ld (COMPOSE_SLOT),a
.slot:          ld a,(COMPOSE_SLOT)
                or a
                ld hl,(KEY_W0)
                jr z,.word
                ld hl,(KEY_W1)
.word:          bit 7,h
                jp z,.nextSlot                  ; слот пуст
                ld (COMPOSE_WORD),hl
                ld a,h
                and #0F
                ld h,a
                ld a,(KEY_SETPAL)
                call CellEnsure
                jp z,.nextSlot
                ld a,d
                and #0F
                ld h,a
                ld l,e                          ; номер ячейки тайла
                call TileCellAddress
                ld (COPY_SOURCE),de
                ld (COPY_SOURCE+2),a
                ld hl,(STRIP_ADDRESS)
                ld (COPY_DEST),hl
                ld a,(STRIP_ADDRESS+2)
                ld (COPY_DEST+2),a
                ld a,(COMPOSE_SLOT)
                or a
                jr z,.dest
                ld bc,TILE_CELL_BYTES/2
                call AddDest                    ; слот 1 — строки 15…29 прохода
.dest:          ld a,(COMPOSE_WORD+1)
                bit 6,a
                jr nz,.flipped
                ld hl,32
                call CmdRoom
                call CmdOpen
                ld bc,TILE_CELL_BYTES/2
                call CopyCommand                ; проход A
                ld bc,TILE_CELL_BYTES
                call AddDest
                ld bc,TILE_CELL_BYTES/2
                call AddSource
                ld bc,TILE_CELL_BYTES/2
                call CopyCommand                ; проход B
                call FtClose
                jr .nextSlot
.flipped:       ld hl,480
                call CmdRoom
                call CmdOpen
                ld bc,TILE_CELL_W*(TILE_CELL_H-1)
                call AddDest                    ; приёмник — последняя строка слота
                ld b,2
.pass:          push bc
                ld b,TILE_CELL_H
.row:           push bc
                ld bc,TILE_CELL_W
                call CopyCommand
                ld bc,TILE_CELL_W
                call AddSource
                ld bc,-TILE_CELL_W
                call AddDest
                pop bc
                djnz .row
                ld bc,TILE_CELL_BYTES+TILE_CELL_W*TILE_CELL_H
                call AddDest                    ; от строки −1 прохода A к последней строке слота прохода B
                pop bc
                djnz .pass
                call FtClose
.nextSlot:      ld hl,COMPOSE_SLOT
                inc (hl)
                ld a,(hl)
                cp 2
                jp c,.slot
                ld hl,(VIDEO_STRIPS)
                inc hl
                ld (VIDEO_STRIPS),hl
                ret

; --- таблица картинок -----------------------------------------------------------------------------------------
; Корзина ключа IMAGE_KEY (W1 — страница тайлов) → HL — адрес слова корзины: h = rlc(h) xor байт по байтам ключа,
; корзина — h & IBUCKET_MASK. Портит AF, B, DE.
ImageHash:      ld hl,IMAGE_KEY
                ld b,IMAGE_KEY_SIZE
                xor a
.byte:          rlca
                xor (hl)
                inc hl
                djnz .byte
                and IBUCKET_MASK
                ld l,a
                ld h,0
                add hl,hl
                ld de,#4000+IMAGE_BUCKETS
                add hl,de
                ret

; ImageAddress (номер картинки → запись) — в резиденте (v30z80_runtime.asm): страница хоста заполнена.

; Картинка с ключом IMAGE_KEY: поиск в цепочке корзины; нет — новая картинка (ImageAlloc), сборка
; (ImageCompose) и включение в корзину. Выход: HL — номер, CF = 0; CF = 1 — картинок нет. Портит всё.
ImageFind:      call ImageHash
                ld (BUCKET_PTR),hl
                ld e,(hl)
                inc hl
                ld d,(hl)                       ; первая в корзине (номер + 1)
.chain:         ld a,d
                or e
                jr z,.new
                dec de
                push de                         ; номер
                ex de,hl
                call ImageAddress
                push hl                         ; запись
                ld de,IMAGE_KEY
                ld b,IMAGE_KEY_SIZE
.compare:       ld a,(de)
                cp (hl)
                jr nz,.differ
                inc hl
                inc de
                djnz .compare
                pop hl
                pop hl                          ; номер найденной
                or a
                ret
.differ:        pop hl
                ld de,IMAGE_KEY_SIZE
                add hl,de
                ld e,(hl)
                inc hl
                ld d,(hl)                       ; следующая в корзине
                pop af                          ; снять номер
                jr .chain
.new:           call ImageAlloc
                ret c
                push hl
                call ImageAddress
                ex de,hl
                ld hl,IMAGE_KEY
                ld bc,IMAGE_KEY_SIZE
                ldir                            ; ключ
                ld hl,(BUCKET_PTR)
                ld a,(hl)
                ld (de),a
                inc hl
                inc de
                ld a,(hl)
                ld (de),a                       ; следующая — прежняя первая в корзине
                pop de
                push de
                inc de
                ld (hl),d
                dec hl
                ld (hl),e                       ; первая в корзине — новая (номер + 1)
                pop hl
                push hl
                call ImageCompose
                pop hl
                or a
                ret

; Предел пула картинок → HL: два кадра после сброса видео — GUARD_IMAGES (выше — изображения показанного титула), с
; кольцом фона — RING_IMAGES (выше — кольцо и его палитра, rtype_ring.py), иначе IMAGES. Портит AF.
ImageLimit:     ld hl,GUARD_IMAGES
                ld a,(TITLE_GUARD)
                or a
                ret nz
                ld hl,RING_IMAGES
                ld a,(RING_ON)
                or a
                ret nz
                ld hl,IMAGES
                ret

; Свободная картинка: по кругу от IMAGE_HAND — не занятая либо без ссылок строк групп, отпущенная видимой
; строкой не позже прошлого кадра (как StripAlloc) и не взятая классом собираемой строки (NEW_IREFS: ссылки строки
; прибавляются после всех её классов, VDAC2+ 2026-09-27); вытесняемая удаляется из корзины. Круг — до предела
; ImageLimit (титул ещё показан, кольцо фона). Выход: HL — номер, CF = 0; CF = 1 — нет.
; Портит всё.
ImageAlloc:     call ImageLimit
                ld (ALLOC_TRIES),hl
.try:           call ImageLimit
                ex de,hl                        ; DE — предел
                ld hl,(IMAGE_HAND)
                ld (ALLOC_PAIR),hl
                inc hl
                or a
                sbc hl,de
                add hl,de
                jr c,.hand
                ld hl,0
.hand:          ld (IMAGE_HAND),hl
                ld hl,(ALLOC_PAIR)
                call ImageAddress
                ld (ALLOC_OWNER),hl
                ld de,IMAGE_KEY_SIZE+5
                add hl,de
                ld a,(hl)
                or a
                jr z,.take                      ; не занята
                dec hl
                dec hl
                dec hl                          ; +36 — число ссылок
                ld a,(hl)
                inc hl
                or (hl)
                jr nz,.busy
                call ImageRowTaken              ; взята классом этой строки — её ссылка ещё не прибавлена
                jr z,.busy
                inc hl                          ; +38 — кадр освобождения
                ld a,(VIDEO_FRAME)
                sub (hl)
                jr z,.busy                      ; отпущена в этом кадре
                dec a
                jr nz,.evict                    ; два кадра и раньше: её не выводит ни один список
                ld a,(SWAP_PENDING)             ; в прошлом кадре: прошлый список должен быть уже показан
                or a
                call nz,FadeWaitSwap
.evict:         call ImageUnlink
                jr .take
.busy:          ld hl,(ALLOC_TRIES)
                dec hl
                ld (ALLOC_TRIES),hl
                ld a,h
                or l
                jr nz,.try
                ld hl,IMG_FAILS                 ; VDAC2+: отказ пула — ранняя сборка строк его сверяет
                inc (hl)
                scf
                ret
.take:          ld hl,(ALLOC_OWNER)
                ld de,IMAGE_KEY_SIZE+2
                add hl,de
                xor a
                ld (hl),a
                inc hl
                ld (hl),a                       ; ссылок нет
                inc hl
                ld a,(VIDEO_FRAME)
                ld (hl),a                       ; без ссылок новая картинка два кадра не вытесняется
                inc hl
                ld (hl),1                       ; занята
                ld hl,(ALLOC_PAIR)
                or a
                ret

; Картинка ALLOC_PAIR (запись ALLOC_OWNER) — из цепочки своей корзины. Портит всё.
ImageUnlink:    ld hl,IMAGE_KEY
                ld de,IMAGE_KEY_SAVE
                ld bc,IMAGE_KEY_SIZE
                ldir
                ld hl,(ALLOC_OWNER)
                ld de,IMAGE_KEY
                ld bc,IMAGE_KEY_SIZE
                ldir
                call ImageHash                  ; HL — корзина вытесняемой
                ld de,(ALLOC_PAIR)
                inc de                          ; её ссылка (номер + 1)
.walk:          ld c,(hl)
                inc hl
                ld b,(hl)
                dec hl                          ; HL — поле ссылки, BC — ссылка
                ld a,b
                or c
                jr z,.restore
                ld a,c
                cp e
                jr nz,.next
                ld a,b
                cp d
                jr nz,.next
                push hl
                ld hl,(ALLOC_OWNER)
                ld bc,IMAGE_KEY_SIZE
                add hl,bc
                ld c,(hl)
                inc hl
                ld b,(hl)                       ; следующая за вытесняемой
                pop hl
                ld (hl),c
                inc hl
                ld (hl),b
                jr .restore
.next:          push de
                dec bc
                ld h,b
                ld l,c
                call ImageAddress
                ld de,IMAGE_KEY_SIZE
                add hl,de                       ; поле «следующая» картинки цепочки
                pop de
                jr .walk
.restore:       ld hl,IMAGE_KEY_SAVE
                ld de,IMAGE_KEY
                ld bc,IMAGE_KEY_SIZE
                ldir
                ret

; --- сборка картинки в RAM_G ---------------------------------------------------------------------------------
; Картинка HL с ключом IMAGE_KEY: CMD_MEMSET нулями картинки сборки (IMAGE_STAGE); для слота класса (слова
; ключа по возрастанию слотов — столбец правее ложится поверх нахлёста) — ячейка тайла (CellEnsure), CMD_MEMCPY
; ячейки в ячейку сборки слота и готовый блок из 30 CMD_MEMCPY её строк в картинку сборки (страница шаблонов
; VIDEO_TEMPLATE_PAGE0 + fx ключа, блок (fy·16 + слот)·IMAGE_TEMPLATE — v30z80_video_assets.image_templates) — DMA
; в открытую запись очереди сопроцессора; затем CMD_MEMCPY картинки сборки на место картинки. Команды слота
; встают в очередь сразу после загрузки его ячейки: следующая загрузка в ту же ячейку исполнится позже. Портит всё.
ImageCompose:   ld d,h
                ld e,l
                add hl,hl
                add hl,de
                ld de,IMAGE_ADDRESSES
                add hl,de
                ld de,IMAGE_TARGET
                ld bc,3
                ldir                            ; адрес картинки в RAM_G
                ld hl,16
                call CmdRoom
                call CmdOpen
                ld hl,#FF1B
                ld de,#FFFF
                call EmitRaw                    ; CMD_MEMSET картинки сборки
                ld hl,IMAGE_STAGE & #FFFF
                ld de,IMAGE_STAGE >> 16
                call EmitRaw
                ld hl,0
                ld de,0
                call EmitRaw                    ; значение 0
                ld hl,IMAGE_BYTES
                ld de,0
                call EmitRaw
                call FtClose
                ld a,1
                ld (VIDEO_UPLOADED),a
                xor a
                ld (COMPOSE_SLOT),a
.slot:          ld a,(COMPOSE_SLOT)
                add a,a
                ld e,a
                ld d,0
                ld hl,IMAGE_KEY+2
                add hl,de
                ld e,(hl)
                inc hl
                ld d,(hl)
                bit 7,d
                jp z,.next                      ; слот не из класса
                ld (COMPOSE_WORD),de
                ex de,hl
                ld a,h
                and #0F
                ld h,a
                ld a,(IMAGE_KEY)
                call CellEnsure
                jp z,.next
                ld a,d
                and #0F
                ld h,a
                ld l,e                          ; номер ячейки тайла
                ld d,h
                ld e,l
                add hl,hl
                add hl,de
                ld de,CELL_ADDRESSES
                add hl,de
                ld de,COPY_SOURCE
                ld bc,3
                ldir
                ld a,(COMPOSE_SLOT)
                ld l,a
                ld h,0
                ld d,h
                ld e,l
                add hl,hl
                add hl,de
                ld de,STAGE_CELL_ADDRESSES
                add hl,de
                ld de,COPY_DEST
                ld bc,3
                ldir
                ld hl,16+IMAGE_TEMPLATE
                call CmdRoom
                call CmdOpen
                ld bc,TILE_CELL_BYTES
                call CopyCommand                ; ячейка → ячейка сборки слота
                ld a,(COMPOSE_WORD+1)
                and #40                         ; fy
                rrca
                rrca
                ld hl,COMPOSE_SLOT
                add a,(hl)                      ; fy·16 + слот
                add a,a
                ld l,a
                ld h,0
                ld de,TEMPLATE_OFFSETS
                add hl,de
                ld a,(hl)
                inc hl
                ld h,(hl)
                ld l,a
                ld a,(IMAGE_KEY+1)
                add a,VIDEO_TEMPLATE_PAGE0
                ld bc,IMAGE_TEMPLATE
                call DmaToSpi                   ; строки слота → картинка сборки
                call FtClose
.next:          ld hl,COMPOSE_SLOT
                inc (hl)
                ld a,(hl)
                cp 16
                jp c,.slot
                ld hl,IMAGE_TARGET
                ld de,COPY_DEST
                ld bc,3
                ldir
                ld hl,IMAGE_STAGE & #FFFF
                ld (COPY_SOURCE),hl
                ld a,IMAGE_STAGE >> 16
                ld (COPY_SOURCE+2),a
                ld hl,16
                call CmdRoom
                call CmdOpen
                ld bc,IMAGE_BYTES
                call CopyCommand                ; картинка сборки → место картинки
                call FtClose
                ld hl,(VIDEO_IMAGES)
                inc hl
                ld (VIDEO_IMAGES),hl
                ret
                ASSERT TILE_CELL_BYTES == 420 && IMAGE_TEMPLATE*32 <= #4000

; Ждать места HL байт в очереди сопроцессора (не дольше WAIT_TRIES опросов). Портит всё.
CmdRoom:        ld (ROOM_NEED),hl
                ld hl,WAIT_TRIES
                ld (WAIT_LEFT),hl
.check:         call CmdSpace
                ld de,(ROOM_NEED)
                or a
                sbc hl,de
                ret nc
                call WaitTick
                jr nz,.check
                ret
; Открыть запись в REG_CMDB_WRITE. Портит AF, C, DE.
CmdOpen:        ld a,#30
                ld de,#2578
                jp FtOpenWrite
; CMD_MEMCPY COPY_DEST ← COPY_SOURCE, BC байт в открытую запись очереди. Портит AF, DE, HL.
CopyCommand:    push bc
                ld hl,#FF1D
                ld de,#FFFF
                call EmitRaw
                ld hl,COPY_DEST
                call Out24
                ld hl,COPY_SOURCE
                call Out24
                pop bc
                ld h,b
                ld l,c
                ld de,0
                jp EmitRaw
; Три байта с (HL) и нулевой старший — в SPI. Портит AF, HL.
Out24:          ld a,(hl)
                out (SPI_DATA),a
                inc hl
                ld a,(hl)
                out (SPI_DATA),a
                inc hl
                ld a,(hl)
                out (SPI_DATA),a
                xor a
                out (SPI_DATA),a
                ret
; COPY_DEST += BC (со знаком). Портит AF, E, HL.
AddDest:        ld hl,(COPY_DEST)
                add hl,bc
                ld (COPY_DEST),hl
                ld a,(COPY_DEST+2)
                ld e,0
                bit 7,b
                jr z,.positive
                dec e
.positive:      adc a,e
                ld (COPY_DEST+2),a
                ret
; COPY_SOURCE += BC (BC < #8000). Портит AF, HL.
AddSource:      ld hl,(COPY_SOURCE)
                add hl,bc
                ld (COPY_SOURCE),hl
                ld a,(COPY_SOURCE+2)
                adc a,0
                ld (COPY_SOURCE+2),a
                ret

; Адреса в RAM_G: A:DE = база пула + номер·размер — сдвигами и сложениями под размеры видеоадаптера (прежде общее
; умножение по битам с переменными в памяти стоило ≈2 тыс. тактов на адрес). Портят F, BC, HL.
                ASSERT TILE_CELL_BYTES == 420 && STRIP_BYTES == 840 && SPRITE_CELL_BYTES == 1620
                ASSERT CELLS <= 96 && STRIPS <= 105 && SPRITE_CELLS <= 256
; HL (< 624) → HL·105. Портит DE.
Mul105:         ld d,h
                ld e,l                          ; DE = n
                add hl,hl
                add hl,hl
                add hl,hl                       ; 8n
                push hl
                add hl,hl
                add hl,hl                       ; 32n
                ex (sp),hl                      ; HL = 8n, на стеке 32n
                add hl,de                       ; 9n
                pop de
                add hl,de
                add hl,de
                add hl,de                       ; 9n + 3·32n = 105n
                ret
; HL — ячейка тайла (< 96) → A:DE = CELL_BASE + ячейка·420.
TileCellAddress:
                call Mul105
                add hl,hl
                add hl,hl                       ; 420n < 40320
                ld de,CELL_BASE & #FFFF
                add hl,de
                ld a,CELL_BASE >> 16
                adc a,0
                ex de,hl
                ret
; HL — полоса (< 105) → A:DE = STRIP_BASE + полоса·840 (адрес её строк в RAM_G; не путать с записью StripAddress).
StripRamAddress:
                call Mul105
                add hl,hl
                add hl,hl                       ; 420n < 44100
                xor a
                add hl,hl
                adc a,a                         ; A:HL = 840n
                ld de,STRIP_BASE & #FFFF
                add hl,de
                adc a,STRIP_BASE >> 16
                ex de,hl
                ret
; HL — ячейка спрайта (< 256) → A:DE = SPRITE_BASE + ячейка·1620.
SpriteCellAddress:
                ld d,h
                ld e,l                          ; DE = n
                add hl,hl
                add hl,hl
                add hl,hl
                add hl,hl                       ; 16n
                push hl
                add hl,hl
                add hl,hl                       ; 64n
                pop bc
                add hl,bc
                add hl,de                       ; 81n < 20655
                xor a
                add hl,hl
                adc a,a                         ; A:HL = 162n
                add hl,hl
                adc a,a                         ; 324n
                ld d,h
                ld e,l
                ld b,a                          ; B:DE = 324n
                add hl,hl
                adc a,a                         ; 648n
                add hl,hl
                adc a,a                         ; 1296n
                add hl,de
                adc a,b                         ; 1620n
                ld de,SPRITE_BASE & #FFFF
                add hl,de
                adc a,SPRITE_BASE >> 16
                ex de,hl
                ret

; --- ссылки позиций ---------------------------------------------------------------------------------------------
; Позиция (TILE_LAYER, строка полос TILE_ROW, столбец TILE_GROUP·8 + TILE_COLUMN): прежние ссылки на
; полосы (номер + 1, два слова) заменяются NEW_REFS; число ссылок новых полос +1, прежних −1 (позиция,
; видимая в одном из двух последних display list, — кадр освобождения; POS_VISIBLE строки группы считает
; StripRowRebuild). W1 — страница тайлов, W2 — страница позиций. Портит всё.
PositionUpdate: ld a,VIDEO_POSITION_PAGE
                call Map2
                ld a,(TILE_LAYER)
                add a,a
                add a,a
                add a,a
                add a,a
                add a,a                         ; слой·#20
                ld hl,TILE_ROW
                add a,(hl)
                add a,#80
                ld h,a
                ld a,(TILE_GROUP)
                add a,a
                add a,a
                add a,a
                ld l,a
                ld a,(TILE_COLUMN)
                add a,l
                add a,a
                add a,a
                ld l,a                          ; столбец·4
                push hl
                ld de,OLD_REFS
                ld bc,4                         ; четыре LDI — 64 такта против 79 у LDIR; BC так же обнуляется
                ldi
                ldi
                ldi
                ldi
                pop de
                push de
                ld hl,NEW_REFS
                ld bc,4
                ldi
                ldi
                ldi
                ldi
                ; запись отката строки: адрес позиции, прежние и новые ссылки
                ld a,(UNDO_COUNT)
                ld l,a
                inc a
                ld (UNDO_COUNT),a
                ld h,0
                ld d,h
                ld e,l
                add hl,hl
                add hl,hl
                add hl,de
                add hl,hl                       ; ·10
                ld de,UNDO_LOG
                add hl,de
                ex de,hl
                pop hl
                ld a,l
                ld (de),a
                inc de
                ld a,h
                ld (de),a
                inc de
                ld hl,NEW_REFS
                ld bc,8
                ldir                            ; NEW_REFS и OLD_REFS подряд
                ASSERT OLD_REFS == NEW_REFS+4
                ld hl,(NEW_REFS)
                call RefAdd
                ld hl,(NEW_REFS+2)
                call RefAdd
                ld hl,(OLD_REFS)
                call RefSub
                ld hl,(OLD_REFS+2)
; Число ссылок полосы HL − 1 (номер + 1; 0 — нет). Ссылку снимает позиция, видимая в показанном или
; предыдущем display list (POS_VISIBLE), — кадр освобождения: такую полосу этот список ещё выводит, и два
; кадра её нельзя переписать. Полоса, которую держали только невидимые позиции, без ссылок вытесняется
; сразу (на смене сцены иначе не хватало полос: старые под защитой, новые уже нужны). Портит AF, DE, HL.
RefSub:         ld a,h
                or l
                ret z
                dec hl
                call StripAddress
                ld de,7
                add hl,de
                ld a,(hl)
                sub 1
                ld (hl),a
                inc hl
                ld a,(hl)
                sbc a,0
                ld (hl),a
                ld a,(POS_VISIBLE)
                or a
                ret z
                inc hl
                ld a,(VIDEO_FRAME)
                ld (hl),a                       ; +9 — кадр освобождения
                ret

; Откат строки полос после нехватки полосы: позиции UNDO_LOG и строка группы (IUNDO_*) получают прежние
; ссылки, число ссылок новых полос и картинок −1 (без кадра освобождения: их ещё никто не выводил), прежних
; +1. W1 — страница тайлов. Портит всё.
RowUndo:        xor a
                ld (POS_VISIBLE),a
                ld a,(IUNDO_VALID)
                or a
                jr z,.strips
                xor a
                ld (IUNDO_VALID),a
                ld a,VIDEO_IMAGE_PAGE
                call Map2
                ld hl,OLD_IREFS
                ld de,(IUNDO_AT)
                ld bc,2*IMAGE_REFS
                ldir
                ld hl,NEW_IREFS
                call IRefsSub
                ld hl,OLD_IREFS
                call IRefsAdd
.strips:        ld a,VIDEO_POSITION_PAGE
                call Map2
                ld hl,UNDO_LOG
.entry:         ld a,(UNDO_COUNT)
                or a
                ret z
                dec a
                ld (UNDO_COUNT),a
                ld e,(hl)
                inc hl
                ld d,(hl)
                inc hl                          ; DE — позиция, HL — новые ссылки
                push hl
                push de
                ld de,4
                add hl,de
                pop de
                push de
                ld bc,4
                ldir                            ; прежние ссылки — в позицию
                pop de
                pop hl
                push hl
                ld e,(hl)
                inc hl
                ld d,(hl)
                inc hl
                push hl
                ex de,hl
                call RefSub
                pop hl
                ld e,(hl)
                inc hl
                ld d,(hl)
                inc hl
                push hl
                ex de,hl
                call RefSub
                pop hl
                ld e,(hl)
                inc hl
                ld d,(hl)
                inc hl
                push hl
                ex de,hl
                call RefAdd
                pop hl
                ld e,(hl)
                inc hl
                ld d,(hl)
                inc hl
                push hl
                ex de,hl
                call RefAdd
                pop hl
                pop de                          ; снять указатель новых ссылок
                jr .entry

; POS_VISIBLE: позиция (TILE_LAYER, TILE_ROW, TILE_GROUP) видна в VIS_*_A или VIS_*_B. Портит AF, BC, DE, HL.
PositionVisibility:
                xor a
                ld (POS_VISIBLE),a
                ld a,(TILE_LAYER)
                ld e,a
                ld d,0
                ld hl,VIS_GROUPS_A
                add hl,de
                ld c,(hl)
                ld hl,VIS_GROUPS_B
                add hl,de
                ld a,(hl)
                or c
                ld c,a                          ; группы
                ld a,(TILE_GROUP)
                inc a
                ld b,a
                ld a,c
.group:         rrca
                djnz .group
                ret nc                          ; группа не видна
                ld a,e
                add a,a
                add a,a
                ld e,a                          ; слой·4
                ld a,(TILE_ROW)
                ld c,a
                rrca
                rrca
                rrca
                and 3
                add a,e
                ld e,a                          ; байт строк
                ld hl,VIS_ROWS_A
                add hl,de
                ld b,(hl)
                ld hl,VIS_ROWS_B
                add hl,de
                ld a,(hl)
                or b
                ld b,a
                ld a,c
                and 7
                inc a
                ld c,a
                ld a,b
.row:           rrca
                dec c
                jr nz,.row
                ret nc                          ; строка не видна
                ld a,1
                ld (POS_VISIBLE),a
                ret
; Число ссылок полосы HL + 1 (номер + 1; 0 — нет). Портит AF, DE, HL.
RefAdd:         ld a,h
                or l
                ret z
                dec hl
                call StripAddress
                ld de,7
                add hl,de
                inc (hl)
                ret nz
                inc hl
                inc (hl)
                ret

; --- ссылки строк групп на картинки -------------------------------------------------------------------------
; Строка группы (TILE_LAYER, TILE_ROW, TILE_GROUP): прежние ссылки на картинки (IMAGE_REFS слов, номер + 1)
; заменяются NEW_IREFS; число ссылок новых картинок +1, прежних −1 (кадр освобождения — у видимой строки, как у
; полос). Запись отката — IUNDO_AT, OLD_IREFS, IUNDO_VALID. W1 — страница тайлов, W2 — страница картинок. Портит
; всё.
ImagePositionUpdate:
                ld a,VIDEO_IMAGE_PAGE
                call Map2
                ld a,(TILE_LAYER)
                add a,a
                add a,a
                add a,a
                add a,a
                add a,a                         ; слой·32
                ld hl,TILE_ROW
                add a,(hl)
                ld l,a
                ld h,0
                add hl,hl
                add hl,hl
                add hl,hl                       ; (слой·32 + строка)·8
                ld a,(TILE_GROUP)
                ld e,a
                ld d,0
                add hl,de
                add hl,hl
                add hl,hl
                add hl,hl                       ; ·2·IMAGE_REFS
                ld de,#8000
                add hl,de
                ld (IUNDO_AT),hl
                push hl
                ld de,OLD_IREFS
                ld bc,2*IMAGE_REFS
                ldir
                pop de
                ld hl,NEW_IREFS
                ld bc,2*IMAGE_REFS
                ldir
                ld a,1
                ld (IUNDO_VALID),a
                ld hl,NEW_IREFS
                call IRefsAdd
                ld hl,OLD_IREFS
; IMAGE_REFS ссылок с HL: число ссылок картинок − 1 (IRefSub). Портит всё.
IRefsSub:       ld b,IMAGE_REFS
.ref:           ld e,(hl)
                inc hl
                ld d,(hl)
                inc hl
                push hl
                push bc
                ex de,hl
                call IRefSub
                pop bc
                pop hl
                djnz .ref
                ret
; IMAGE_REFS ссылок с HL: число ссылок картинок + 1. Портит всё.
IRefsAdd:       ld b,IMAGE_REFS
.ref:           ld e,(hl)
                inc hl
                ld d,(hl)
                inc hl
                push hl
                ex de,hl
                ld a,h
                or l
                jr z,.none
                dec hl
                call ImageAddress
                ld de,IMAGE_KEY_SIZE+2
                add hl,de
                inc (hl)
                jr nz,.none
                inc hl
                inc (hl)
.none:          pop hl
                djnz .ref
                ret
; Число ссылок картинки HL − 1 (номер + 1; 0 — нет); у видимой строки (POS_VISIBLE) — кадр освобождения, как у
; полосы (RefSub). Портит AF, DE, HL.
IRefSub:        ld a,h
                or l
                ret z
                dec hl
                call ImageAddress
                ld de,IMAGE_KEY_SIZE+2
                add hl,de
                ld a,(hl)
                sub 1
                ld (hl),a
                inc hl
                ld a,(hl)
                sbc a,0
                ld (hl),a
                ld a,(POS_VISIBLE)
                or a
                ret z
                inc hl
                ld a,(VIDEO_FRAME)
                ld (hl),a                       ; +38 — кадр освобождения
                ret

; --- ячейки -----------------------------------------------------------------------------------------------------
; Слово карты слотов (страницы VIDEO_SLOTMAP_PAGE0…) на (набор·16 + палитра, код): 0 — неизвестна,
; EMPTY_CELL — пустая, иначе признаки проходов A (бит 14), B (бит 15) и в битах 0…11 номер ячейки
; тайла или слот спрайта (#FFF — признаки известны, ячейка не загружена). Наборы: 0 — передний
; слой, 1 — фон, 2 — спрайты.

; A — набор·16 + палитра, HL — код → W2 — страница слова, HL — его адрес. Портит AF, BC, D.
SlotWordAddress:
                add hl,hl
                ld d,a
                srl a
                add a,VIDEO_SLOTMAP_PAGE0
                call Map2
                ld a,d
                rrca                            ; CF — нечётная палитра: вторая половина страницы
                ld a,#80
                jr nc,.even
                ld a,#A0
.even:          add a,h
                ld h,a
                ret

; Признаки проходов ячейки: A — набор·16 + палитра, HL — код; неизвестные — загрузчиком (ячейка не
; загружается). Выход: NZ — DE — слово; Z — пустая или нет данных. Сохраняет IX; портит остальное, W2.
CellFlags:      ld (CELL_SETPAL),a
                ld (CELL_CODE),hl
                call SlotWordAddress
                ld e,(hl)
                inc hl
                ld d,(hl)
                ld a,d
                or e
                jr z,.unknown
                ld a,d
                and #C0
                ret
.unknown:       ld a,(DATA_STATUS)
                cp DATA_READY
                jr nz,.none
                call LoaderMap
                ld a,(CELL_SETPAL)
                ld hl,(CELL_CODE)
                push ix
                call LOADER_CELL
                pop ix
                jr c,.none
                or a
                ld de,EMPTY_CELL
                jr z,.store
                or #0F
                ld d,a
                ld e,#FF                        ; признаки, ячейка не загружена
.store:         push de
                ld a,(CELL_SETPAL)
                ld hl,(CELL_CODE)
                call SlotWordAddress
                pop de
                ld (hl),e
                inc hl
                ld (hl),d
                ld a,d
                and #C0
                ret
.none:          ld hl,(VIDEO_MISSING)
                inc hl
                ld (VIDEO_MISSING),hl
                xor a
                ret

; Загруженная ячейка: A — набор·16 + палитра, HL — код. Не загруженную читает загрузчик, ячейка
; (тайлы — TileCellAlloc, спрайты — SpriteAllocS) получает поток CMD_INFLATE. Выход: NZ — DE —
; слово (биты 0…11 — номер ячейки тайла или слот спрайта); Z — пустая, нет данных или места.
; Сохраняет IX; портит остальное, окно W2.
CellEnsure:     ld (CELL_SETPAL),a
                ld (CELL_CODE),hl
                call SlotWordAddress
                ld e,(hl)
                inc hl
                ld d,(hl)
                ld a,d
                or e
                jr z,.load                      ; неизвестна
                ld a,d
                and #C0
                ret z                           ; пустая
                ld a,d
                and #0F
                cp #0F
                jr nz,.loaded
                ld a,e
                inc a
                jr z,.load                      ; признаки известны, ячейки нет
.loaded:        ld a,d
                and #C0
                ret
.load:          call CellSpend                  ; ячейка с SD тратит бюджет подгрузки кадра
                ld a,(DATA_STATUS)
                cp DATA_READY
                jr nz,.missing
                call LoaderMap
                ld a,(CELL_SETPAL)
                ld hl,(CELL_CODE)
                push ix
                call LOADER_CELL
                pop ix
                jr c,.missing
                ld (INFLATE_OFFSET),de
                ld (INFLATE_BYTES),bc
                ; куски потока (секторы в кэше загрузчика) — из страницы загрузчика, пока она в окне W2: выбор
                ; ячейки ниже меняет W2
                ld hl,LOADER_PIECES
                ld de,INFLATE_PIECES
                ld bc,LOADER_PIECES_BYTES
                ldir
                or a
                ld de,EMPTY_CELL
                jr z,.store
                ld (CELL_FLAGS),a
                ld a,(CELL_SETPAL)
                cp 32
                jr nc,.sprite
                call TileCellAlloc
                jr .allocated
.sprite:        call SpriteAllocS                ; VDAC2+: резидент, vdac2p_sprites.asm
.allocated:     jr c,.missing
                ld (CELL_SLOT),hl
                call Inflate
                ld hl,(CELL_SLOT)
                ld a,(CELL_FLAGS)
                or h
                ld d,a
                ld e,l
.store:         push de
                ld a,(CELL_SETPAL)
                ld hl,(CELL_CODE)
                call SlotWordAddress
                pop de
                ld (hl),e
                inc hl
                ld (hl),d
                ld a,d
                and #C0
                ret
.missing:       ld hl,(VIDEO_MISSING)
                inc hl
                ld (VIDEO_MISSING),hl
                xor a
                ret

; Ячейка грузится с SD: тратит бюджет подгрузки кадра. Портит AF, HL.
CellSpend:      ld hl,CELL_LEFT
                ld a,(hl)
                or a
                ret z
                dec (hl)
                ret

; Ячейка тайла для CELL_SETPAL, CELL_CODE (W1 — страница тайлов): по кругу, любая — ячейки только
; источники сборки полос (копирования прежнего содержимого уже в очереди сопроцессора, новая
; загрузка встанет после них); прежний владелец — «ячейка не загружена». Выход: HL — номер,
; INFLATE_ADDRESS; CF = 0. Портит всё, окно W2.
TileCellAlloc:  ld hl,(CELL_HAND)
                ld (ALLOC_PAIR),hl
                inc hl
                ld de,CELLS
                or a
                sbc hl,de
                add hl,de
                jr c,.hand
                ld hl,0
.hand:          ld (CELL_HAND),hl
                ld hl,(ALLOC_PAIR)
                ld d,h
                ld e,l
                add hl,hl
                add hl,de
                ld de,#4000+CELL_OWNER
                add hl,de
                ld (ALLOC_OWNER),hl
                ld bc,(ALLOC_PAIR)
                call OwnerRelease
                ld hl,(ALLOC_OWNER)
                ld a,(CELL_SETPAL)
                ld (hl),a
                inc hl
                ld de,(CELL_CODE)
                ld (hl),e
                inc hl
                ld (hl),d
                ld hl,(ALLOC_PAIR)
                call TileCellAddress
                ld (INFLATE_ADDRESS),de
                ld (INFLATE_ADDRESS+2),a
                ld hl,(ALLOC_PAIR)
                or a
                ret

; Ячейка спрайта — SpriteAllocS резидента (vdac2p_sprites.asm, VDAC2+: выборка давнейшей вместо круга).

; Запись владельца HL (набор·16 + палитра, код) ячейки или слота BC: если слово карты слотов владельца
; указывает на неё — «ячейка не загружена» (признаки остаются); запись свободна. Портит всё, окно W2.
OwnerRelease:   ld a,(hl)
                cp FREE_OWNER
                ret z
                ld (hl),FREE_OWNER
                cp OBJ_OWNER
                ret z                           ; место объекта: карты слотов нет (объект сбросит vdac2p_objects.asm)
                inc hl
                ld e,(hl)
                inc hl
                ld d,(hl)
                push bc
                ex de,hl
                call SlotWordAddress
                pop bc
                inc hl
                ld a,(hl)
                and #C0
                ret z                           ; неизвестна или пустая
                ld a,(hl)
                and #0F
                cp b
                ret nz
                dec hl
                ld a,(hl)
                cp c
                ret nz
                ld (hl),#FF
                inc hl
                ld a,(hl)
                or #0F
                ld (hl),a
                ret

; BC записей владельцев по 3 байта с HL, слоты с DE — OwnerRelease. Портит всё, окно W2.
OwnersRelease:  ld (RELEASE_LEFT),bc
                ld b,d
                ld c,e
.record:        push bc
                push hl
                call OwnerRelease
                pop hl
                pop bc
                inc hl
                inc hl
                inc hl
                inc bc
                push hl
                ld hl,(RELEASE_LEFT)
                dec hl
                ld (RELEASE_LEFT),hl
                ld a,h
                or l
                pop hl
                jr nz,.record
                ret

; CMD_INFLATE потока загрузчика по адресу INFLATE_ADDRESS: проходы A и B ячейки подряд. Поток лежит в слотах
; кэша секторов загрузчика: куски INFLATE_PIECES (страница, старший байт смещения слота) по секторам подряд,
; первый — со смещения INFLATE_OFFSET, всего INFLATE_BYTES байт. Смещение и длина потока в паке кратны 4, так
; что каждый кусок — чётное число байт с чётного адреса (DMA передаёт слова). Портит всё.
Inflate:        ld hl,WAIT_TRIES
                ld (WAIT_LEFT),hl
.space:         call CmdSpace
                ld de,(INFLATE_BYTES)
                ld bc,8
                ex de,hl
                add hl,bc
                ex de,hl
                or a
                sbc hl,de
                jr nc,.write
                call WaitTick
                jr nz,.space
.write:         call CmdOpen
                ld hl,#FF22
                ld de,#FFFF
                call EmitRaw                    ; CMD_INFLATE
                ld hl,INFLATE_ADDRESS
                call Out24
                ld hl,(INFLATE_BYTES)
                ld (INFLATE_LEFT),hl
                ld hl,INFLATE_PIECES
                ld (INFLATE_PIECE),hl
                ld de,(INFLATE_OFFSET)          ; DE — начало куска в секторе (у следующих — 0)
.piece:         ld hl,(INFLATE_PIECE)
                ld a,(hl)
                ld (INFLATE_PAGE),a             ; страница слота
                inc hl
                ld b,(hl)                       ; старший байт смещения слота в странице
                inc hl
                ld (INFLATE_PIECE),hl
                ld hl,512
                or a
                sbc hl,de                       ; HL — байт до конца сектора
                ld a,d
                add a,b
                ld d,a                          ; DE — смещение куска в странице (слот + начало в секторе)
                push de
                ex de,hl                        ; DE — байт до конца сектора
                ld hl,(INFLATE_LEFT)
                or a
                sbc hl,de                       ; остаток после куска до конца сектора
                jr nc,.fits
                add hl,de
                ex de,hl                        ; DE — весь остаток (последний кусок)
                ld hl,0
.fits:          ld (INFLATE_LEFT),hl
                ld b,d
                ld c,e                          ; BC — байт куска
                pop hl                          ; HL — смещение куска
                ld a,(INFLATE_PAGE)
                call DmaToSpi
                ld de,0
                ld hl,(INFLATE_LEFT)
                ld a,h
                or l
                jr nz,.piece
.close:         call FtClose                    ; вход второй страницы хоста после своего потока (vdac2p_objects.asm)
                ld a,1
                ld (VIDEO_UPLOADED),a
                ld hl,(VIDEO_UPLOADS)
                inc hl
                ld (VIDEO_UPLOADS),hl
                ret

; Опрос ожидания FT812: WAIT_LEFT − 1. Z — время вышло (VIDEO_TIMEOUTS + 1), NZ — ждать дальше.
; Портит AF, HL.
WaitTick:       ld hl,(WAIT_LEFT)
                dec hl
                ld (WAIT_LEFT),hl
                ld a,h
                or l
                ret nz
                ld hl,(VIDEO_TIMEOUTS)
                inc hl
                ld (VIDEO_TIMEOUTS),hl
                xor a
                ret

; Свободное место очереди сопроцессора REG_CMDB_SPACE → HL. Сбой сопроцессора (REG_CMD_READ =
; #FFF, очередь не освободится) — сброс сопроцессора по FT81X datasheet. Портит AF, C, DE.
CmdSpace:       ld a,#30
                ld de,#20F8                     ; REG_CMD_READ
                call FtRead16
                ld a,h
                cp #0F
                jr nz,.space
                ld a,l
                inc a
                call z,CmdRecover
.space:         ld a,#30
                ld de,#2574                     ; REG_CMDB_SPACE
                jp FtRead16

; Сброс сопроцессора после сбоя: REG_CPURESET = 1, указатели очереди и REG_CMD_DL — 0, REG_CPURESET = 0.
CmdRecover:     ld a,1
                ld de,#2020                     ; REG_CPURESET
                call FtWriteReg8
                ld hl,0
                ld de,#20F8                     ; REG_CMD_READ
                call FtWriteReg16
                ld de,#20FC                     ; REG_CMD_WRITE
                call FtWriteReg16
                ld de,#2100                     ; REG_CMD_DL
                call FtWriteReg16
                xor a
                ld de,#2020
                call FtWriteReg8
                ld hl,(VIDEO_FAULTS)
                inc hl
                ld (VIDEO_FAULTS),hl
                ret

; --- спрайты -----------------------------------------------------------------------------------------------
; Перед шагом: буфер спрайтов (как M72HqRenderer._draw_sprites: запись — ширина·4 слова, вывод
; от последней к первой, ячейки по столбцам) → слова в странице состояния (W1); копия буфера —
; там же (SPRITE_TEMP).
SpritesBuild:   xor a
                ld bc,DMASADDRL
                out (c),a
                ld bc,DMASADDRH
                out (c),a
                ld a,SPRITE_BUFFER_PAGE
                ld bc,DMASADDRX
                out (c),a
                ld hl,SPRITE_TEMP
                ld a,l
                ld bc,DMADADDRL
                out (c),a
                ld a,h
                ld bc,DMADADDRH
                out (c),a
                ld a,VIDEO_STATE_PAGE
                ld bc,DMADADDRX
                out (c),a
                ld a,#FF
                ld bc,DMALEN
                out (c),a
                ld a,1
                ld bc,DMANUM
                out (c),a
                ld a,DMA_RAM
                ld bc,DMACTR
                out (c),a
.wait:          ld bc,DMASTATUS
                in a,(c)
                and DMA_WNR
                jr nz,.wait
                ; адреса записей, хотя бы частично видимых на игровом поле: при X = слово 3 & #3FF
                ; и Y = слово 0 & #1FF видима, если X < 704, X + 16·w > 304, Y < 400, Y + 16·h > 144
                ; (native_x = X − 320, native_y = 384 − Y − 16·h; поле 384×240). Проверки — байтами:
                ; при старшем байте X 0…3 и Y 0…1 условия — пороги младшего байта по ширине и высоте
                ; (X ≥ 305 − 16·w: 289, 273, 241, 177; Y ≥ 145 − 16·h: 129, 113, 81, 17).
                ; Смотрим все 128 записей буфера. Указатель заполнения [2EFC] границей быть не может:
                ; замер 2026-09-20 показал живые записи за ним в 125 кадрах из 801 (обычно одна, дважды —
                ; сразу 77), а игрока эталон держит в записи 120 (сверка с MAME: код 34, X 443) вместе с
                ; ещё четырьмя спрайтами в 121…125. Прежняя граница по [2EFC] теряла корабль целиком.
                ld a,128
                ld b,a                          ; B — записей буфера
                ; Хвост буфера — записи с нулевыми байтами 5…7 (очищенные $0A53: атрибут и X = 0 —
                ; ширина 1, не видны): просмотр вперёд — только до последнего слота с ненулевым байтом.
                ld l,a
                ld h,0
                add hl,hl
                add hl,hl
                add hl,hl                       ; записей·8
                ld de,#4000+SPRITE_TEMP-1
                add hl,de                       ; байт 7 последней записи
                ld de,-6
.tail:          ld a,(hl)
                dec l                           ; байты 7…5 записи не пересекают границу 256 байт
                or (hl)
                dec l
                or (hl)
                jr nz,.head
                add hl,de                       ; байт 7 предыдущего слота
                djnz .tail
.head:          ld c,0                          ; B — слотов до последнего непустого включительно, C — видимых
                ld a,b
                or a
                jp z,.collected
                ld hl,#4000+SPRITE_TEMP+5       ; HL — старший байт атрибута
.entry:         ld a,(hl)
                and #F0
                jr nz,.shaped
                ; 1×1: полное отсечение сделает Sprite1 до чтения кода и палитры.
                ; Здесь отбрасываем только X < 256 и X >= 768 (включая пустые записи).
                inc l
                inc l
                ld a,(hl)
                and 3
                dec a
                cp 2
                jr nc,.singleSkip
                dec l
                dec l                           ; байт 5 записи: Sprite1 ждёт указатель именно на него
                push hl                         ; адрес чётный — бит 0 отличает 1×1 от записи с формой
                inc c
                ld de,8
                add hl,de                       ; байт 5 следующей записи
                djnz .entry
                jp .pass
.singleSkip:    ld de,6                         ; запись 1×1 заведомо не «широкая»: проверка .skip не нужна,
                add hl,de                       ; с байта 7 до байта 5 следующей записи — ровно 6
                dec b
                jp nz,.entry
                jp .pass
.shaped:        inc l
                inc l
                ld a,(hl)
                dec hl
                dec hl                          ; HL — атрибут (байт 5)
                and 3
                jr z,.x0
                dec a
                jr z,.x1
                dec a
                jr nz,.skip                     ; X ≥ 768
                inc hl
                ld a,(hl)                       ; X = 512…767: видима при X < 704
                dec hl
                cp 192
                jr nc,.skip
                jr .y
.x1:            ld a,(hl)                       ; X = 256…511
                cp #80
                jr nc,.y                        ; ширина 4 и 8: видима по X
                ld d,#21                        ; ширина 1: X ≥ 289
                cp #40
                jr c,.x1Low
                ld d,#11                        ; ширина 2: X ≥ 273
.x1Low:         inc hl
                ld a,(hl)
                dec hl
                cp d
                jr c,.skip
                jr .y
.x0:            ld a,(hl)                       ; X = 0…255
                cp #80
                jr c,.skip                      ; ширина 1 и 2: не видна
                ld d,#F1                        ; ширина 4: X ≥ 241
                cp #C0
                jr c,.x0Low
                ld d,#B1                        ; ширина 8: X ≥ 177
.x0Low:         inc hl
                ld a,(hl)
                dec hl
                cp d
                jr c,.skip
.y:             ld a,(hl)
                and #30                         ; log2 высоты · 16
                ld d,129
                jr z,.yThreshold
                ld d,113
                cp #10
                jr z,.yThreshold
                ld d,81
                cp #20
                jr z,.yThreshold
                ld d,17
.yThreshold:    dec hl
                dec hl
                dec hl
                dec hl
                ld a,(hl)                       ; байт 1: бит 0 — старший бит Y
                dec hl                          ; HL — начало записи
                rrca
                ld a,(hl)
                jr c,.yHigh
                cp d                            ; Y = 0…255
                jr c,.skipFromStart
                jr .visible
.yHigh:         cp 144                          ; Y = 256…511: видима при Y < 400
                jr nc,.skipFromStart
.visible:       push hl                         ; адрес записи — на стек (порядок вывода обратный)
                inc c
.skipFromStart: ld de,5
                add hl,de
.skip:          ld a,(hl)                       ; HL — атрибут
                and #C0
                jr nz,.wide
                ld de,8
                add hl,de                       ; атрибут следующей записи
                dec b
                jp nz,.entry
                jp .pass
.wide:          rlca
                rlca                            ; log2 ширины (1…3)
                ld e,a
                ld d,0
                push hl
                ld hl,CELLS_BY_LOG
                add hl,de
                ld e,(hl)                       ; слотов записи
                pop hl
                ld a,b
                sub e
                jp c,.collected
                jp z,.collected
                ld b,a
                ld a,e
                add a,a
                add a,a
                add a,a
                ld e,a                          ; от атрибута до атрибута следующей записи
                add hl,de
                jp .entry
.pass:
.collected:     ld a,#FF
                ld (SE_SLOT_PAL),a              ; окно W2 после тайлов неизвестно
                ld hl,SPRITE_WORDS+#4000
                ld (SPRITE_FILL),hl
                ld a,UNKNOWN
                ld (SPRITE_PAL),a
                xor a
                ld (SPRITE_FLIP),a              ; матрица без отражения (заголовок display list)
                ld a,#7F                        ; области, которой не бывает (#FF, 0, 1)
                ld (SPRITE_RX),a
                xor a
                ld (SPRITE_RY),a                ; окно Y ещё не задано
                ld b,c                          ; число записей — в регистре, не в памяти на каждую ячейку
                ld a,b
                or a
                jr z,.end
                ; Просмотр уже отличил 1×1 от записи с формой: у 1×1 на стеке адрес байта 5 (нечётный,
                ; как ждёт Sprite1), у остальных — начало записи (кратно восьми). Байт 5 второй раз не читаем.
.item:          pop hl                          ; адрес записи в SPRITE_TEMP
                push bc                         ; под адресами записей стек не трогаем
                call ProtectMark                ; граница слов записей игрока (vdac2p_sprites.asm)
                bit 0,l
                jr z,.shapedItem
                call Sprite1
.itemNext:      pop bc
                djnz .item
                jr .end
.shapedItem:    call SpriteEntry
                jr .itemNext
.end:           ld de,(SPRITE_FILL)
                xor a
                call SpriteTransform            ; к тайлам после спрайтов — матрица без отражения
                ld (SPRITE_FILL),de
                ex de,hl
                ld de,SPRITE_WORDS+#4000
                or a
                sbc hl,de
                ld (SPRITE_BYTES),hl
                ret

; HL — запись в SPRITE_TEMP (окно W1): Y, код, атрибут, X (слова). Форма — запись SPRITE_SHAPES по атрибуту.
; Видимые столбцы (x + 16 в 0…399) и в каждом видимые строки (y + 16 в 0…255) — ячейки SpriteCell; порядок
; (столбцы, в столбце строки) и слова буфера — как у вывода по ячейке с проверками видимости. Координаты
; столбцов и строк растут, поэтому невидимые начальные пропускаются один раз, а конец — первый выход за поле.
; Окно W2 — страница карты слотов палитры спрайта (набор 2) на всю запись (SE_SLOT_PAL — палитра отображённой
; карты; #FF — окно W2 неизвестно). Запись 1×1 (86 % в плотных сценах) — отдельной короткой веткой. Портит всё,
; окно W2.
; VDAC2+ (спрайты объектами, 2026-09-25): сначала — вывод записи одной картинкой на второй странице хоста
; (vdac2p_objects.asm; DE — запись). CF = 1 — выведена; иначе (записи нет в каталоге объектов, форма не та, пул занят,
; строки за полем, нет данных) — ячейками, как раньше. Окно W2 вторая страница могла сменить — карта слотов заново.
SpriteEntry:    push hl
                ex de,hl
                ld hl,HOST2_OBJECT
                call Host2Check
                pop hl
                ld a,#FF
                ld (SE_SLOT_PAL),a
                ret c
                ld e,(hl)
                inc hl
                ld a,(hl)
                and 1
                ld d,a                          ; DE = Y & #1FF
                inc hl
                ld c,(hl)
                inc hl
                ld b,(hl)
                ld (SPRITE_CODE),bc
                inc hl
                ld a,(hl)
                and 15
                ld (SPRITE_PALETTE),a
                inc hl
                ld b,(hl)                       ; B — старший байт атрибута
                inc hl
                ld a,(hl)
                inc hl
                ld h,(hl)
                ld l,a
                ld a,h
                and 3
                ld h,a                          ; HL = X & #3FF
.shaped:
                push hl
                ; форма: запись SPRITE_SHAPES + (атрибут >> 2)·8 → SE_SHAPE
                ld a,b
                rrca
                rrca
                and #3F
                ld l,a
                ld h,0
                add hl,hl
                add hl,hl
                add hl,hl                       ; HL = (атрибут >> 2)·8
                ld bc,SPRITE_SHAPES
                add hl,bc
                push de
                ld de,SE_SHAPE
                ld bc,8                         ; восемь LDI — 128 тактов против 178 у LDIR со счётчиком
                ldi
                ldi
                ldi
                ldi
                ldi
                ldi
                ldi
                ldi
                ; строки: y + 16 первой = 384 − Y − 16·h + 16 (запись прошла отбор: больше −16·h, меньше 256)
                pop de                          ; DE = Y
                ld a,(SE_H16)
                ld c,a
                ld b,0
                ld hl,400
                or a
                sbc hl,bc
                sbc hl,de                       ; HL = 400 − 16·h − Y
                ld a,(SE_ROWS)
                ld b,a
                ld a,(SE_ROWCODE)
                ld c,a                          ; B — строк осталось, C — смещение кода строки
                ld de,16
.rowSkip:       bit 7,h
                jr z,.rowsFirst
                add hl,de                       ; y + 16 < 0: строка не видна
                ld a,(SE_ROWSTEP)
                add a,c
                ld c,a
                djnz .rowSkip
                pop hl
                ret                             ; ни одной видимой строки
.rowsFirst:     ld a,c
                ld (SE_ROWCODE),a
                ld a,l
                ld (SE_Y0),a
                ld c,0                          ; C — видимых строк: пока y + 16 < 256
.rowCount:      inc c
                dec b
                jr z,.rowsCounted
                add a,16
                jr nc,.rowCount
.rowsCounted:   ld a,c
                ld (SE_ROWN),a
                ; столбцы: x + 16 первого = (X & #3FF) − 304 (больше −16·w, меньше 400)
                pop hl
                ld de,-304
                add hl,de
                ld a,(SE_COLUMNS)
                ld b,a
                ld a,(SE_COLCODE)
                ld c,a                          ; B — столбцов осталось, C — смещение кода столбца
                ld de,16
.columnSkip:    bit 7,h
                jr z,.columnsFirst
                add hl,de                       ; x + 16 < 0: столбец не виден
                ld a,(SE_COLSTEP)
                add a,c
                ld c,a
                djnz .columnSkip
                ret                             ; ни одного видимого столбца
.columnsFirst:  push hl
                push bc
                call SpriteSlots
                ld a,1
                ld (SE_PENDING),a               ; палитра и отражение — при первой выведенной ячейке
                pop bc
                pop hl
.column:        ; HL = x + 16 (0…399), B — столбцов осталось, C — смещение кода столбца
                push bc
                push hl
                ld a,h
                add a,high SPRITE_XT_RX
                ld h,a                          ; HL → SPRITE_XT_RX[x + 16]
                ld a,(hl)
                ld (SE_RX),a
                inc h
                inc h
                ld a,(hl)
                ld (SE_B2),a
                inc h
                inc h
                ld a,(hl)
                ld (SE_B3),a
                ld hl,SE_PENDING
                set 1,(hl)                      ; область X — при первой выведенной ячейке столбца
                ld hl,(SPRITE_CODE)
                ld a,c
                add a,l
                ld l,a
                jr nc,.columnCode
                inc h
.columnCode:    ld (SE_CODEBASE),hl             ; код + смещение столбца
                ld a,(SE_ROWN)
                ld b,a
                ld a,(SE_ROWCODE)
                ld c,a
                ld a,(SE_Y0)
.row:           ; A = y + 16, B — строк осталось, C — смещение кода строки
                ld (SE_Y),a
                push bc
                ld hl,(SE_CODEBASE)
                ld a,c
                add a,l
                ld l,a
                jr nc,.rowCode
                inc h
.rowCode:       ld a,h
                and #0F
                ld h,a                          ; HL = (код + смещения) & #FFF
                call SpriteCell
                pop bc
                ld a,(SE_ROWSTEP)
                add a,c
                ld c,a
                ld a,(SE_Y)
                add a,16
                djnz .row
                pop hl
                pop bc
                ld de,16
                add hl,de
                ld a,(SE_COLSTEP)
                add a,c
                ld c,a
                dec b
                ret z
                ld a,h                          ; следующий столбец: x + 16 < 400
                or a
                jr z,.column
                dec a
                ret nz
                ld a,l
                cp 144
                jr c,.column
                ret

; Окно W2 — карта слотов набора 2 палитры SPRITE_PALETTE: страница VIDEO_SLOTMAP_PAGE0 + (32 + палитра) >> 1,
; нечётная палитра — вторая половина страницы (SE_SLOT_BASE, как SlotWordAddress). Уже отображённая (SE_SLOT_PAL)
; не переключается. Портит AF, BC.
SpriteSlots:    ld a,(SE_SLOT_PAL)
                ld c,a
                ld a,(SPRITE_PALETTE)
                cp c
                ret z
; A — палитра: отобразить её карту. Портит F, BC.
SpriteSlotsMap: ld (SE_SLOT_PAL),a
                ld c,a
                srl a
                add a,VIDEO_SLOTMAP_PAGE0+16
                ld (SE_SLOT_PAGE),a
                ld b,a
                ld a,c
                rrca
                ld a,#80
                jr nc,.base
                ld a,#A0
.base:          ld (SE_SLOT_BASE),a
                ld a,b
                jp Map2

; Запись 1×1 (86 % записей в плотных сценах): HL — байт 5 записи в SPRITE_TEMP.
; Код и палитра читаются только после отсечения; код до карты слотов остаётся в регистрах/стеке.
; Слова — как у SpriteEntry/SpriteCell для той же ячейки: y + 16 = 384 − Y и
; x + 16 = X − 304 — без 16-битной арифметики, байты вершины и области — по таблицам, состояние буфера
; (палитра, отражение, области X и Y) сверяется перед словами ячейки. Портит всё, окно W2.
Sprite1:        ld b,(hl)
                push hl                         ; атрибут: после проверки X вернёмся к Y
                inc l
                ld a,(hl)
                inc l
                ld h,(hl)
                ld l,a
                ld a,h
                and 3
                ld h,a
                ld a,h                          ; x + 16: X = 256…511 — X_low − 48 (≥ 0); 512…767 — X_low + 208 (< 400)
                dec a
                jr nz,.x2
                ld a,l
                sub 48
                jp c,.outside
                ld l,a
                ld h,high SPRITE_XT_RX
                jr .xt
.x2:            dec a
                jp nz,.outside                  ; X < 256 или X ≥ 768 — не видна
                ld a,l
                cp 192
                jp nc,.outside
                sub 48
                ld l,a
                ld a,high SPRITE_XT_RX+1
                sbc a,0                         ; X_low < 48: x + 16 = X_low + 208 < 256
                ld h,a
.xt:            ld (SE_XT),hl                   ; HL → SPRITE_XT_RX[x + 16]
                pop hl
                ld a,l
                sub 5
                ld l,a                          ; начало записи
                ld a,128
                sub (hl)
                ld e,a                          ; E = y + 16
                sbc a,a
                inc l
                xor (hl)
                rrca
                ret nc                          ; бит 0 старшего байта Y и заём должны различаться
                ld a,e
                ld (SE_Y),a
                inc l
                ld e,(hl)
                inc l
                ld d,(hl)
                push de                         ; код до выбора карты слотов
                inc l
                ld a,(hl)
                and 15
                ld (SPRITE_PALETTE),a
                ld c,a                          ; палитра переживает разбор отражения в C — без второго чтения
                ld a,b
                rrca
                rrca
                and 3
                ld l,a
                ld h,high SPRITE_FLIPS
                ld a,(hl)
                ld (SE_FLIP),a                  ; биты 3, 2 атрибута → режим матрицы: fx (бит 0), fy (бит 2)
                pop hl                          ; код — без промежуточной глобальной переменной
                ld a,(SE_SLOT_PAL)
                cp c
                ld a,c
                call nz,SpriteSlotsMap
                ld a,h
                and #0F
                ld h,a                          ; HL = код & #FFF
                ld d,h
                ld e,l                          ; DE — код (для CellEnsure)
                add hl,hl
                ld a,(SE_SLOT_BASE)
                add a,h
                ld h,a                          ; HL → слово карты: база + код·2
                ld c,(hl)
                inc hl
                ld b,(hl)                       ; BC — слово
                ld a,b
                and #0F
                cp 3
                jp nz,.ensure                   ; не загружена, пустая или неизвестна
.loaded:        ld h,high (#4000+SLOT_USED)
                ld l,c
                ld a,(VIDEO_FRAME)
                ld (hl),a                       ; кадр вывода: SLOT_USED + слот − SPRITE_SLOT0
                ld de,(SPRITE_FILL)
                ld a,d
                cp high (SPRITE_WORDS_END+#4000-52)
                jr nc,.near
.room:          ld hl,SPRITE_PAL
                ld a,(SPRITE_PALETTE)
                cp (hl)
                call nz,SpritePaletteWord
                ld a,(SE_FLIP)
                inc hl                          ; SPRITE_FLIP
                cp (hl)
                call nz,SpriteFlipWords
                ld hl,(SE_XT)
                ld a,(SPRITE_RX)
                cp (hl)
                call nz,SpriteTranslateXAt
                ld a,(SE_Y)
                ld l,a
                ld h,high SPRITE_YT_RY          ; HL → SPRITE_YT_RY[y + 16]: окна ячейки
                ld a,(SPRITE_RY)
                and (hl)
                call z,SpriteTranslateY         ; в текущее окно Y ячейка не входит
                inc h
                ld a,(hl)
                ex af,af'                       ; A' — байт 1; до вывода вершины вызовов больше нет
                inc h
                ld a,(hl)                       ; y >> 4 верхнего окна
                ld hl,SPRITE_RY
                bit 1,(hl)
                jr z,.upper
                sub 16                          ; нижнее окно: вершина на 256 выше
.upper:         ld hl,(SE_XT)
                inc h
                inc h
                or (hl)                         ; байт 2: | (x & 7) << 5
                inc h
                inc h
                ld l,(hl)                       ; L — байт 3: #80 | x >> 3
                ld h,a                          ; H — байт 2
                ex af,af'                       ; A — байт 1: (y & 15) << 4 | 3
                ex de,hl                        ; HL — буфер, D/E — байты 2/3; A сохраняется до прохода B
                bit 6,b
                jr z,.passB
                ld (hl),c
                inc l
                ld (hl),a
                inc l
                ld (hl),d
                inc l
                ld (hl),e
                inc hl
.passB:         bit 7,b
                jr z,.done
                ld (hl),c
                inc l
                inc a                           ; проход B — handle-псевдоним: слот + 256
                ld (hl),a
                inc l
                ld (hl),d
                inc l
                ld (hl),e
                inc hl
.done:          ld (SPRITE_FILL),hl
                ret
.near:          jr nz,.full
                ld a,e
                cp low (SPRITE_WORDS_END+#4000-52)+1
                jp c,.room
.full:          ld hl,(VIDEO_OVERFLOW)
                inc hl
                ld (VIDEO_OVERFLOW),hl
                ret
.ensure:        ex de,hl                        ; HL = код
                ld a,(SPRITE_PALETTE)
                add a,32                        ; набор 2 — спрайты
                call CellEnsure
                push af
                push de
                ld a,(SE_SLOT_PAGE)
                call Map2
                pop bc                          ; BC — слово
                pop af
                ret z                           ; пустая, нет данных или места
                jp .loaded
.outside:       pop hl
                ret

; PALETTE_SOURCE палитра·512: A — палитра, HL → SPRITE_PAL (= A), DE — буфер. Сохраняет BC, HL.
SpritePaletteWord:
                ld (hl),a
                add a,a
                ex de,hl
                ld (hl),0
                inc l                           ; начало слова кратно четырём: первые три шага без переноса
                ld (hl),a
                inc l
                ld (hl),0
                inc l
                ld (hl),#2A
                inc hl
                ex de,hl
                ret

; Матрица режима A (SpriteTransform) с сохранением BC, HL.
SpriteFlipWords:
                push bc
                push hl
                call SpriteTransform
                pop hl
                pop bc
                ret

; VERTEX_TRANSLATE_X: HL → область (#FF, 0, 1) в SPRITE_XT_RX, SPRITE_RX = она. Сохраняет BC, HL.
SpriteTranslateXAt:
                ld a,(hl)
                ld (SPRITE_RX),a
                ex de,hl
                ld (hl),0
                inc l
                add a,a
                add a,a
                add a,a
                add a,a
                add a,a                         ; #FF/0/1 → #E0/0/#20: знак области остаётся в бите 7
                ld (hl),a
                inc l
                rlca
                and 1
                ld (hl),a
                inc l
                ld (hl),#2B
                inc hl
                ex de,hl                        ; BC и указатель таблицы HL не трогали
                ret

; Ячейка спрайта: HL — код (0…#FFF), SE_Y — y + 16; столбец — SE_RX, SE_B2, SE_B3. Слово карты слотов (окно
; W2): загруженная ячейка (старший полубайт слота 3) — сразу, иначе CellEnsure (признаки, загрузка; окно
; W2 после — снова карта слотов). Кадр вывода (SLOT_USED), место в буфере (DE + 52 <= SPRITE_WORDS_END, иначе
; VIDEO_OVERFLOW), состояние буфера (палитра, матрица, области X и Y), VERTEX2II проходов A (слот) и B
; (handle-псевдоним). Портит всё, кроме IX, IY.
SpriteCell:     ld d,h
                ld e,l                          ; DE = код (для CellEnsure)
                add hl,hl
                ld a,(SE_SLOT_BASE)
                add a,h
                ld h,a                          ; HL → слово карты: база + код·2
                ld c,(hl)
                inc hl
                ld b,(hl)                       ; BC — слово
                ld a,b
                and #0F
                cp 3
                jp nz,.ensure                   ; не загружена, пустая или неизвестна
.loaded:        ld h,high (#4000+SLOT_USED)
                ld l,c
                ld a,(VIDEO_FRAME)
                ld (hl),a                       ; кадр вывода: SLOT_USED + слот − SPRITE_SLOT0
                ld de,(SPRITE_FILL)
                ld a,d
                cp high (SPRITE_WORDS_END+#4000-52)
                jr nc,.near
.room:          ld a,(SE_PENDING)
                or a
                call nz,SpriteState
                ld a,(SE_FLIP)
                ld hl,SPRITE_FLIP
                cp (hl)
                call nz,SpriteFlipWords
                ld a,(SE_Y)
                ld l,a
                ld h,high SPRITE_YT_RY          ; HL → SPRITE_YT_RY[y + 16]: окна ячейки
                ld a,(SPRITE_RY)
                and (hl)
                call z,SpriteTranslateY         ; в текущее окно Y ячейка не входит
                inc h
                ld a,(hl)                       ; байт 1: (y & 15) << 4 | 3
                inc h
                ld l,(hl)                       ; y >> 4 верхнего окна
                ld h,a                          ; H — байт 1
                ld a,(SPRITE_RY)
                and 2
                jr z,.upper
                ld a,l
                sub 16                          ; нижнее окно: вершина на 256 выше
                ld l,a
.upper:         ld a,(SE_B2)
                or l
                ld l,a                          ; L — байт 2: y >> 4 | (x & 7) << 5
                ld a,(SE_B3)                    ; A — байт 3 для обоих проходов
                ex de,hl                        ; HL — буфер, D/E — байты 1/2
                bit 6,b
                jr z,.passB
                ld (hl),c
                inc l
                ld (hl),d
                inc l
                ld (hl),e
                inc l
                ld (hl),a
                inc hl
.passB:         bit 7,b
                jr z,.done
                ld (hl),c
                inc l
                inc d                           ; проход B — handle-псевдоним: слот + 256
                ld (hl),d
                inc l
                ld (hl),e
                inc l
                ld (hl),a
                inc hl
.done:          ld (SPRITE_FILL),hl
                ret
.near:          jr nz,.full
                ld a,e
                cp low (SPRITE_WORDS_END+#4000-52)+1
                jr c,.room
.full:          ld hl,(VIDEO_OVERFLOW)
                inc hl
                ld (VIDEO_OVERFLOW),hl
                ret
.ensure:        ex de,hl                        ; HL = код
                ld a,(SPRITE_PALETTE)
                add a,32                        ; набор 2 — спрайты
                call CellEnsure
                push af
                push de
                ld a,(SE_SLOT_PAGE)
                call Map2
                pop bc                          ; BC — слово
                pop af
                ret z                           ; пустая, нет данных или места
                jp .loaded
                ASSERT low SLOT_USED == 0 && SPRITE_SLOT0 == #300 && SPRITE_CELLS == 256

; Состояние буфера перед первой ячейкой записи (SE_PENDING бит 0: PALETTE_SOURCE при смене палитры) и столбца
; (бит 1: VERTEX_TRANSLATE_X при смене области); матрицу ставит ячейка (у родной ячейки своя). A = SE_PENDING,
; DE — буфер. Сохраняет BC.
SpriteState:    push bc
                rrca
                jr nc,.region
                ld a,(SPRITE_PALETTE)
                ld hl,SPRITE_PAL
                cp (hl)
                jr z,.region
                ld (hl),a                       ; PALETTE_SOURCE палитра·512
                add a,a
                ld c,a
                xor a
                ld (de),a
                inc de
                ld a,c
                ld (de),a
                inc de
                xor a
                ld (de),a
                inc de
                ld a,#2A
                ld (de),a
                inc de
.region:        ld a,(SE_PENDING)
                and 2
                jr z,.done
                ld a,(SE_RX)
                ld hl,SPRITE_RX
                cp (hl)
                jr z,.done
                ld (hl),a
                ld b,#2B
                call SpriteTranslate
.done:          xor a
                ld (SE_PENDING),a
                pop bc
                ret

; VERTEX_TRANSLATE_Y окна Y спрайтов (VDAC2+, v30z80_video_assets.sprite_tables): HL → окна ячейки в SPRITE_YT_RY —
; верхнее (бит 0; сдвиг −48 px = #1FD00 в 1/16 пикселя), если ячейка в него входит, иначе нижнее (208 px = #00D00);
; SPRITE_RY = 1 или 2. DE — буфер. Сохраняет BC, HL.
SpriteTranslateY:
                ld a,(hl)
                ex de,hl
                ld (hl),0
                inc l
                rrca
                jr nc,.lower
                ld (hl),#FD
                inc l
                ld (hl),1
                ld a,1
                jr .word
.lower:         ld (hl),#0D
                inc l
                ld (hl),0
                ld a,2
.word:          inc l
                ld (hl),#2C
                inc hl
                ex de,hl
                ld (SPRITE_RY),a
                ret
; VERTEX_TRANSLATE (B — код #2B или #2C): A — область (#FF, 0, 1), сдвиг = область·8192 (1/16 пикселя). DE —
; буфер. Портит AF, C.
SpriteTranslate:
                ld c,a                          ; общий вход сохраняет исходный знак и для произвольного байта
                ex de,hl
                ld (hl),0
                inc l
                add a,a
                add a,a
                add a,a
                add a,a
                add a,a
                ld (hl),a                       ; байт 1 = область·32
                inc l
                ld a,c
                rlca
                and 1
                ld (hl),a                       ; бит 16 — знак
                inc l
                ld (hl),b
                inc hl
                ex de,hl
                ret

; Матрица в буфере спрайтов: A — нужный режим, SPRITE_FLIP — текущий. Режим оси X — бит 0 (зеркало), оси Y —
; бит 2 (биты 1 и 3 всегда 0). У изменившейся оси — слова из SPRITE_TRANSFORMS: A и C (X) или E и F (Y); если ни
; прежний, ни новый режим оси не зеркальный (сдвиг 0 у обоих) — только A или E. DE — указатель в буфере (на
; выходе — после слов). Портит AF, BC, HL.
SpriteTransform:
                ld b,a
                ld a,(SPRITE_FLIP)
                cp b
                ret z
                ld c,a                          ; C — прежний режим
                ld a,b
                ld (SPRITE_FLIP),a
                xor c
                and 3
                jr z,.axisY
                ld a,b
                or c
                and 1
                ld h,a                          ; H ≠ 0 — и слово сдвига
                ld a,b
                and 3
                push bc
                ld bc,SPRITE_TRANSFORMS
                call TransformWords
                pop bc
.axisY:         ld a,b
                xor c
                and #0C
                ret z
                ld a,b
                or c
                and 4
                ld h,a
                ld a,b
                rrca
                rrca
                and 3
                ld bc,SPRITE_TRANSFORMS+16
; Слова оси: A — режим оси (0 или 1), BC — её таблица (по 8 байт на режим: слово масштаба, слово сдвига), H ≠ 0 —
; и слово сдвига. DE — буфер. Портит AF, BC, HL.
TransformWords: add a,a
                add a,a
                add a,a
                add a,c
                ld c,a
                jr nc,.table
                inc b
.table:         ld a,h
                ld h,b
                ld l,c
                ld bc,4
                or a
                jr z,.copy
                ld c,8
.copy:          ldir
                ret

; --- кадр ------------------------------------------------------------------------------------------------------
; Display list: заголовок и handle; JUMP через подпрограммы; подпрограммы слоёв (проход приоритета,
; полоса растра, слой: сдвиги, палитры, пакеты полос, RETURN); основная часть — по проходам и
; полосам: ножницы, для слоя CALL подпрограммы (проходы A и B её полос и картинок — парами вершин); между
; проходами — спрайты; DISPLAY.
FrameEmit:      ; прежний список ещё не показан — ждать (не дольше WAIT_TRIES опросов: сбой FT812 не
                ; должен останавливать игру)
                ld hl,WAIT_TRIES
                ld (WAIT_LEFT),hl
.swap:          ld a,#30
                ld de,#2054
                call FtRead16
                ld a,l
                or a
                jr z,.shown
                call WaitTick
                jr nz,.swap
.shown:         ld a,VIDEO_STATE_PAGE
                call Map1                       ; заголовки потоков, таблицы сдвигов
                ld a,(VIDEO_UPLOADED)
                or a
                jr z,.ready
                xor a
                ld (VIDEO_UPLOADED),a
                ld hl,WAIT_TRIES
                ld (WAIT_LEFT),hl
.idle:          call CmdSpace                   ; команды сопроцессора (загрузки, сборка полос) исполнены
                ld de,4092
                or a
                sbc hl,de
                jr z,.ready
                call WaitTick
                jr nz,.idle
.ready:         ld hl,0
                ld (DL_SENT),hl
                ld hl,DL_LIMIT
                ld (DL_CAP),hl
                xor a
                ld (DL_FULL),a
                ld a,#30
                ld de,#0000
                call FtOpenWrite                ; RAM_DL
                ld hl,DL_HEADER
                ld b,(DL_HEADER_END-DL_HEADER)/4
                call EmitTable
                ; Очистка — только если экран не закроет кольцо фона: оно непрозрачно (альфа 15 у всех
                ; записей палитры) и двумя полосами покрывает все 768 строк. Кольца нет, пока оно не
                ; записано целиком (RING_READY) и когда видео выключено — тогда гасим кадр очисткой.
                ld a,(RING_READY)
                or a
                jr z,.clear
                ld a,(VIDEO_OFF_SNAP)
                or a
                jr z,.noClear
.clear:         ld hl,#0007
                ld de,#2600                     ; CLEAR 1,1,1
                call EmitWord
.noClear:
                ifdef RTYPE_COUNTERS
                ; Диагностика: фон кадра краснеет по счётчику невыведенных ячеек (VIDEO_MISSING) —
                ; так его видно на снимке экрана там, куда не дотянуться дампом ОЗУ (титры, поздние
                ; этапы). Оттенок = младший байт счётчика, при переполнении старшего — полный красный.
                ; Собирается только с определением RTYPE_COUNTERS, в релизный SPG не входит.
                ; Каналы фона: красный — были невыведенные ячейки (VIDEO_MISSING), зелёный —
                ; переполнялся display list (VIDEO_DROPPED), синий — сбрасывался сопроцессор FT812
                ; (VIDEO_FAULTS). Значение 64, чтобы подсветка читалась на снимке, но не забивала картинку.
                ld d,#02                        ; CLEAR_COLOR_RGB
                ld hl,(VIDEO_MISSING)
                ld a,h
                or l
                ld e,#00
                jr z,.noMissing
                ld e,#40
.noMissing:     ld hl,(VIDEO_DROPPED)
                ld a,h
                or l
                ld a,#00
                jr z,.noDropped
                ld a,#40
.noDropped:     push af
                ld hl,(VIDEO_FAULTS)
                ld a,h
                or l
                ld l,#00
                jr z,.noFaults
                ld l,#40
.noFaults:      pop af
                ld h,a
                call EmitWord
                ld hl,#0007
                ld de,#2600                     ; CLEAR 1,1,1 — перекрасить уже очищенный кадр
                call EmitWord
                endif
                ld a,(VIDEO_HANDLES)
                or a
                jr z,.noHandles
                xor a
                ld (VIDEO_HANDLES),a
                ld hl,DL_HANDLES
                ld b,(DL_HANDLES_END-DL_HANDLES)/4
                call EmitTable
.noHandles:     ld a,(VIDEO_OFF_SNAP)
                or a
                jp nz,.finish                   ; очистка для этого кадра уже поставлена выше
                ld hl,(DL_SENT)
                ld (JUMP_AT),hl
                ld hl,0
                ld de,#1E00
                call EmitReserved               ; JUMP на основную часть (номер — после подпрограмм)
                call BandsSetup
                ; предел подпрограмм: место основной части, возвратов и спрайтов оставлено
                ld hl,(SPRITE_BYTES)
                ld de,MAIN_RESERVE
                add hl,de
                ex de,hl
                ld hl,DL_LIMIT
                or a
                sbc hl,de
                ld (DL_CAP),hl
                xor a
                ld (EMIT_PASS),a
.subPass:       xor a
                ld (EMIT_BAND),a
.subBand:       call BandSelect
                ld a,1
                ld (TILE_LAYER),a
                call SubEmit
                xor a
                ld (TILE_LAYER),a
                call SubEmit
                ld hl,EMIT_BAND
                inc (hl)
                ld a,(BAND_COUNT)
                cp (hl)
                jr nz,.subBand
                ld hl,EMIT_PASS
                inc (hl)
                ld a,(hl)
                cp 2
                jr c,.subPass
                ; номер первой команды основной части — в слово JUMP
                call FtClose
                ld de,(JUMP_AT)
                ld a,#30
                call FtOpenWrite
                ld hl,(DL_SENT)
                srl h
                rr l
                srl h
                rr l
                ld de,#1E00
                call EmitRaw
                call FtClose
                ld de,(DL_SENT)
                ld a,#30
                call FtOpenWrite                ; запись продолжается с основной части
                ld hl,DL_LIMIT
                ld (DL_CAP),hl
                xor a
                ld (DL_FULL),a
                ld (EMIT_PASS),a
                ld (RING_CONT),a
                call MainPass
                ld hl,#0000
                ld de,#1B00                     ; SCISSOR_XY 0,0
                call EmitWord
                ld hl,720
                ld de,#1C40                     ; SCISSOR_SIZE 1024,720: игровое поле. Спрайты ниже не
                                                ; выводятся — панель они не перекрывают, как в аркаде
                                                ; (эталон `M72HqRenderer` рисует их поверх панели: его
                                                ; расхождение на корабле этапа 3, кадр 27 000).
                call EmitWord
                ; VDAC2+: защита строки FT812 — в перегруженном кадре спрайты без прохода B (vdac2p_guard.asm, вторая
                ; страница хоста); блок GUARD_ARGS — в странице состояния (окно W1)
                ld hl,(JUMP_AT)
                ld (GUARD_ARGS),hl
                ld hl,(DL_SENT)
                ld (GUARD_ARGS+2),hl
                ld hl,(SPRITE_BYTES)
                ld (GUARD_ARGS+4),hl
                ld hl,HOST2_GUARD
                call Host2Check
                ld bc,(GUARD_ARGS+4)            ; байт слов спрайтов после защиты
                ld a,b
                or c
                jr z,.noSprites
                ld a,VIDEO_STATE_PAGE
                ld hl,SPRITE_WORDS
                call DlBurst
.noSprites:     ld a,1
                ld (EMIT_PASS),a
                call MainPass
.finish:                        ld hl,(DL_SENT)
                ld (DL_LAST),hl                 ; место DISPLAY — для затемнения (HostVideoFade)
                ld hl,#0000
                ld de,#0000                     ; DISPLAY: место оставлено пределом DL_LIMIT
                call EmitRaw
                call FtClose
                call LabelCall                  ; VDAC2+: надпись скорости мыши и клавиш — на место DISPLAY (vdac2p_label.asm)
                ld a,1
                ld (VIDEO_SHOWN),a
                call VisibilityUpdate
                ; Таблицы палитр в RAM_G общие для показанного и нового списка: изменённые перья
                ; пишутся перед самым DLSWAP — показанный кадр получает новые цвета лишь на время
                ; записи и ожидания конца развёртки (отступление на аппаратном пределе, а не на всё
                ; построение списка).
                ld a,VIDEO_STATE_PAGE
                call Map1
                call PalettesUpload
                ld hl,TITLE_GUARD
                ld a,(hl)
                or a
                jr z,.swapRequest
                dec (hl)
.swapRequest:   ld a,1
                ld (SWAP_PENDING),a
                inc a
                ld de,#2054                     ; REG_DLSWAP = DLSWAP_FRAME
                jp FtWriteReg8

; Видимость позиций собранного display list → VIS_*_A (прежняя — в VIS_*_B): группы — маска геометрии слоя в
; полосе растра, строки полос — её куски (LayerEmit выводит только их). Слой без потоков и выключенное видео —
; ничего не видно; геометрия без признака годности — видно всё. Портит всё.
VisibilityUpdate:
                ld hl,VIS_ROWS_A
                ld de,VIS_ROWS_B
                ld bc,10
                ldir
                ld hl,VIS_ROWS_A
                ld de,VIS_ROWS_A+1
                ld bc,10-1
                ld (hl),0
                ldir
                ld a,(VIDEO_OFF_SNAP)
                or a
                ret nz
                ld a,VIDEO_COLUMN_PAGE
                call Map2                       ; биты диапазонов строк (ROW_RANGE_OFFSET)
                xor a
                ld (VIS_LAYER),a
.layer:         ld a,(VIS_LAYER)
                add a,a
                ld e,a
                ld d,0
                ld hl,LAYER_STREAMS
                add hl,de
                ld a,(hl)
                inc hl
                or (hl)
                ld bc,3
                add hl,bc                       ; те же проходы у картинок (LAYER_STREAMS + 4)
                or (hl)
                inc hl
                or (hl)
                jp z,.nextLayer                 ; слой не выводится
                xor a
                ld (VIS_BAND),a
.band:          ld a,(VIS_LAYER)
                add a,a
                ld hl,VIS_BAND
                add a,(hl)
                ld l,a
                ld h,0
                ld de,GEOMETRY_SIZE
                call MultiplyHLDE
                ld de,GEOMETRY
                add hl,de
                ld a,(hl)
                or a
                jp z,.all
                push hl
                ld de,GEOMETRY_X
                add hl,de
                ld a,(hl)
                or a
                jp z,.allPop
                inc hl
                inc hl
                inc hl
                ld b,(hl)                       ; маска видимых групп полосы
                ld a,(VIS_LAYER)
                ld e,a
                ld d,0
                ld hl,VIS_GROUPS_A
                add hl,de
                ld a,(hl)
                or b
                ld (hl),a
                pop hl
                ld de,5
                add hl,de
                ld a,(hl)                       ; кусков
                ld (VIS_PIECES),a
                inc hl
.piece:         ld a,(VIS_PIECES)
                or a
                jr z,.nextBand
                dec a
                ld (VIS_PIECES),a
                ld e,(hl)                       ; область
                inc hl
                ld d,0
                push hl
                ld hl,REGION_FIRST
                add hl,de
                ld c,(hl)
                pop hl
                ld a,(hl)                       ; первая строка полос в области
                inc hl
                add a,c
                ld c,a                          ; строка полос
                ld b,(hl)                       ; строк
                inc hl
                inc hl
                inc hl
                inc hl                          ; следующий кусок (6 байт)
                push hl
                ; биты строк [C, C + B) — 4 байта таблицы: #8000 + ROW_RANGE_OFFSET + (C·12 + B)·4 (окно W2)
                ld l,c
                ld h,0
                add hl,hl
                add hl,hl
                ld e,l
                ld d,h
                add hl,hl
                add hl,de                       ; C·12
                ld e,b
                ld d,0
                add hl,de
                add hl,hl
                add hl,hl
                ld de,#8000+ROW_RANGE_OFFSET
                add hl,de
                ex de,hl                        ; DE → биты
                ld a,(VIS_LAYER)
                add a,a
                add a,a
                ld l,a
                ld h,0
                ld bc,VIS_ROWS_A
                add hl,bc                       ; HL → строки слоя
                ld b,4
.rowBits:       ld a,(de)
                or (hl)
                ld (hl),a
                inc hl
                inc de
                djnz .rowBits
                pop hl
                jr .piece
                ASSERT ROW_RANGE_OFFSET+32*12*4 <= #4000
.nextBand:      ld hl,VIS_BAND
                inc (hl)
                ld a,(BAND_COUNT)
                cp (hl)
                jp nz,.band
.nextLayer:     ld hl,VIS_LAYER
                inc (hl)
                ld a,(hl)
                cp 2
                jp c,.layer
                ret
.allPop:        pop hl
.all:           ld a,(VIS_LAYER)
                ld e,a
                ld d,0
                ld hl,VIS_GROUPS_A
                add hl,de
                ld (hl),#FF
                ld a,e
                add a,a
                add a,a
                ld e,a
                ld hl,VIS_ROWS_A
                add hl,de
                ld b,4
.allRows:       ld (hl),#FF
                inc hl
                djnz .allRows
                jr .nextLayer

; Подпрограмма слоя TILE_LAYER, прохода EMIT_PASS, полосы EMIT_BAND: слова LayerEmit и RETURN; номер
; первой команды — в SUB_TABLE (#FFFF — слов нет). Состояние сдвигов и палитры в начале подпрограммы
; неизвестно: основная часть вызывает её после ножниц и спрайтов; матрица — без отражения, и подпрограмма
; возвращает её такой (слова сброса — на зарезервированном месте: переполнение списка их не отменяет).
; Годная копия прошлого кадра выводится из кэша (CacheReplay), иначе слова выводятся заново и записываются в
; кэш (CaptureBegin … CaptureEnd). Портит всё, окно W2.
SubEmit:        call SubIndex
                ld (hl),#FF
                inc hl
                ld (hl),#FF
                ld a,(DL_FULL)
                or a
                ret nz
                call LayerGeometry
                ret z                           ; у слоя-прохода нет потоков
                ld hl,(DL_SENT)
                ld (SUB_START),hl
                call CacheReplay
                jr c,.table                     ; выведена копия
                call CaptureBegin
                ld a,UNKNOWN
                ld (CUR_PAL),a
                ld a,TRANSLATE_UNKNOWN
                ld (CUR_TX_H),a
                ld (CUR_TY_H),a
                xor a
                ld (CUR_FLIP),a
                call LayerEmit
                ld hl,(DL_SENT)
                ld de,(SUB_START)
                or a
                sbc hl,de
                jp z,CaptureEnd                 ; слов нет (в кэш — и пустая подпрограмма)
                ld a,(CUR_FLIP)
                ld hl,DL_FULL
                or (hl)                         ; после переполнения состояние матрицы неизвестно
                jr z,.return
                ld hl,TILE_TRANSFORMS
                ld b,2
.unflip:        push bc
                ld e,(hl)
                inc hl
                ld d,(hl)
                inc hl
                ld c,(hl)
                inc hl
                ld b,(hl)
                inc hl
                push hl
                ex de,hl
                ld d,b
                ld e,c
                call EmitReserved               ; BITMAP_TRANSFORM_A 160, C 0
                pop hl
                pop bc
                djnz .unflip
.return:        ld hl,0
                ld de,#2400
                call EmitReserved               ; RETURN
                call CaptureEnd
.table:         ld hl,(DL_SENT)
                ld de,(SUB_START)
                or a
                sbc hl,de
                ret z                           ; слов нет (пустая копия)
                call SubIndex
                ld de,(SUB_START)
                srl d
                rr e
                srl d
                rr e
                ld (hl),e
                inc hl
                ld (hl),d
                ret

; --- кэш подпрограмм слоёв ----------------------------------------------------------------------------------------
; Подпрограмма слоя-прохода в полосе от кадра к кадру обычно та же с точностью до значений VERTEX_TRANSLATE (замер
; на модели SPG: 82 % подпрограмм прогона с неуязвимостью): её слова хранятся в слоте s = проход·4 + полоса·2 +
; (слой = 0) страницы VIDEO_CACHE_PAGE (CACHE_SLOT байт: CACHE_DL_BYTES — слова, дальше записи сдвигов по
; CACHE_RECORD байт: вид 0 — X, 1 — Y; адрес значения в геометрии (3 байта C:DE, как у TranslateCheck); смещение
; слова в подпрограмме, #FFFF — значение совпало с текущим и слово не выводилось). Копия годна (CACHE_OK), пока не
; было перестроек строк, которые она выводит (CacheInvalidate из StreamSplice), и структура та же: число кусков, их
; области, первые строки и число строк, маска видимых групп (CACHE_STRUCT). Тогда те же слова выводит и LayerEmit:
; видимые части заголовков и потоков не менялись, а сдвиги X и Y определяются геометрией.
CACHE_RECORD    EQU 5
CACHE_RECORDS   EQU (CACHE_SLOT-CACHE_DL_BYTES)/CACHE_RECORD
CACHE_STRUCT_SIZE EQU 14                ; число кусков, 4 куска по 3 байта, маска групп
                ASSERT CACHE_STRUCT_SIZE == 2+3*4 && CACHE_RECORDS <= 255

; Слот кэша текущих слоя, прохода и полосы → A и E, D = 0. Портит F.
CacheIndex:     ld a,(EMIT_PASS)
                add a,a
                ld e,a
                ld a,(EMIT_BAND)
                add a,e
                add a,a
                ld e,a
                ld a,(TILE_LAYER)
                or a
                ld a,e
                jr nz,.layer
                inc a
.layer:         ld e,a
                ld d,0
                ret

; Структура слота E в CACHE_STRUCT → HL (E·14 = E·16 − E·2). Портит AF, DE.
CacheStruct:    ld a,e
                add a,a
                ld d,a
                add a,a
                add a,a
                add a,a
                sub d
                ld e,a
                ld d,0
                ld hl,CACHE_STRUCT
                add hl,de
                ret

; Подпрограмма из кэша (геометрия готова — LayerGeometry, SUB_START — начало): копия годна, структура совпадает, место
; в display list есть, и по записям сдвигов с нынешними значениями слова выводились бы там же — тогда значения
; вписываются в копию, копия уходит DMA в RAM_DL (DL_SENT растёт). CF = 1 — выведена (или пуста); CF = 0 — выводить
; заново. Состояние сдвигов CUR_TX, CUR_TY — как после вывода. Портит всё, окно W2.
CacheReplay:    call CacheIndex
                ld (CACHE_NOW),a
                ld hl,CACHE_OK
                add hl,de
                ld a,(hl)
                or a
                ret z                           ; копии нет (или её сняла CacheInvalidate)
                call CacheStruct
                ex de,hl                        ; DE → структура копии
                ld hl,(GEOMETRY_PTR)
                ld bc,5
                add hl,bc                       ; HL → число кусков
                ld a,(de)
                cp (hl)
                jp nz,.miss
                or a
                jr z,.mask
                ld b,a
.piece:         inc hl
                inc de
                ld a,(de)
                cp (hl)                         ; область
                jp nz,.miss
                inc hl
                inc de
                ld a,(de)
                cp (hl)                         ; первая строка полос в области
                jp nz,.miss
                inc hl
                inc de
                ld a,(de)
                cp (hl)                         ; строк
                jp nz,.miss
                inc hl
                inc hl
                inc hl                          ; сдвиг Y куска — по записям
                djnz .piece
.mask:          ld a,(CACHE_NOW)
                ld e,a
                ld d,0
                call CacheStruct
                ld de,CACHE_STRUCT_SIZE-1
                add hl,de
                ex de,hl                        ; DE → маска групп копии
                ld hl,(GEOMETRY_PTR)
                ld bc,GEOMETRY_X+3
                add hl,bc
                ld a,(de)
                cp (hl)
                jp nz,.miss
                ; место в списке: DL_SENT + длина ≤ DL_CAP (иначе вывод заново заполнит список, как без кэша)
                ld a,(CACHE_NOW)
                ld e,a
                ld d,0
                ld hl,CACHE_LEN
                add hl,de
                add hl,de
                ld c,(hl)
                inc hl
                ld b,(hl)
                ld (CACHE_BYTES),bc
                ld hl,(DL_SENT)
                add hl,bc
                ld de,(DL_CAP)
                inc de
                or a
                sbc hl,de
                jp nc,.miss
                ; записи сдвигов: значения из геометрии против текущих (как TranslateCheck)
                ld a,VIDEO_CACHE_PAGE
                call Map2
                ld a,(CACHE_NOW)
                ld e,a
                ld d,0
                ld hl,CACHE_COUNT
                add hl,de
                ld a,(hl)
                ld ixl,a                        ; IXL — записей осталось
                ld a,e
                add a,a
                add a,a
                add a,a
                add a,#80
                ld (CACHE_BASE),a               ; старший байт слота в окне W2
                ld h,a
                ld l,0
                ld de,CACHE_DL_BYTES
                add hl,de                       ; HL → первая запись
                ld a,TRANSLATE_UNKNOWN
                ld (CUR_TX_H),a
                ld (CUR_TY_H),a
                ld a,ixl
                or a
                jr z,.send
                ; запись (CACHE_RECORD байт): +0 вид (0 — сдвиг X), +1 адрес значения (3 байта), +3 смещение слова в копии
                ; (ст. байт #FF — слово не выводилось); сверка трёх байт значения с текущим — без цикла
.record:        ld a,(hl)
                inc hl
                ld e,(hl)
                inc hl
                ld d,(hl)                       ; DE → значение
                inc hl
                push hl                         ; → смещение слова
                ld hl,CUR_TX
                or a
                jr z,.current
                ld hl,CUR_TY
.current:       ld c,0                          ; C = 1 — значение отличается от текущего (текущее = значение)
                ld a,(de)
                cp (hl)
                jr z,.same0
                ld (hl),a
                ld c,1
.same0:         inc de
                inc hl
                ld a,(de)
                cp (hl)
                jr z,.same1
                ld (hl),a
                ld c,1
.same1:         inc de
                inc hl
                ld a,(de)
                cp (hl)
                jr z,.same2
                ld (hl),a
                ld c,1
.same2:         pop hl
                ld b,(hl)                       ; B — мл. байт смещения слова
                inc hl
                ld a,(hl)                       ; ст. байт
                inc hl                          ; HL → следующая запись
                inc a
                jr z,.kept                      ; слово не выводилось (#FFFF)
                dec c
                jp nz,.miss                     ; выводилось, а значение совпало с текущим
                push hl
                ld l,b
                ld b,a
                ld a,(CACHE_BASE)
                dec a
                add a,b
                ld h,a                          ; HL → слово в копии
                dec de
                dec de                          ; DE → значение
                ld a,(de)
                ld (hl),a
                inc de
                inc hl
                ld a,(de)
                ld (hl),a
                inc de
                inc hl
                ld a,(de)
                and 1
                ld (hl),a                       ; бит 16 значения; код слова в копии прежний
                pop hl
                jr .next
.kept:          dec c
                jp z,.miss                      ; не выводилось, а значение отличается
.next:          dec ixl
                jr nz,.record
.send:          ld bc,(CACHE_BYTES)
                ld a,b
                or c
                jr z,.hit                       ; пустая подпрограмма
                ld hl,(DL_SENT)
                add hl,bc
                ld (DL_SENT),hl
                ld a,(CACHE_BASE)
                sub #80
                ld h,a
                ld l,0                          ; смещение слота в странице
                ld a,VIDEO_CACHE_PAGE
                call DmaToSpi
.hit:           scf
                ret
.miss:          or a
                ret

; Начало записи подпрограммы в кэш: слот CacheIndex недействителен до CaptureEnd, окно W2 — страница кэша, указатели
; слов и записей сдвигов — в начало слота. Портит AF, BC, DE, HL, окно W2.
CaptureBegin:   call CacheIndex
                ld (CACHE_NOW),a
                ld hl,CACHE_OK
                add hl,de
                ld (hl),0
                add a,a
                add a,a
                add a,a
                add a,#80
                ld (CAPTURE_BASE),a
                ld h,a
                ld l,0
                ld (CAPTURE_PTR),hl
                ld de,CACHE_DL_BYTES
                add hl,de
                ld (RECORD_PTR),hl
                ld a,CACHE_RECORDS
                ld (RECORD_LEFT),a
                ld a,VIDEO_CACHE_PAGE
                call Map2
                ld a,1
                ld (CAPTURE),a
                ret
                ASSERT CACHE_SLOT == #800

; Конец записи подпрограммы: копия годна, если запись не прерывалась и список не заполнился (DL_FULL). Тогда —
; длина, число записей сдвигов, структура кусков и маска видимых групп. Портит всё.
CaptureEnd:     ld a,(CAPTURE)
                or a
                ret z
                xor a
                ld (CAPTURE),a
                ld a,(DL_FULL)
                or a
                ret nz
                ld a,(CACHE_NOW)
                ld e,a
                ld d,0
                ld a,(RECORD_LEFT)
                ld b,a
                ld a,CACHE_RECORDS
                sub b
                ld hl,CACHE_COUNT
                add hl,de
                ld (hl),a
                ld hl,CACHE_LEN
                add hl,de
                add hl,de
                push hl
                ld hl,(DL_SENT)
                ld bc,(SUB_START)
                or a
                sbc hl,bc
                ex de,hl
                pop hl
                ld (hl),e
                inc hl
                ld (hl),d
                ; структура: число кусков, куски (область, первая строка, строк), маска групп
                ld a,(CACHE_NOW)
                ld e,a
                ld d,0
                call CacheStruct
                ex de,hl                        ; DE → структура копии
                ld hl,(GEOMETRY_PTR)
                ld bc,5
                add hl,bc
                ld a,(hl)
                ld (de),a                       ; число кусков
                or a
                jr z,.mask
                ld b,a
.piece:         inc hl
                inc de
                ld a,(hl)
                ld (de),a                       ; область
                inc hl
                inc de
                ld a,(hl)
                ld (de),a                       ; первая строка полос в области
                inc hl
                inc de
                ld a,(hl)
                ld (de),a                       ; строк
                inc hl
                inc hl
                inc hl                          ; сдвиг Y куска в кэш не пишется
                djnz .piece
.mask:          ld a,(CACHE_NOW)
                ld e,a
                ld d,0
                push de
                call CacheStruct
                ld de,CACHE_STRUCT_SIZE-1
                add hl,de
                ex de,hl
                ld hl,(GEOMETRY_PTR)
                ld bc,GEOMETRY_X+3
                add hl,bc
                ld a,(hl)
                ld (de),a                       ; маска видимых групп
                pop de
                ld hl,CACHE_OK
                add hl,de
                ld (hl),1
                ret

; Перестройка строки полос TILE_RR области TILE_REGION группы TILE_GROUP в потоках слоя TILE_LAYER прохода STREAM_KIND
; (StreamSplice). Строка rr меняет свои слова и состояния перед строками rr и rr + 1, а начала следующих строк лишь
; сдвигаются — поэтому годная копия этого слоя-прохода (обе полосы) теряет силу, только если группа видна в её
; структуре и у копии есть кусок этой области с первой строкой f и числом строк n при f − 1 ≤ rr ≤ f + n.
; Портит AF, BC, DE, HL.
CacheInvalidate:
                ld a,(TILE_GROUP)
                inc a
                ld b,a
                ld a,#80
.bit:           rlca
                djnz .bit
                ld (CACHE_GROUP_BIT),a
                ld a,(STREAM_KIND)
                add a,a
                add a,a
                ld e,a                          ; проход·4 — слот полосы 0
                ld a,(TILE_LAYER)
                or a
                jr nz,.layer
                inc e                           ; слой 0
.layer:         call .slot
                inc e
                inc e                           ; слот полосы 1
.slot:          ld d,0
                ld hl,CACHE_OK
                add hl,de
                ld a,(hl)
                or a
                ret z                           ; копии нет
                push de
                push hl
                call CacheStruct                ; HL → структура копии
                push hl
                ld de,CACHE_STRUCT_SIZE-1
                add hl,de
                ld a,(CACHE_GROUP_BIT)
                and (hl)
                pop hl
                jr z,.kept                      ; группа не видна
                ld a,(hl)                       ; кусков
                or a
                jr z,.kept
                ld b,a
.piece:         inc hl
                ld a,(TILE_REGION)
                cp (hl)
                inc hl
                jr nz,.other                    ; другая область
                ld a,(TILE_RR)
                inc a
                cp (hl)
                jr c,.other                     ; rr + 1 < f
                dec a
                ld c,a                          ; rr
                ld a,(hl)
                inc hl
                add a,(hl)                      ; f + n
                dec hl
                cp c
                jr nc,.stale                    ; rr ≤ f + n
.other:         inc hl                          ; HL → число строк куска
                djnz .piece
.kept:          pop hl
                pop de
                ret
.stale:         pop hl
                pop de
                ld (hl),0                       ; копия не годна
                ret

; Запись SUB_TABLE: (проход·2 + полоса)·2 + (слой = 0) → HL. Портит AF, B, DE.
SubIndex:       ld a,(EMIT_PASS)
                add a,a
                ld b,a
                ld a,(EMIT_BAND)
                add a,b
                add a,a
                ld b,a
                ld a,(TILE_LAYER)
                or a
                ld a,b
                jr nz,.layer
                inc a
.layer:         add a,a
                ld e,a
                ld d,0
                ld hl,SUB_TABLE
                add hl,de
                ret

; Основная часть прохода EMIT_PASS: полосы растра — ножницы, фон, передний слой (вызовы подпрограмм).
MainPass:       xor a
                ld (EMIT_BAND),a
.band:          call BandScissor
                ld a,(EMIT_PASS)
                ld hl,RING_READY
                or a
                jr nz,.back
                or (hl)
                call nz,RingEmit                ; проход 0: фон — кольцо (его тайлы низкого прохода не в потоках)
.back:          ld a,1
                ld (TILE_LAYER),a
                call .layer
                xor a
                ld (TILE_LAYER),a
                call .layer
                ld hl,EMIT_BAND
                inc (hl)
                ld a,(BAND_COUNT)
                cp (hl)
                jr nz,.band
                ret
.layer:         call SubIndex
                ld e,(hl)
                inc hl
                ld d,(hl)
                ld a,d
                and e
                inc a
                ret z                           ; подпрограммы нет
                ex de,hl
                ld de,#1D00
                jp EmitWord                     ; CALL: проходы A и B — пары вершин подпрограммы (RowPair)

; Полосы растра: BAND_COUNT (1 или 2); у полосы — первая строка M72, последняя+1 и скроллы.
BandsSetup:     ld hl,(RASTER_ROW)
                ld a,h
                or a
                jr nz,.top                      ; #FFFF — растра нет
                ld a,l
                or a
                jr z,.after                     ; растр на строке 0
                ld (BAND1_TOP),a
                ld (BAND0_BOTTOM),a
                xor a
                ld (BAND0_TOP),a
                ld hl,TOP_SCROLL
                ld de,BAND0_SCROLL
                ld bc,8
                ldir
                ld hl,AFTER_RASTER
                ld de,BAND1_SCROLL
                ld bc,8
                ldir
                ld a,2
                ld (BAND_COUNT),a
                ret
.after:         ld hl,AFTER_RASTER
                jr .single
.top:           ld hl,TOP_SCROLL
.single:        ld de,BAND0_SCROLL
                ld bc,8
                ldir
                xor a
                ld (BAND0_TOP),a
                ld (BAND0_BOTTOM),a             ; 0 — до строки 256
                inc a
                ld (BAND_COUNT),a
                ret

; Полоса EMIT_BAND: BAND_TOP, BAND_BOTTOM (0 — 256), BAND_SCROLL_PTR.
BandSelect:     ld a,(EMIT_BAND)
                or a
                jr nz,.second
                ld hl,BAND0_SCROLL
                ld a,(BAND0_TOP)
                ld c,a
                ld a,(BAND0_BOTTOM)
                ld b,a
                jr .set
.second:        ld hl,BAND1_SCROLL
                ld a,(BAND1_TOP)
                ld c,a
                ld b,0
.set:           ld (BAND_SCROLL_PTR),hl
                ld a,c
                ld (BAND_TOP),a
                ld a,b
                ld (BAND_BOTTOM),a
                ret

; Ножницы полосы EMIT_BAND (и её выбор).
BandScissor:    call BandSelect
                ld a,(BAND_TOP)
                ld l,a
                ld h,0
                ld d,h
                ld e,l
                add hl,hl
                add hl,de                       ; y = первая·3
                ld de,#1B00                     ; SCISSOR_XY 0,y
                call EmitWord
                ld a,(BAND_BOTTOM)
                ld l,a
                ld h,0
                or a
                jr nz,.height
                inc h
.height:        ld a,(BAND_TOP)
                ld e,a
                ld d,0
                or a
                sbc hl,de
                ld d,h
                ld e,l
                add hl,hl
                add hl,de
                ld de,#1C40                     ; SCISSOR_SIZE 1024,высота·3
                jp EmitWord

; Геометрия слоя TILE_LAYER прохода EMIT_PASS в текущей полосе: LAYER_PASS; Z — у слоя-прохода нет непустых
; потоков (выводить нечего). Иначе NZ, скроллы LAYER_SY и LAYER_SX, GEOMETRY_PTR — запись геометрии (куски строк
; со сдвигами Y, видимые группы со сдвигами X): она хранится в GEOMETRY по слою·2 + полосе и пересчитывается
; только при смене скролла или границ полосы. Портит всё, окно W2.
LayerGeometry:  ld a,(TILE_LAYER)
                add a,a
                ld hl,EMIT_PASS
                add a,(hl)
                ld (LAYER_PASS),a               ; слой·2 + проход
                ld e,a
                ld d,0
                ld hl,LAYER_STREAMS
                add hl,de
                ld a,(hl)
                ld hl,LAYER_STREAMS+4
                add hl,de
                or (hl)
                ret z
                ld hl,(BAND_SCROLL_PTR)
                ld a,(TILE_LAYER)
                add a,a
                add a,a
                ld e,a
                add hl,de
                ld e,(hl)
                inc hl
                ld a,(hl)
                and 1
                ld d,a
                inc hl
                ld (LAYER_SY),de                ; скролл Y & 511
                ld e,(hl)
                inc hl
                ld a,(hl)
                and 1
                ld d,a
                ld (LAYER_SX),de                ; скролл X & 511
                ; запись геометрии: GEOMETRY + (слой·2 + полоса)·GEOMETRY_SIZE
                ld a,(TILE_LAYER)
                add a,a
                ld hl,EMIT_BAND
                add a,(hl)
                ld l,a
                ld h,0
                ld de,GEOMETRY_SIZE
                call MultiplyHLDE
                ld de,GEOMETRY
                add hl,de
                ld (GEOMETRY_PTR),hl
                ; строки: ключ — sy, первая и последняя строки полосы
                ld de,(LAYER_SY)
                ld a,(hl)                       ; +0 признак годности
                or a
                jr z,.rowsNew
                inc hl
                ld a,(hl)
                cp e
                jr nz,.rowsNew
                inc hl
                ld a,(hl)
                cp d
                jr nz,.rowsNew
                inc hl
                ld a,(BAND_TOP)
                cp (hl)
                jr nz,.rowsNew
                inc hl
                ld a,(BAND_BOTTOM)
                cp (hl)
                jr z,.rowsReady
.rowsNew:       call RowsSetup
.rowsReady:     ; столбцы: ключ — sx
                ld hl,(GEOMETRY_PTR)
                ld de,GEOMETRY_X
                add hl,de
                ld de,(LAYER_SX)
                ld a,(hl)
                or a
                jr z,.columnsNew
                inc hl
                ld a,(hl)
                cp e
                jr nz,.columnsNew
                inc hl
                ld a,(hl)
                cp d
                jr z,.columnsReady
.columnsNew:    call ColumnsSetup
.columnsReady:  or 1                            ; NZ — потоки есть
                ret

; Слой TILE_LAYER, проход EMIT_PASS, текущая полоса (геометрия готова — LayerGeometry): видимые группы и куски
; строк — сначала потоки картинок, затем полос. Пустые группы и области (маски непустых потоков) пропускаются
; сразу. На входе и выходе W1 — страница состояния; окно W2 не трогается.
LayerEmit:      ld a,1
                ld (EMIT_FAMILY),a              ; сначала картинки
.family:        ld a,(LAYER_PASS)
                ld e,a
                ld d,0
                ld hl,LAYER_STREAMS
                ld a,(EMIT_FAMILY)
                or a
                jr z,.familyCount
                ld hl,LAYER_STREAMS+4
.familyCount:   add hl,de
                ld a,(hl)
                or a
                jp z,.nextFamily                ; потоков семьи нет
                ld a,(EMIT_FAMILY)
                or a
                ld a,VIDEO_STATE_PAGE
                ld hl,#4000
                ld de,STREAM_LOC
                jr z,.familyPage
                ld a,VIDEO_IMAGE_PAGE
                ld hl,#4000+IHEADER_OFFSET
                ld de,ISTREAM_LOC
.familyPage:    ld (HEADER_BASE),hl
                ld (LOC_TABLE),de
                call Map1                       ; W1 — заголовки потоков семьи
                ld a,(LAYER_PASS)
                ld c,a
                add a,a
                add a,c
                ld c,a                          ; слой-проход·3
                ld a,(EMIT_FAMILY)
                add a,a
                add a,a
                ld b,a
                add a,a
                add a,b                         ; семья·12
                add a,c
                ld (FAMILY_REGION0),a           ; маска групп области 0 семьи и слоя-прохода в REGION_GROUPS
                ; куски полосы → PIECE_WORK (PIECE_ENTRY байт на кусок): индекс маски групп области в REGION_GROUPS;
                ; адрес заголовка потока группы 0 области (HEADER_BASE + номер·HEADER_SIZE, номер = (слой-проход·3 +
                ; область)·8); смещения в заголовке начала первой строки и конца последней (строка·2), состояний перед
                ; ними (HEADER_PAL + строка); адрес места потока группы 0 в таблице мест семьи (LOC_TABLE); адрес
                ; VERTEX_TRANSLATE_Y куска (3 байта в записи геометрии).
                ld hl,(GEOMETRY_PTR)
                ld de,5
                add hl,de
                ld a,(hl)
                ld (PIECE_COUNT),a
                inc hl                          ; HL → первый кусок (6 байт)
                or a
                jr z,.piecesReady
                ld b,a
                ld ix,PIECE_WORK
.pieceSetup:    push bc
                ld a,(LAYER_PASS)
                ld c,a
                add a,a
                add a,c
                add a,(hl)                      ; + область
                add a,a
                add a,a
                add a,a                         ; A = номер потока группы 0 (не больше 88)
                push hl
                ld l,a
                ld h,0
                ld e,l
                ld d,h
                add hl,hl
                add hl,de                       ; номер·3
                push hl
                add hl,hl
                add hl,hl
                ld e,l
                ld d,h
                add hl,hl
                add hl,de                       ; номер·36
                ld de,(HEADER_BASE)
                add hl,de
                ld (ix+1),l
                ld (ix+2),h
                pop hl
                ld de,(LOC_TABLE)
                add hl,de
                ld (ix+7),l
                ld (ix+8),h
                pop hl
                ld c,(hl)                       ; область
                inc hl
                ld a,(hl)                       ; первая строка полос в области
                inc hl
                ld b,(hl)                       ; строк
                inc hl
                ld e,a
                add a,a
                ld (ix+3),a                     ; первая·2
                ld a,e
                add a,b
                ld d,a
                add a,a
                ld (ix+4),a                     ; (первая + строк)·2
                ld a,e
                add a,HEADER_PAL
                ld (ix+5),a
                ld a,d
                add a,HEADER_PAL
                ld (ix+6),a
                ld (ix+9),l
                ld (ix+10),h                    ; VERTEX_TRANSLATE_Y куска
                inc hl
                inc hl
                inc hl                          ; следующий кусок
                ld a,(FAMILY_REGION0)
                add a,c
                ld (ix+0),a                     ; маска групп области куска
                ld de,PIECE_ENTRY
                add ix,de
                pop bc
                djnz .pieceSetup
.piecesReady:   ; куски снаружи, группы внутри: VERTEX_TRANSLATE_Y — раз на кусок, сдвиг X — при смене области группы
                ; (разные куски не пересекаются, соседние группы куска идут по порядку — картинка та же); группы —
                ; только видимые с потоком в области куска
                ld a,(PIECE_COUNT)
                or a
                jp z,.familyEnd
                ld (PIECES_LEFT),a
                ld hl,(GEOMETRY_PTR)
                ld de,GEOMETRY_X+3
                add hl,de
                ld a,(hl)
                ld (GROUPS_GEOMETRY),a          ; маска видимых групп
                inc hl
                ld (GROUP_TX_BASE),hl           ; сдвиги X групп по 3 байта
                ld ix,PIECE_WORK
.piece:         ld e,(ix+0)
                ld d,0
                ld hl,REGION_GROUPS
                add hl,de
                ld a,(GROUPS_GEOMETRY)
                and (hl)
                jr z,.nextPiece
                ld (GROUPS_LEFT),a
                ld hl,(GROUP_TX_BASE)
                ld (GROUP_TX_PTR),hl
                ld l,(ix+1)
                ld h,(ix+2)
                ld (BURST_HEADER),hl            ; заголовок потока группы 0 области куска
                ld l,(ix+7)
                ld h,(ix+8)
                ld (BURST_LOC),hl
.group:         ld hl,GROUPS_LEFT
                srl (hl)
                call c,PieceBurst
                ld a,(GROUPS_LEFT)
                or a
                jr z,.nextPiece
                ld hl,(GROUP_TX_PTR)
                inc hl
                inc hl
                inc hl
                ld (GROUP_TX_PTR),hl
                ld hl,(BURST_LOC)
                inc hl
                inc hl
                inc hl
                ld (BURST_LOC),hl
                ld hl,(BURST_HEADER)
                ld de,HEADER_SIZE
                add hl,de
                ld (BURST_HEADER),hl
                jr .group
.nextPiece:     ld de,PIECE_ENTRY
                add ix,de
                ld hl,PIECES_LEFT
                dec (hl)
                jr nz,.piece
.familyEnd:     xor a
                call FlipCheck                  ; к следующей семье — матрица без отражения
.nextFamily:    ld hl,EMIT_FAMILY
                ld a,(hl)
                or a
                jr z,.done
                dec (hl)
                jp .family
.done:          ld a,VIDEO_STATE_PAGE
                jp Map1

; Матрица подпрограммы: A — нужное отражение семьи EMIT_FAMILY (0/1), CUR_FLIP — текущее; при смене — слова
; BITMAP_TRANSFORM_A и C (TILE_TRANSFORMS или IMAGE_TRANSFORMS). Список заполнен (DL_FULL) — матрица не меняется:
; сброс отражения перед RETURN (SubEmit) выводится всегда. Портит AF, BC, DE, HL.
FlipCheck:      ld hl,CUR_FLIP
                cp (hl)
                ret z
                ld b,a
                ld a,(DL_FULL)
                or a
                ret nz
                ld (hl),b
                ld hl,TILE_TRANSFORMS
                ld a,(EMIT_FAMILY)
                or a
                jr z,.family
                ld hl,IMAGE_TRANSFORMS
.family:        ld a,b
                or a
                jr z,.words
                ld de,8
                add hl,de
.words:         ld b,2
                jp EmitTable

; Кусок IX (запись PIECE_WORK) группы: заголовок потока BURST_HEADER, место потока BURST_LOC, сдвиг X группы
; GROUP_TX_PTR (ведёт цикл групп LayerEmit). Пакет строк потока, если они есть. Перед пакетом — VERTEX_TRANSLATE_X
; группы и VERTEX_TRANSLATE_Y куска (при смене), состояние перед первой непустой строкой куска (PALETTE_SOURCE при
; смене палитры, матрица семьи при смене отражения; бит выбора #20 — строка сама выбрала своё начало, пустые
; строки перед ней ничего не выводят); после пакета текущее — состояние после последней строки.
; Сохраняет IX; портит остальное.
PieceBurst:     ld hl,(BURST_HEADER)
                ld e,(ix+3)
                ld d,0
                add hl,de
                ld c,(hl)
                inc hl
                ld b,(hl)                       ; BC — начало первой строки куска
                ld hl,(BURST_HEADER)
                ld e,(ix+4)
                add hl,de
                ld e,(hl)
                inc hl
                ld d,(hl)                       ; DE — конец последней строки
                ex de,hl
                or a
                sbc hl,bc
                ret z                           ; строк куска в потоке нет
                ld (BURST_BYTES),hl
                ld (BURST_START),bc
                ld hl,(GROUP_TX_PTR)
                ld (CAPTURE_SOURCE),hl          ; адрес значения — для записи сдвигов копии
                ld e,(hl)
                inc hl
                ld d,(hl)
                inc hl
                ld c,(hl)
                ld hl,CUR_TX
                ld a,#2B
                call TranslateCheck
                ld l,(ix+9)
                ld h,(ix+10)
                ld (CAPTURE_SOURCE),hl
                ld e,(hl)
                inc hl
                ld d,(hl)
                inc hl
                ld c,(hl)
                ld hl,CUR_TY
                ld a,#2C
                call TranslateCheck
                ; первая непустая строка куска: начала строк k и k + 1 различаются
                ld hl,(BURST_HEADER)
                ld e,(ix+3)
                ld d,0
                add hl,de
                ld a,(ix+5)
                ld (STATE_OFFSET),a             ; HEADER_PAL + строка
.scan:          ld e,(hl)
                inc hl
                ld d,(hl)
                inc hl
                ld a,(hl)
                cp e
                jr nz,.found
                inc hl
                ld a,(hl)
                dec hl
                cp d
                jr nz,.found
                ld a,(STATE_OFFSET)
                inc a
                ld (STATE_OFFSET),a
                cp (ix+6)
                jr c,.scan
.found:         ld hl,(BURST_HEADER)
                ld a,(STATE_OFFSET)
                ld e,a
                ld d,0
                add hl,de
                ld a,(hl)                       ; состояние перед первой непустой строкой
                cp UNKNOWN
                jr nz,.stateKnown
                xor a
                call FlipCheck
                jr .after
.stateKnown:    push af
                and 15
                ld hl,CUR_PAL
                cp (hl)
                jr z,.flipBefore
                ld (hl),a
                add a,16
                add a,a
                ld h,a
                ld l,0
                ld de,#2A00
                call EmitWord                   ; PALETTE_SOURCE (набор·16 + палитра)·512
.flipBefore:    pop af
                rrca
                rrca
                rrca
                rrca
                and 1
                call FlipCheck
.after:         ld hl,(BURST_HEADER)
                ld e,(ix+6)
                ld d,0
                add hl,de
                ld a,(hl)                       ; состояние после последней строки
                cp UNKNOWN
                jr z,.burst
                ld b,a
                and 15
                ld (CUR_PAL),a
                ld a,b
                rrca
                rrca
                rrca
                rrca
                and 1
                ld (CUR_FLIP),a
.burst:         ld hl,(BURST_LOC)
                ld a,(hl)                       ; страница потока
                inc hl
                ld e,(hl)
                inc hl
                ld d,(hl)                       ; смещение потока в странице
                ld hl,(BURST_START)
                add hl,de
                ld bc,(BURST_BYTES)
                jp DlBurst
                ASSERT HEADER_SIZE == 36         ; группа·36 и номер·36 — сложениями

; HL·DE → HL (малые множители).
MultiplyHLDE:   ld b,h
                ld c,l
                ld hl,0
                ld a,b
                or c
                ret z
.add:           add hl,de
                dec bc
                ld a,b
                or c
                jr nz,.add
                ret

; Куски строк слоя в полосе → запись геометрии (GEOMETRY_PTR): ключ и PIECES.
RowsSetup:      ld hl,(GEOMETRY_PTR)
                ld (hl),1
                inc hl
                ld de,(LAYER_SY)
                ld (hl),e
                inc hl
                ld (hl),d
                inc hl
                ld a,(BAND_TOP)
                ld (hl),a
                inc hl
                ld a,(BAND_BOTTOM)
                ld (hl),a
                inc hl
                ld (PIECE_TABLE),hl             ; +5: число кусков, куски по 6 байт
                ld (hl),0
                ; base_y = (−128 − sy) & 511; первая строка r0 = ((top − base) & 511) >> 3
                ld hl,(LAYER_SY)
                ld de,128
                add hl,de
                ex de,hl
                ld hl,0
                or a
                sbc hl,de
                ld a,h
                and 1
                ld h,a
                ld (LAYER_BASE_Y),hl
                ex de,hl
                ld a,(BAND_TOP)
                ld l,a
                ld h,0
                or a
                sbc hl,de
                call Shift9By3
                ld (ROW_FIRST),a
                call RowY
                ld (ROW_FIRST_Y),hl
                ld a,(BAND_BOTTOM)
                ld e,a
                ld d,0
                or a
                jr nz,.bottom
                inc d
.bottom:        ex de,hl
                dec hl
                ld de,(ROW_FIRST_Y)
                ; y0 первой строки — со знаком: он равен нулю только когда sy кратен 8, иначе −7…−1
                ; (строка полос начинается выше верха полосы растра). Беззнаковое вычитание тогда даёт
                ; заём, хотя строк полно, и полоса слоя за кадр не выводилась вовсе: в титрах слой
                ; сдвигается по половине пикселя за кадр, и текст появлялся 2 кадра из 16 — это и было
                ; мигание титров (замер 2026-09-20). Заём при отрицательном y0 признаком пустоты не считаем.
                ld a,d                          ; #FF — y0 отрицателен
                or a                            ; заодно снимает перенос перед sbc
                sbc hl,de                       ; последняя строка полосы − y0
                jr nc,.enough
                or a
                ret z                           ; y0 неотрицателен и ниже полосы — строк нет
.enough:        call Rows8
                cp 34
                jr c,.rows
                ld a,33
.rows:          ld (ROW_COUNT),a
                jp PiecesSetup

; Видимые группы слоя и их VERTEX_TRANSLATE_X → запись геометрии: ключ (годна, sx), маска и сдвиги групп — запись
; sx таблицы VIDEO_COLUMN_PAGE (v30z80_video_assets.column_table: те же вычисления заранее для каждого sx). Окно W2 —
; страница таблицы. Портит всё.
ColumnsSetup:   ld hl,(GEOMETRY_PTR)
                ld de,GEOMETRY_X
                add hl,de
                ld (hl),1
                inc hl
                ld de,(LAYER_SX)
                ld (hl),e
                inc hl
                ld (hl),d
                inc hl
                push hl                         ; → маска групп
                ex de,hl                        ; HL = sx
                ld d,h
                ld e,l
                add hl,hl
                add hl,hl
                add hl,hl
                ld b,h
                ld c,l
                add hl,hl
                add hl,bc
                add hl,de                       ; sx·25
                ld a,h
                or #80
                ld h,a
                ld a,VIDEO_COLUMN_PAGE
                call Map2
                pop de
                ld bc,COLUMN_ENTRY
                ldir
                ret
                ASSERT COLUMN_ENTRY == 25 && GEOMETRY_SIZE == GEOMETRY_X+3+COLUMN_ENTRY

; ((HL & 511) >> 3) & 63 → A.
Shift9By3:      ld a,h
                and 1
                ld h,a
                srl h
                rr l
                srl h
                rr l
                srl h
                rr l
                ld a,l
                and 63
                ret

; (HL >> 3) + 1 → A (HL < 512).
Rows8:          srl h
                rr l
                srl h
                rr l
                srl h
                rr l
                ld a,l
                inc a
                ret

; y строки A: ((8·A + base_y + 8) & 511) − 8 → HL.
RowY:           ld l,a
                ld h,0
                add hl,hl
                add hl,hl
                add hl,hl
                ld de,(LAYER_BASE_Y)
Wrap9:          add hl,de
                ld de,8
                add hl,de
                ld a,h
                and 1
                ld h,a
                ld de,-8
                add hl,de
                ret

; C:DE += HL·B.
AddTimes:       ld a,b
                or a
                ret z
.add:           ex de,hl
                push de
                add hl,de
                ex de,hl
                pop hl
                ld a,c
                adc a,0
                ld c,a
                djnz .add
                ret

; Слово VERTEX_TRANSLATE (A — код) со значением C:DE, если оно отличается от (HL) — текущего. Во время записи
; подпрограммы в кэш вызов записывается (CaptureTranslate: адрес значения — CAPTURE_SOURCE). Портит всё.
TranslateCheck: push af
                ld a,(hl)
                cp e
                jr nz,.emit
                inc hl
                ld a,(hl)
                cp d
                jr nz,.emitH
                inc hl
                ld a,(hl)
                cp c
                jr nz,.emitHH
                pop af
                ld hl,#FFFF                     ; слово не выводится
                jp CaptureTranslate
.emit:          inc hl
.emitH:         inc hl
.emitHH:        dec hl
                dec hl
                ld (hl),e
                inc hl
                ld (hl),d
                inc hl
                ld (hl),c
                pop af
                push de                         ; младшее слово
                ld hl,(DL_SENT)
                ld de,(SUB_START)
                or a
                sbc hl,de                       ; смещение слова в подпрограмме
                call CaptureTranslate
                pop hl                          ; HL = младшее слово
                ld d,a
                ld a,c
                and 1
                ld e,a
                jp EmitWord

; Вызов TranslateCheck — в записи сдвигов копии (RECORD_PTR, окно W2): вид (код − #2B: 0 — X, 1 — Y), адрес
; значения CAPTURE_SOURCE, смещение слова HL (#FFFF — не выводилось). Записей больше нет места — запись копии
; прекращается. Без записи в кэш — ничего. Сохраняет A, BC.
CaptureTranslate:
                push af
                ld a,(CAPTURE)
                or a
                jr z,.done
                ld a,(RECORD_LEFT)
                or a
                jr z,.overflow
                dec a
                ld (RECORD_LEFT),a
                ex de,hl                        ; DE — смещение
                ld hl,(RECORD_PTR)
                pop af
                push af
                sub #2B
                ld (hl),a
                inc hl
                ld a,(CAPTURE_SOURCE)
                ld (hl),a
                inc hl
                ld a,(CAPTURE_SOURCE+1)
                ld (hl),a
                inc hl
                ld (hl),e
                inc hl
                ld (hl),d
                inc hl
                ld (RECORD_PTR),hl
.done:          pop af
                ret
.overflow:      xor a
                ld (CAPTURE),a
                pop af
                ret

; Куски видимых строк полос (строки карты [ROW_FIRST, +ROW_COUNT); строка полос — две строки карты) по
; модулю 32 внутри областей — один раз на слой полосы: PIECES — область, первая строка полос в
; области, строк полос, VERTEX_TRANSLATE_Y (3 байта).
PiecesSetup:    xor a
                ld (PIECE_WRAP),a               ; куски до склейки карты поправки не требуют
                ld a,(ROW_FIRST)
                srl a
                ld (PIECE_FIRST),a
                ld a,(ROW_FIRST)
                ld hl,ROW_COUNT
                add a,(hl)
                dec a
                srl a                           ; последняя строка полос (без переноса по модулю 32)
                ld hl,PIECE_FIRST
                sub (hl)
                inc a
                ld (PIECE_LEFT),a
                ld hl,(PIECE_TABLE)
                ld (hl),0
                inc hl
                ld (PIECE_PTR),hl
.piece:         ld a,(PIECE_LEFT)
                or a
                ret z
                ld a,(PIECE_FIRST)
                ld e,a
                ld d,0
                ld hl,STRIP_REGION
                add hl,de
                ld c,(hl)                       ; область
                ld hl,STRIP_INDEX
                add hl,de
                ld b,(hl)                       ; первая строка полос в области
                ld hl,REGION_ROWS
                ld e,c
                add hl,de
                ld a,(hl)
                sub b                           ; строк полос до конца области
                ld e,a
                ld a,(PIECE_LEFT)
                cp e
                jr c,.limit
                ld a,e
.limit:         ld hl,(PIECE_PTR)
                ld (hl),c
                inc hl
                ld (hl),b
                inc hl
                ld (hl),a
                inc hl
                ld (PIECE_PTR),hl
                ld (PIECE_ROWS),a
                ld a,c
                ld (TILE_REGION),a
                ; w' = (y − (8r − 128 − sy)) / 512 для строки карты r = 2·строка полос;
                ; T_y = 8192·j + TY[sy] + 24576·w'
                ; Поправка на высоту карты нужна кускам, которые в окне идут **после** её склейки:
                ; у них строки взяты с начала карты, а показываются ниже конца. Прежде признак считался
                ; как (y строки − развёрнутая позиция) >> 9, но эта разница равна 512 и у первого куска
                ; окна, которому поправка не нужна: замер 2026-09-20 — в титрах она уводила весь слой за
                ; экран (VERTEX_TRANSLATE_Y +22864 вместо −1712, текст пропадал 14 кадров из 16), а нижней
                ; панели счёта, чей второй кусок и правда за склейкой, та же поправка нужна (+24576 ставит
                ; её на строку 720). Теперь признак — флаг PIECE_WRAP, взводимый при переходе через строку 31.
                ld a,(PIECE_WRAP)
                ld b,a
                ld hl,(LAYER_SY)
                add hl,hl
                ld de,TY_TABLE
                add hl,de
                ld e,(hl)
                inc hl
                ld d,(hl)
                ld a,d
                or e
                add a,#FF
                sbc a,a
                ld c,a                          ; знак TY: #FF, у нуля (sy = 384 — таблица по модулю 512) — 0
                ld a,(TILE_REGION)
                add a,a
                add a,a
                add a,a
                add a,a
                add a,a
                add a,d
                ld d,a
                ld a,c
                adc a,0
                ld c,a
                ld hl,24576                     ; высота карты: 512 тайловых пикселей = три области FT812
                call AddTimes
                ld hl,(PIECE_PTR)
                ld (hl),e
                inc hl
                ld (hl),d
                inc hl
                ld (hl),c
                inc hl
                ld (PIECE_PTR),hl
                ld hl,(PIECE_TABLE)
                inc (hl)
                ld a,(PIECE_ROWS)
                ld b,a
                ld a,(PIECE_LEFT)
                sub b
                ld (PIECE_LEFT),a
                ld a,(PIECE_FIRST)
                add a,b
                cp 32
                jr c,.sameLap
                ld hl,PIECE_WRAP
                ld (hl),1                       ; дальше куски идут за склейкой карты
.sameLap:       and 31
                ld (PIECE_FIRST),a
                jp .piece

; --- таблицы и переменные ------------------------------------------------------------------------------------
; Заголовок display list: масштаб 8/5 (A = E = 160), BEGIN BITMAPS.
; Очистки кадра здесь нет. Кольцо фона непрозрачно (все 256 записей его палитры с альфой 15, прозрачных
; текселей нет вовсе) и двумя полосами накрывает все 768 строк на всю ширину, поэтому чёрный CLEAR под
; ним не виден ни одним пикселем, а стоил он 128 тактов каждой строке развёртки (1024 px / 8) — около
; 10 % потолка строки. Замер 22.09.2026: пик строки на уровне 2 — 1331 такт при пределе 1300…1445, из
; них очистка 128; это и есть разрывы строк, о которых сообщил тестировщик. Очистку ставит сам код
; кадра, когда кольца в списке не будет (RING_READY = 0 — кольцо ещё не записано или сборка
; RTYPE_NO_RING; выключенное видео — VIDEO_OFF_SNAP).
DL_HEADER:      DD #02000000                    ; CLEAR_COLOR_RGB 0,0,0 — цвет очистки, когда она нужна
                DD #150000A0                    ; BITMAP_TRANSFORM_A 160
                DD #190000A0                    ; BITMAP_TRANSFORM_E 160
                DD #1F000001                    ; BEGIN BITMAPS
DL_HEADER_END:
; Затемнение (HostVideoFade): состояние, влияющее на прямоугольник, ставится заново; COLOR_A — слово
; со смещением FADE_ALPHA_AT; вершины в 1/8 физического пикселя: весь экран 1024×768.
FADE_WORDS:     DD #27000003                    ; VERTEX_FORMAT 3
                DD #2B000000                    ; VERTEX_TRANSLATE_X 0
                DD #2C000000                    ; VERTEX_TRANSLATE_Y 0
                DD #1B000000                    ; SCISSOR_XY 0,0
                DD #1C400300                    ; SCISSOR_SIZE 1024,768
                DD #04000000                    ; COLOR_RGB 0,0,0
                DD #10000000                    ; COLOR_A 0
                DD #1F000009                    ; BEGIN RECTS
                DD #40000000                    ; VERTEX2F 0,0
                DD #50001800                    ; VERTEX2F 8192,6144
                DD #21000000                    ; END
                DD #00000000                    ; DISPLAY
FADE_WORDS_END:
                ASSERT FADE_ALPHA_AT == 6*4
FADE_ALPHAS:    DB 36, 72, 108, 144, 180, 216, 255, 0
; Проход тайла по слою и режиму приоритета (атрибут >> 6): 0 — низкий, 1 — высокий. Фон группы 2 — высокий
; (2026-09-25, жалоба пользователя «Z-index двигателя корабля неверный» на этапе 3): у M72 такой тайл рисуется в
; заднем проходе (BG_LAYER1 — все перья), но перья 1…15 закрывают спрайты (BG_PRIORITY, MAME m72_v.cpp); прежде (0)
; спрайты шли поверх него — двигатель линкора этапа 3 поверх корпуса, спрайты этапа 8 поверх фона. Перо 0 фона в
; ячейках прозрачно (пак: rtype_data.py, маска пера 0 набора фона — ячейками фон выводится только в высоком проходе,
; низкий — кольцо), под тайлом — кольцо. Аудит всей игры (vdac2p_priority_audit.py, автоогонь 70 000 кадров и случайный
; ввод): расхождений источника пикселя с аркадой нет. Задний проход переднего слоя поверх таких перьев (у M72 он
; поверх, здесь фон лёг бы сверху) в игре не встречается.
PASS_TABLE:     DB 0, 1, 1, 1                   ; передний слой
                DB 0, 1, 1, 1                   ; фон
WIDTH16:        DW 16, 32, 64, 128
CELLS_BY_LOG:   DB 1, 2, 4, 8
; Матрица отражения полос и картинок (масштаб 8/5): BITMAP_TRANSFORM_A и C; пара слов без отражения
; (A = 160, C = 0), затем зеркальная (A = −160, C = ширина·256 − 1): при выборке по центрам пикселей —
; точное зеркало неотражённого вывода (сдвиг 1/256 меньше шага координат 1/16). Без «− 1» выборка по
; углу пикселя (эмулятор FT812 в Unreal) брала строку (столбец) за краем ячейки: у спрайта 27×60
; строка 30 — уже проход B, над отражённым спрайтом появлялась тонкая линия. Вертикальное отражение
; тайла собрано в полосе или картинке. Пары без отражения у полос и картинок одинаковы (SubEmit).
TILE_TRANSFORMS:
                DD #150000A0, #17000000
                DD #1501FF60, #17000000+TILE_CELL_W*256-1
IMAGE_TRANSFORMS:
                DD #150000A0, #17000000
                DD #1501FF60, #17000000+IMAGE_WIDTH*256-1
; Матрица спрайтов (SpriteTransform): по оси — режимы 0 масштаб 8/5 и 1 его зеркало; пара слов — масштаб и
; сдвиг. Зеркало ячейки 27×30 при 8/5 — сдвиг 43·160 по X (выборка столбца 42 − k = (160·(42 − k) + 80) >> 8
; при центрах пикселей — точное зеркало неотражённого вывода; 43 — ширина ячейки на экране) и 30·256 − 1 по Y
; (там «− 1» ничего не меняет, а выборка по углу пикселя эмулятора в Unreal без него брала строку 30 — уже
; проход B, над отражённым спрайтом была тонкая линия).
SPRITE_TRANSFORMS:
                DD #150000A0, #17000000
                DD #1501FF60, #17000000+43*160
                DD #190000A0, #1A000000
                DD #1901FF60, #1A000000+SPRITE_CELL_H*256-1
                INCLUDE "video.inc"
                INCLUDE "rtype_ring.inc"

VIDEO_READY     DB 0
SKIP_FRAMES     DB 0                    ; младший байт REG_FRAMES прошлого шага с выводом (HostVideoSkip)
SKIP_LAG        DB 0                    ; долг в кадрах развёртки
SKIP_RUN        DB 0                    ; шагов без вывода подряд
VIDEO_HANDLES   DB 0
VIDEO_UPLOADED  DB 0
VIDEO_OFF_SNAP  DB 0
VIDEO_FORCE     DB 0
TITLE_GUARD     DB 0                    ; кадров, пока картинки — только первые GUARD_IMAGES
RING_ON         DB 0                    ; 1 — родные тайлы фона прочитаны: фон выводит кольцо (v30z80_ring.asm)
SLOT_HIGH       DB 0                    ; старший байт слова кода тайла у SlotRead (маска кольца)
SWAP_PENDING    DB 1                    ; запрошенный DLSWAP ещё не подтверждён (FadeWaitSwap)
; Видимость позиций в двух последних display list (A — последний, B — предыдущий): по слою 4 байта строк
; полос (бит на строку) и байт групп. Полоса, отпущенная невидимой позицией, не защищается от вытеснения.
VIS_ROWS_A      DS 8
VIS_GROUPS_A    DS 2
VIS_ROWS_B      DS 8
VIS_GROUPS_B    DS 2
VIS_LAYER       DB 0
VIS_BAND        DB 0
VIS_PIECES      DB 0
POS_VISIBLE     DB 0                    ; позиция PositionUpdate видна в одном из двух списков
VIDEO_SHOWN     DB 0                    ; показан display list машины (есть что затемнять)
DL_LAST         DW 0                    ; место DISPLAY последнего display list в RAM_DL
RETRY0          DS 32                   ; слой 0: байт на строку полос, бит на группу — ждёт полосы
RETRY1          DS 32                   ; слой 1
VIDEO_MISSING   DW 0
VIDEO_DROPPED   DW 0
VIDEO_OVERFLOW  DW 0
VIDEO_UPLOADS   DW 0
VIDEO_FAULTS    DW 0
VIDEO_TIMEOUTS  DW 0
VIDEO_STRIPS    DW 0                    ; собрано полос
WAIT_LEFT       DW 0
DL_FULL         DB 0
DL_CAP          DW DL_LIMIT
DATA_STATUS     DB 0                    ; 0 — пак не открывался, DATA_READY, DATA_FAILED
DATA_ERROR      DB 0
HOST_W1         DB V30_PAGE_BASE+WORK_PAGE ; страница окна W1 (Map1)
TOP_SCROLL      DS 8
DMA_PAGE        DB 0
DMA_OFFSET      DW 0
DMA_NUMBER      DB 0
BURST_OFFSET    DW 0
BURST_BYTES     DW 0
BURST_HEADER    DW 0
BURST_START     DW 0
DL_SENT         DW 0
JUMP_AT         DW 0
SUB_START       DW 0
SUB_TABLE       DS 16                   ; номер первой команды подпрограммы: (проход·2 + полоса)·2 + (слой = 0)
CUR_PAL         DB 0
CUR_TX          DW 0
CUR_TX_H        DB 0
CUR_TY          DW 0
CUR_TY_H        DB 0
PAL_TABLE       DB 0
PAL_PEN         DB 0
PAL_G5          DB 0
PAL_B5          DB 0
PEN_MASK        DW 0                    ; перья палитры PensRead
SCAN_ROW        DB 0
TILE_LAYER      DB 0
TILE_ROW        DB 0                    ; строка полос
TILE_GROUP      DB 0
TILE_REGION     DB 0
TILE_RR         DB 0
TILE_COLUMN     DB 0
TILE_OFFSET     DW 0
ROW_FORCE       DB 0
STREAM_KIND     DB 0
CASCADE         DB 0
SPLICE_NUMBER   DB 0
SPLICE_ROWS     DB 0
SPLICE_NEW      DB 0
SPLICE_HEADER   DW 0
SPLICE_START    DW 0
SPLICE_END      DW 0
SPLICE_USED     DW 0
SPLICE_DELTA    DW 0
SPLICE_BASE     DW 0
SLOT_INFO       DS 2*SLOT_SIZE
STRIP_MASK      DB 0
STRIP_PASS      DB 0
STRIP_FX        DB 0
STRIP_CURRENT   DW 0
KEY_SETPAL      DB 0                    ; ключ полосы: 5 байт подряд
KEY_W0          DW 0
KEY_W1          DW 0
KEY_SAVE        DS 5
BUCKET_PTR      DW 0
NEW_REFS        DS 4
OLD_REFS        DS 4
ROW_FAILED      DB 0                    ; в строке полос не хватило полосы — строка откатывается
UNDO_COUNT      DB 0
UNDO_LOG        DS 8*10                 ; столбец строки: адрес позиции, новые и прежние ссылки
STRIP_ADDRESS   DS 3
COMPOSE_SLOT    DB 0
COMPOSE_WORD    DW 0
COPY_DEST       DS 3
COPY_SOURCE     DS 3
ROOM_NEED       DW 0
CELL_SETPAL     DB 0
CELL_CODE       DW 0
CELL_FLAGS      DB 0
CELL_SLOT       DW 0
ALLOC_TRIES     DW 0
ALLOC_PAIR      DW 0
ALLOC_OWNER     DW 0
RELEASE_LEFT    DW 0
INFLATE_ADDRESS DS 3
INFLATE_OFFSET  DW 0
INFLATE_BYTES   DW 0
INFLATE_PIECES  DS LOADER_PIECES_BYTES          ; куски потока ячейки (копия LOADER_PIECES)
INFLATE_PIECE   DW 0
INFLATE_PAGE    DB 0
INFLATE_LEFT    DW 0
STRIP_HAND      DW 0
CELL_HAND       DW 0
SPRITE_HAND     DB 0
SPRITE_BYTES    DW 0
; Указатель SPRITE_FILL, состояние буфера спрайтов (SPRITE_PAL, SPRITE_FLIP, SPRITE_RX, SPRITE_RY) и VIDEO_FRAME — в
; резиденте (v30z80_runtime.asm): их ведёт и вывод объектов второй страницы хоста (vdac2p_objects.asm).
SPRITE_CODE     DW 0
SPRITE_PALETTE  DB 0
; Запись SpriteEntry: форма (8 байт — как запись SPRITE_SHAPES), видимые строки, столбец, ячейка, карта слотов.
SE_SHAPE:
SE_COLUMNS      DB 0
SE_ROWS         DB 0
SE_COLCODE      DB 0                    ; смещение кода первого столбца и шаг
SE_COLSTEP      DB 0
SE_ROWCODE      DB 0                    ; смещение кода первой (видимой) строки и шаг
SE_ROWSTEP      DB 0
SE_FLIP         DB 0                    ; режим матрицы ключа: бит 0 — fx, бит 2 — fy
SE_H16          DB 0
                ASSERT SE_H16 == SE_SHAPE+7
SE_Y0           DB 0                    ; y + 16 первой видимой строки
SE_ROWN         DB 0                    ; видимых строк
SE_Y            DB 0                    ; y + 16 ячейки
SE_CODEBASE     DW 0                    ; код + смещение столбца
SE_RX           DB 0                    ; столбец: область X, байты 2 и 3 вершины
SE_B2           DB 0
SE_B3           DB 0
SE_PENDING      DB 0                    ; бит 0 — сверить палитру, бит 1 — область X
SE_SLOT_PAL     DB #FF                  ; палитра карты слотов в окне W2 (#FF — окно неизвестно)
SE_SLOT_PAGE    DB 0
SE_SLOT_BASE    DB 0                    ; #80 или #A0: половина страницы карты
SE_XT           DW 0                    ; запись 1×1: указатель в SPRITE_XT_RX
EMIT_PASS       DB 0
EMIT_BAND       DB 0
BAND_COUNT      DB 0
BAND0_TOP       DB 0
BAND0_BOTTOM    DB 0
BAND1_TOP       DB 0
BAND0_SCROLL    DS 8
BAND1_SCROLL    DS 8
BAND_SCROLL_PTR DW 0
BAND_TOP        DB 0
BAND_BOTTOM     DB 0
LAYER_PASS      DB 0
LAYER_SX        DW 0
LAYER_SY        DW 0
LAYER_BASE_Y    DW 0
ROW_FIRST       DB 0
ROW_FIRST_Y     DW 0
ROW_COUNT       DB 0
PIECE_FIRST     DB 0
PIECE_WRAP      DB 0            ; куски этой записи уже за склейкой карты полос
PIECE_LEFT      DB 0
PIECE_ROWS      DB 0
PIECE_PTR       DW 0
PIECE_TABLE     DW 0
PIECE_COUNT     DB 0                    ; кусков полосы слоя (LayerEmit)
PIECE_ENTRY     EQU 11
PIECE_WORK      DS 4*PIECE_ENTRY        ; куски полосы для PieceBurst (не больше 4)
BURST_LOC       DW 0                    ; место потока выводимой группы в таблице мест семьи
LAYER_STREAMS   DS 8                  ; непустых потоков слоя-прохода: полосы, затем картинки
REGION_GROUPS   DS 24                   ; маска групп с непустым потоком (слой-проход·3 + область): полосы, картинки
EMIT_FAMILY     DB 0                    ; выводимая семья потоков: 0 — полосы, 1 — картинки
CUR_FLIP        DB 0                    ; отражение матрицы в подпрограмме
HEADER_BASE     DW 0                    ; заголовок потока 0 семьи (окно W1)
LOC_TABLE       DW 0                    ; места потоков семьи
GROUPS_GEOMETRY DB 0                    ; видимые группы слоя в полосе
GROUPS_LEFT     DB 0                    ; группы куска, ещё не выведенные (младший бит — TILE_GROUP)
FAMILY_REGION0  DB 0
GROUP_TX_BASE   DW 0
GROUP_TX_PTR    DW 0
GEOMETRY_PTR    DW 0
; Геометрия слоя в полосе (слой·2 + полоса): +0 годна, +1 sy, +3 первая строка, +4 последняя,
; +5 число кусков, +6 куски (4 по 6 байт); +GEOMETRY_X годна, sx, маска групп, сдвиги X групп.
GEOMETRY_X      EQU 30
GEOMETRY_SIZE   EQU GEOMETRY_X+4+8*3
GEOMETRY        DS 4*GEOMETRY_SIZE
ROW_PAL         DS 4                    ; (семья·2 + проход): палитра в конце буфера строки (UNKNOWN — неизвестна)
ROW_LEN         DS 4
ROW_FLIP        DS 4                    ; отражение матрицы в конце буфера строки
ROW_OPEN        DS 4                    ; начало строки ещё свободно (задаст первое слово)
ROW_START       DS 4                    ; выбранное начало строки (#20 + отражение·16 + палитра; UNKNOWN — нет)
SPLICE_STATE    DW 0                    ; адрес состояния перед строкой в заголовке потока
PIECES_LEFT     DB 0
STATE_OFFSET    DB 0
TILE_TEMP       DS 64                   ; тайлы строк 2k и 2k+1 группы
PAL_PENDING     DS 64
STREAM_FAMILY   DB 0                    ; семья потоков перестройки: 0 — полосы, 1 — картинки
IMAGE_HAND      DW 0
IMAGE_CURRENT   DW 0
IMAGE_TARGET    DS 3                    ; адрес собираемой картинки в RAM_G
IMAGE_MASK      DW 0                    ; слоты строки группы, выведенные картинками
CLASS_DONE      DW 0                    ; слоты, уже отнесённые к классу
CLASS_MASK      DW 0
CLASS_SLOT      DB 0
CLASS_RECORD    DW 0                    ; запись слота CLASS_SLOT в SLOTS
CLASS_BIT       DW 0                    ; маска слота CLASS_SLOT
CLASS_PASS      DB 0
CLASS_COUNT     DB 0
IREF_COUNT      DB 0
NEW_IREFS       DS 2*IMAGE_REFS         ; ссылки строки группы на картинки (номер + 1)
OLD_IREFS       DS 2*IMAGE_REFS
IUNDO_AT        DW 0                    ; откат ссылок строки группы: адрес в странице картинок (окно W2)
IUNDO_VALID     DB 0
VIDEO_IMAGES    DW 0                    ; собрано картинок
; Кэш подпрограмм слоёв (CacheReplay): по слоту s = проход·4 + полоса·2 + (слой = 0).
CACHE_OK        DS 8                    ; 1 — копия годна (снимает CacheInvalidate при перестройке видимой строки)
CACHE_COUNT     DS 8                    ; записей сдвигов копии
CACHE_LEN       DS 16                   ; байт слов копии
CACHE_STRUCT    DS 8*CACHE_STRUCT_SIZE  ; число кусков, куски (область, первая строка, строк), маска групп
CACHE_NOW       DB 0                    ; слот выводимой подпрограммы
CACHE_GROUP_BIT DB 0                    ; бит группы перестраиваемой строки (CacheInvalidate)
CACHE_BASE      DB 0                    ; старший байт адреса слота в окне W2 (CacheReplay)
CACHE_BYTES     DW 0                    ; длина выводимой копии
CAPTURE         DB 0                    ; 1 — слова выводимой подпрограммы копируются в слот
CAPTURE_BASE    DB 0                    ; старший байт адреса слота в окне W2 (запись копии)
CAPTURE_PTR     DW 0                    ; место следующего слова копии (окно W2)
CAPTURE_SOURCE  DW 0                    ; адрес значения сдвига для записи (PieceBurst)
RECORD_PTR      DW 0                    ; место следующей записи сдвигов (окно W2)
RECORD_LEFT     DB 0                    ; записей сдвигов ещё помещается
COPY_TO         DW 0                    ; смещение приёмника CacheCopy в странице кэша

; Есть ли группы, ждущие повтора (любой бит RETRY0 и RETRY1)? → RETRY_ANY: пока они есть, бюджет
; перестройки в этом кадре не действует. Повтор ставится при нехватке полосы, а отложенные строки держат
; прежние полосы — без этого пул не освобождается и на экране остаются дыры (замер 2026-09-20: после
; гибели корабля игра переинициализирует видео, и картинка восстанавливалась 350 кадров вместо нескольких).
; Проверка раз в кадр, а не у каждой группы: 64 байта против 11 тыс. тактов кадра.
; Портит AF, B, HL.
RetryScan:      ld hl,RETRY0
                ld b,64
                xor a
.byte:          or (hl)
                inc hl
                djnz .byte
                ld (RETRY_ANY),a
                ret

; Конец строки полос: отложенной группе возвращаются пометки строк карты 2k, 2k+1 (HL — байт строки 2k+1
; в VRAM_ROWS слоя). Портит AF; HL сохраняет.
RowRestore:     ld a,(ROW_DEFER)
                or a
                ret z
                ld (hl),a
                dec hl
                ld (hl),a
                inc hl
                xor a
                ld (ROW_DEFER),a
                ret

; --- кольцо фона: слова списка (VDAC2+: перенесено из резидента, v30z80_ring.asm — место резидента ушло под раннюю
; подгрузку ячеек; зовёт только LayerEmit хоста) -------------------------------------------------------------
; Кольцо в основную часть display list прохода 0 полосы EMIT_BAND (после её ножниц, перед слоем 1): handle
; RING_HANDLE, источник, раскладка 512×256 и размер полосы (NEAREST), палитра кольца, матрица A = 96 (3/8), E = 85
; (≈1/3), C = (64 + sx)·256 − 48, F = (верх полосы + 128 + sy)·256 + 120, CELL 0, вершина (0, верх·3), затем матрица
; как у заголовка (A = E = 160, C = F = 0) — без отражения, как ждут подпрограммы слоёв (палитру и сдвиги они ставят сами).
; Слова — шаблон RING_DL, в который вписываются высота полосы, C, F и вершина; шаблон уходит в display list одним пакетом
; DMA RAM→SPI из страницы резидента (DlBurst хоста): по слову через EmitWord 19 слов стоили ≈5,6 тыс. тактов на полосу.
; Портит всё.
RingEmit:       ; высота полосы: (низ − верх)·3, низ 0 — 256
                ld a,(BAND_BOTTOM)
                ld l,a
                ld h,0
                or a
                jr nz,.bottom
                inc h
.bottom:        ld a,(BAND_TOP)
                ld e,a
                ld d,0
                or a
                sbc hl,de
                ld d,h
                ld e,l
                add hl,hl
                add hl,de                       ; HL = высота в физических пикселях (≤ 768)
                ld a,l
                ld (RING_DL_SIZE),a                ; BITMAP_SIZE: высота & 511
                ld a,h
                and 1
                ld (RING_DL_SIZE+1),a
                ld a,h
                srl a                           ; высота >> 9 (h ≤ 3: бит 9 — это бит 1 старшего байта)
                or 8                            ; ширина >> 9 = 2 → << 2
                ld (RING_DL_SIZE_H),a              ; BITMAP_SIZE_H
                ; скроллы слоя 1 полосы: BAND_SCROLL_PTR + 4 — sy, + 6 — sx (& 511)
                ld hl,(BAND_SCROLL_PTR)
                ld de,4
                add hl,de
                ld e,(hl)
                inc hl
                ld a,(hl)
                and 1
                ld d,a                          ; DE = sy
                inc hl
                push de
                ld e,(hl)
                inc hl
                ld a,(hl)
                and 1
                ld d,a                          ; DE = sx
                ld hl,63
                add hl,de                       ; 64 + sx − 1
                ld (RING_DL_C+1),hl                ; C = (64 + sx)·256 − 48 = (63 + sx)·256 + 208: u = 64 + sx + floor(3x/8)
                pop de
                ld hl,128
                add hl,de
                ld a,(BAND_TOP)
                ld e,a
                ld d,0
                add hl,de                       ; верх + 128 + sy (повтор кольца по v — через 256)
                ld (RING_DL_F+1),hl                ; F = (верх + 128 + sy)·256 + 120
                ld a,(BAND_TOP)
                ld l,a
                ld h,0
                add hl,hl
                ld d,h
                ld e,l
                add hl,hl
                add hl,de                       ; верх·6
                add hl,hl
                add hl,hl
                add hl,hl                       ; верх·48 = верх·3 в 1/16 пикселя
                ld (RING_DL_VERTEX),hl             ; VERTEX2F 0, верх·3
                ; Пакет (VDAC2+, 2026-09-24: −14 команд на строку развёртки при двух полосах). Кольцо сразу за кольцом
                ; прошлой полосы (RING_CONT: между ними только ножницы) — лишь слова полосы с RING_DL_BAND: handle, источник,
                ; раскладка, палитра, A, E, CELL и сдвиги у него те же. Сброс матрицы в конце не нужен, если следом —
                ; кольцо следующей полосы: у этой полосы нет подпрограмм слоёв (им нужна матрица без отражения).
                ld hl,RING_DL-#C000
                ld bc,RING_WORDS*4
                ld a,(RING_CONT)
                or a
                jr z,.whole
                ld hl,RING_DL_BAND-#C000
                ld bc,RING_DL_END-RING_DL_BAND
.whole:         xor a
                ld (RING_CONT),a
                push hl
                push bc
                ld a,(EMIT_BAND)
                inc a
                ld hl,BAND_COUNT
                cp (hl)
                jr nc,.send                     ; полоса последняя — сброс нужен
                call BandSubs
                jr nz,.send                     ; подпрограммы слоёв полосы ждут матрицу без отражения
                pop bc
                ld hl,-(RING_DL_END-RING_DL_RESET)
                add hl,bc
                push hl                         ; длина без сброса
                ld a,1
                ld (RING_CONT),a
.send:          pop bc
                pop hl
                ld a,$$RING_DL                  ; шаблон — в странице хоста (VDAC2+: перенесён из резидента)
                jp DlBurst

; Подпрограммы слоёв полосы EMIT_BAND прохода EMIT_PASS (SUB_TABLE): NZ — есть хоть одна. Портит AF, B, DE, HL,
; TILE_LAYER.
BandSubs:       ld a,1
                ld (TILE_LAYER),a
                call SubIndex
                ld a,(hl)
                inc hl
                and (hl)
                inc a
                ret nz                          ; подпрограмма слоя 1
                xor a
                ld (TILE_LAYER),a
                call SubIndex
                ld a,(hl)
                inc hl
                and (hl)
                inc a
                ret

; Слова кольца: младшее слово, старшее слово команды FT812. Сначала общие для обеих полос, с RING_DL_BAND — слова полосы
; (их вписывает RingEmit: высота в RING_DL_SIZE, RING_DL_SIZE_H, целые части C и F, вершина), с RING_DL_RESET — сброс матрицы.
; Адрес чётный — DMA RAM→SPI TS-Config начинает с чётного адреса.
                ALIGN 2
RING_DL:        DW RING_HANDLE, #0500                           ; BITMAP_HANDLE
                DW RING_BASE & #FFFF, #0100 | (RING_BASE >> 16) ; BITMAP_SOURCE
                DW #0100, #077C                 ; BITMAP_LAYOUT PALETTED4444, шаг 512 (& 1023), высота 256
                DW #0000, #2800                 ; BITMAP_LAYOUT_H: старшие биты шага и высоты — 0
                DW RING_LUT & #FFFF, #2A00 | (RING_LUT >> 16)   ; PALETTE_SOURCE
                DW 96, #1500                    ; BITMAP_TRANSFORM_A 3/8 (8.8)
                DW 85, #1900                    ; BITMAP_TRANSFORM_E ≈1/3 (8.8)
                DW 0, #0600                     ; CELL 0
                DW 0, #2B00                     ; VERTEX_TRANSLATE_X 0
                DW 0, #2C00                     ; VERTEX_TRANSLATE_Y 0
RING_DL_BAND:
RING_DL_SIZE:      DW 0, #080C                     ; BITMAP_SIZE NEAREST, REPEAT, REPEAT, ширина 1024 (& 511 = 0), высота & 511
RING_DL_SIZE_H:    DW 0, #2900                     ; BITMAP_SIZE_H: ширина >> 9 = 2 → << 2, высота >> 9
RING_DL_C:         DW 208, #1700                   ; BITMAP_TRANSFORM_C: доля 208, целая часть — байты 1, 2
RING_DL_F:         DW 120, #1A00                   ; BITMAP_TRANSFORM_F: доля 120 — границы родных строк не дальше пикселя от идеальных при E = 85
RING_DL_VERTEX:    DW 0, #4000                     ; VERTEX2F 0, верх·3
RING_DL_RESET:     DW 160, #1500                   ; BITMAP_TRANSFORM_A 160
                DW 160, #1900                   ; BITMAP_TRANSFORM_E 160
                DW 0, #1700                     ; BITMAP_TRANSFORM_C 0
                DW 0, #1A00                     ; BITMAP_TRANSFORM_F 0
RING_DL_END:
RING_WORDS      EQU 19                  ; слов RingEmit (резерв основной части хоста MAIN_RESERVE)
                ASSERT RING_DL_END-RING_DL == RING_WORDS*4 && RING_DL_END-RING_DL_BAND == 9*4 && RING_DL_END-RING_DL_RESET == 4*4
RING_CONT       DB 0                    ; последнее в списке — кольцо полосы без сброса матрицы: следующее — продолжение

HOST_END:
                INCLUDE "video_tables.inc"
                ASSERT HOST_END <= SPRITE_TABLES

; --- хвост страницы хоста: код за сгенерированными таблицами (в основной части места нет) --------------------
; Бюджет перестройки групп карты (отступление на аппаратном пределе скорости).
;
; Зачем. Раз в 64 кадра эталон переписывает в VRAM целую вертикальную полосу карты: замер 2026-09-20 —
; 54 группы вместо обычных трёх, кадр 3,97 млн тактов (284 мс) против 0,5 млн, и с ними залп подгрузки
; ячеек с SD (128 за кадр). Работа нужная, но не в этом кадре: за 2601 кадр перестроено 5600 групп, и
; ни одна из них в момент перестройки не была видна — 1660 правее окна, 3940 вне окна по вертикали.
;
; Как. За кадр каждый слой перестраивает не больше TILE_BUDGET срочных групп и LAZY_BUDGET ожидающих;
; остальные ждут следующих кадров — их пометки VRAM_ROWS и VRAM_DIRTY не снимаются, VIDEO_DIRTY остаётся
; взведён (тем же механизмом группы уже повторялись после нехватки полосы, StripFromSlots). Классы —
; GroupInWindow по окнам обеих полос растра.
;
; Чего бюджет не касается (проверено замерами, каждый случай ломал картинку):
;   — видимая группа перестраивается всегда: иначе на экране остаются прежние тайлы (без этого 11 кадров
;     подряд показывали по 4—6 устаревших групп);
;   — каскад строк области в StripRowRebuild: у следующей строки изменилось состояние потока, и отложить
;     её нельзя — склейка потоков разъезжается (в эмуляторе игровое поле не выводилось совсем);
;   — кадр, в котором есть группы, ждущие повтора (RETRY_ANY): повтор ставится при нехватке полосы, а
;     отложенные строки держат прежние полосы, и пул не освобождается (после гибели корабля картинка
;     восстанавливалась 350 кадров вместо нескольких);
;   — полная перестройка кадра (VIDEO_FORCE после VideoInit) — картинка собирается за один кадр, как прежде.
;
; Запас по времени у срочной группы — не меньше восьми кадров: столбец карты это 8 пикселей, а скролл не
; быстрее пикселя за кадр.
; Пределы задаются через -D при сборке (диагностика: проверить, не от бюджета ли рвутся титры).
                ifndef TILE_BUDGET
TILE_BUDGET     EQU 3                   ; групп правее окна (войдут в него при скролле) за кадр на слой
                endif
                ifndef LAZY_BUDGET
LAZY_BUDGET     EQU 1                   ; групп вне окна по вертикали — эти ждут, пока не сдвинется окно
                endif
; Цена группы — не столько в самой перестройке, сколько в ячейках, которые она тянет с SD: замер
; 2026-09-20, кадр 2794 — семь групп и 52 ячейки, 1,86 млн тактов. Поэтому новых групп кадр не берёт,
; когда выбран и этот бюджет (начатая группа догружает своё: бросать её посреди сборки — терять сделанную
; работу). Тратят его и спрайтовые ячейки, но они грузятся уже после TilesUpdate и ни на что не влияют.
                ifndef CELL_BUDGET
CELL_BUDGET     EQU 12                  ; ячеек графики с SD за кадр
                endif
TILE_LEFT       DB 0                    ; бюджет срочных групп этого кадра (ставит TilesUpdate)
LAZY_LEFT       DB 0                    ; бюджет ожидающих групп
CELL_LEFT       DB 0                    ; бюджет подгрузки ячеек этого кадра
RETRY_ANY       DB 0                    ; в RETRY0/RETRY1 есть ждущие повтора группы (RetryScan раз в кадр)
ROW_DEFER       DB 0                    ; в строке полос отложена группа — пометки строки вернуть
VIS_GROUPS      DB 0                    ; маска видимых групп слоя (LayerWindow)
VIS_ROW         DB 0                    ; первая видимая строка полос слоя
VIS_ROW2        DB 0                    ; то же для полосы экрана после растрового разрыва
VIS_ROWS2       DB 0                    ; строк полос в ней (0 — разрыва нет)

; Окно слоя TILE_LAYER для бюджета перестройки; зовёт TilesUpdate перед обходом слоя. Считает:
;   VIS_GROUPS — маска видимых групп из записи sx таблицы столбцов (те же вычисления, что у ColumnsSetup);
;   VIS_ROW — первая видимая строка полос ((128 + sy) & 511) >> 4 (тексел окна v = y + 128 + sy, строка
;     полос — 16 текселей), окно считается в 17 строк полос (256 строк текселей с частичными по краям);
;   VIS_ROW2, VIS_ROWS2 — то же для полосы экрана после растрового разрыва, у неё свой скролл AFTER_RASTER.
; Портит всё, окно W2.
LayerWindow:    ld a,(TILE_LAYER)
                add a,a
                add a,a                         ; слой·4 — пара sy, sx в TOP_SCROLL
                ld e,a
                ld d,0
                ld hl,TOP_SCROLL
                add hl,de
                ld e,(hl)
                inc hl
                ld d,(hl)                       ; DE = sy слоя
                inc hl
                ld a,(hl)
                inc hl
                ld h,(hl)
                ld l,a                          ; HL = sx слоя
                push hl
                ex de,hl
                ld de,128
                add hl,de
                ld a,h
                and 1
                ld h,a                          ; (128 + sy) & 511
                srl h
                rr l
                srl h
                rr l
                srl h
                rr l
                srl h
                rr l                            ; >> 4 — строка полос
                ld a,l
                ld (VIS_ROW),a
                pop hl
                ld a,h
                and 1
                ld h,a                          ; sx & 511
                ld d,h
                ld e,l
                add hl,hl
                add hl,hl
                add hl,hl                       ; sx·8
                ld b,h
                ld c,l
                add hl,hl                       ; sx·16
                add hl,bc                       ; sx·24
                add hl,de                       ; sx·25 — запись таблицы столбцов
                ld a,h
                or #80
                ld h,a                          ; адрес окна W2
                ld a,VIDEO_COLUMN_PAGE
                call Map2
                ld a,(hl)
                ld (VIS_GROUPS),a               ; маска видимых групп этого sx
                ; Полоса экрана после растрового разрыва (BandsSetup) показывает слой со своим скроллом
                ; AFTER_RASTER: у M72 это панель счёта, и строки карты у неё совсем другие (замер 2026-09-20:
                ; разрыв на строке 239 каждый кадр, у слоя 0 там sy 144). Её строки считаются видимыми целиком,
                ; без проверки столбцов: полоса низкая, групп в ней единицы.
                ld hl,(RASTER_ROW)
                ld a,h
                or a
                ld b,0
                jr nz,.band1                    ; #FFFF — разрыва нет
                ld a,l
                ld c,a                          ; строка разрыва
                ld a,255
                sub c
                rrca
                rrca
                rrca
                rrca
                and 15
                add a,2                         ; строк полос полосы (с частичными по краям)
                ld b,a
                ld a,(TILE_LAYER)
                add a,a
                add a,a
                ld e,a
                ld d,0
                ld hl,AFTER_RASTER
                add hl,de
                ld e,(hl)
                inc hl
                ld d,(hl)                       ; DE = sy полосы
                ld l,c
                ld h,0
                add hl,de
                ld de,128
                add hl,de
                ld a,h
                and 1
                ld h,a                          ; (128 + sy + строка разрыва) & 511
                srl h
                rr l
                srl h
                rr l
                srl h
                rr l
                srl h
                rr l                            ; >> 4 — строка полос
                ld a,l
                ld (VIS_ROW2),a
.band1:         ld a,b
                ld (VIS_ROWS2),a
                ret

; Взять группу B строки полос SCAN_ROW слоя на перестройку: HL — байт пометки группы в строке карты 2k
; (в строке 2k+1 — на 8 дальше). CF = 1 — перестраивать: пометки сняты и, если группа брала бюджет, он
; уменьшен. CF = 0 — пометок нет либо группу отложили (бюджет кончился, а она не видна): пометки остаются,
; ROW_DEFER взведён, VIDEO_DIRTY тоже — кадр вернётся к ней. Портит AF, DE, C; HL и B сохраняет.
GroupTake:      ld de,8
                push hl
                add hl,de
                ld a,(hl)                       ; пометка группы в строке карты 2k+1
                pop hl
                or (hl)                         ; или в строке 2k
                ret z                           ; пометок нет — CF = 0
                ld a,(VIDEO_FORCE)
                or a
                jr nz,.clear                    ; полная перестройка кадра — без бюджета
                ld a,(RETRY_ANY)
                or a
                jr nz,.clear                    ; в кадре есть группы, ждущие повтора: откладывать нельзя —
                call GroupInWindow              ; отложенные строки держат прежние полосы, и пул не освободится
                jr c,.clear                     ; видна — откладывать нельзя
                push af
                ld a,(CELL_LEFT)
                or a
                jr z,.deferPop                  ; кадр уже выбрал подгрузку ячеек
                pop af
                jr nz,.lazy
                ld a,(TILE_LEFT)                ; правее окна: бюджет срочных
                or a
                jr z,.defer
                dec a
                ld (TILE_LEFT),a
                jr .clear
.lazy:          ld a,(LAZY_LEFT)                ; вне окна по вертикали: бюджет ожидающих
                or a
                jr z,.defer
                dec a
                ld (LAZY_LEFT),a
.clear:         ld (hl),0                       ; пометки сняты — группа перестраивается
                push hl
                add hl,de
                ld (hl),0
                pop hl
                scf
                ret
.deferPop:      pop af
.defer:         ld a,#FF
                ld (ROW_DEFER),a
                ld (VIDEO_DIRTY),a              ; строка вернётся в следующем кадре
                or a                            ; CF = 0
                ret

HOST_TAIL_END:
                ASSERT HOST_TAIL_END <= #10000
