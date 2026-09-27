; Загрузчик данных уровней с SD-карты: файл RTYPELVL.PAC (Source/Tools/rtype_data.py) через
; драйвер FAT32 (E:\zx\FAT32 Driver: страница кода в окне W1 и рабочая страница с портом SD-ZC
; в окне W0). Страница загрузчика — в окне W2 (#8000): код, стек, буферы секторов.
;
; Вызов из хоста видеоадаптера (окна: W0 — резидент машины, W3 — страница хоста): хост
; ставит W2 = LOADER_PAGE, в LOADER_HOST_W1 — свою страницу окна W1, и вызывает вход. Загрузчик
; переходит на свой стек, отображает W0 — рабочую страницу драйвера, W1 — код драйвера, W3 —
; буфер данных DATA_BUF_PAGE, а перед возвратом возвращает окна хоста.
;
; Том монтирует и файл находит драйвер (FIND); сектора файла загрузчик читает сам: при открытии
; проходит цепочку FAT и строит таблицу кусков (сектор файла → сектор карты), далее чтение —
; прямое через обработчик порта драйвера (таблица #3900). Файл не длиннее 32 МБ (номер
; сектора файла — слово).
;
; Секторы индекса и потоков ячеек читаются через кэш секторов в ОЗУ (CacheSector): поток ячейки остаётся в слотах
; кэша и уходит в FT812 кусками прямо из них (LOADER_PIECES), без копирования в буфер.
;
; Константы (страницы, страницы кэша, адреса состояния драйвера) — Build/V30Z80/rtype_loader.inc.
                INCLUDE "rtype_loader.inc"
                INCLUDE "fat32.inc"

                ORG #8000
LOADER_INIT:    jp LoaderInit                   ; → A = 0 — файл открыт, иначе код ошибки
LOADER_CELL:    jp LoaderCell                   ; A — набор·16 + палитра, HL — код ячейки
LOADER_READ:    jp LoaderRead                   ; HL — сектор файла, BC — секторов → буфер
LOADER_READ_DMA: jp LoaderReadDma               ; HL — сектор файла, BC — секторов, A — первая страница (DMA)
LOADER_RECORD:  jp LoaderRecord                 ; HL — первый сектор потока, DE — смещение в нём, BC — байт
LOADER_OPEN:    jp LoaderOpen                   ; HL — описание файла (FILE_DESC) → A = 0 — файл открыт
LOADER_HOST_W1: DB 0                            ; страница окна W1 хоста (ставит хост)
LOADER_READY:   DB 0                            ; 1 — файл открыт
LOADER_HOST_W3: DB HOST_W3_PAGE                 ; страница окна W3 вызывающего (звуковая страница ставит свою)
; Куски потока последней ячейки LOADER_CELL (или записи LOADER_RECORD) по секторам подряд: страница кэша и старший
; байт смещения слота в ней ((слот & 31)·2); первый кусок — со смещения потока в секторе (DE выхода), остальные — с
; начала слота.
LOADER_PIECES:  DS RECORD_SECTORS_MAX*2

SECTOR_SIZE     EQU 512
CACHE_SLOTS     EQU CACHE_PAGE_COUNT*32         ; слотов кэша секторов (по 32 в странице)
MAX_EXTENTS     EQU 64
MAX_DIRS        EQU 64
ERROR_NO_FILE   EQU #F1
ERROR_FORMAT    EQU #F4
ERROR_EXTENTS   EQU #F5
ERROR_CHAIN     EQU #F6

; --- окна ------------------------------------------------------------------------------------
MapDriver:      ld a,FAT_WORK_PAGE
                ld bc,#10AF
                out (c),a
                ld a,FAT_CODE_PAGE
                ld bc,#11AF
                out (c),a
                ld a,DATA_BUF_PAGE
                ld bc,#13AF
                out (c),a
                ret
MapHost:        push af
                push bc
                ld a,HOST_W0_PAGE
                ld bc,#10AF
                out (c),a
                ld a,(LOADER_HOST_W1)
                ld bc,#11AF
                out (c),a
                ld a,(LOADER_HOST_W3)
                ld bc,#13AF
                out (c),a
                pop bc
                pop af
                ret

; --- открытие ------------------------------------------------------------------------------------
; LOADER_INIT — пак уровней RTYPELVL.PAC (DefaultFile). LOADER_OPEN — файл по описанию HL (VDAC2+ 2026-09-27: загрузчик
; SPG релиза так открывает код игры RTYPECOD.PAC): короткое имя 11 байт, размер 4 байта, метка первого сектора 8 байт
; (FILE_DESC); описание копируется в PackName…Magic до смены окон — HL может лежать в окне W1 вызывающего.
LoaderInit:     ld hl,DefaultFile
LoaderOpen:     ld de,PackName
                ld bc,FILE_DESC
                ldir
                ld (HostSp),sp
                ld sp,LoaderStackTop
                call MapDriver
                call OpenFile
                call MapHost
                ld sp,(HostSp)
                ret

OpenFile:       xor a
                ld (LOADER_READY),a
                ld hl,#3900
                xor a
                call FAT32_BIND
                call FAT32_DEVICE_INIT
                or a
                ret nz
                call FAT32_MOUNT
                or a
                ret nz
                ; том: BPB с сектора ADDTOP (начало раздела), найденного драйвером
                ld hl,(WDOS_ADDTOP)
                ld (VolumeStart),hl
                ld hl,(WDOS_ADDTOP+2)
                ld (VolumeStart+2),hl
                call VolumeGeometry
                ret nz
                ; пак уровней — сквозным поиском по всей карте по имени и размеру (как у Zuma)
                call FindPack
                ret nz
                ld hl,(PackEntry+28)
                ld de,(PackEntry+30)
                ; секторов файла: (размер + 511) >> 9, файл < 32 МБ
                ld bc,511
                add hl,bc
                jr nc,.noCarry
                inc de
.noCarry:       ld a,d
                cp 2
                jp nc,.tooLong                  ; размер + 511 >= 32 МБ
                ld l,h
                ld h,e
                srl d
                rr h
                rr l                            ; (D:E:H) >> 1 = (размер + 511) >> 9
                ld (FileSectors),hl
                ld hl,(PackEntry+26)
                ld (Cluster),hl
                ld hl,(PackEntry+20)
                ld (Cluster+2),hl
                ; цепочка кластеров → куски; подряд идущие кластеры удлиняют кусок без пересчёта
                ld hl,0
                ld (FileSector),hl
                ld (ExtentCount),hl
                ld hl,#FFFF
                ld (FatCached),hl
                ld (FatCached+2),hl
                xor a
                ld (FatValid),a
.newExtent:     call ClusterLba                 ; Lba = данные + (кластер − 2)·секторов
                call AppendExtent
                ret nz
.advance:       ld a,(ClusterSectors)
                ld e,a
                ld d,0
                ld hl,(FileSector)
                add hl,de
                ld (FileSector),hl
                ld de,(FileSectors)
                or a
                sbc hl,de
                jp nc,.chainDone
                ld a,(FatValid)
                or a
                jr nz,.located
                call FatLocate
                ret nz
.located:       ld hl,(FatPointer)
                ld e,(hl)
                inc hl
                ld d,(hl)
                inc hl
                ld c,(hl)
                inc hl
                ld a,(hl)
                and #0F
                ld b,a
                inc hl
                ld (FatPointer),hl              ; запись кластера номер + 1
                ; следующий (B:C:D:E) = Cluster + 1?
                ld hl,(Cluster)
                inc hl
                ld a,h
                or l
                jr z,.jump                      ; перенос в старшее слово — общим путём
                or a
                sbc hl,de
                jr nz,.jump
                ld hl,(Cluster+2)
                or a
                sbc hl,bc
                jr nz,.jump
                ld (Cluster),de
                ld hl,(ExtentCount)
                dec hl
                call ExtentAddress
                ld a,(ClusterSectors)
                add a,(ix+2)
                ld (ix+2),a
                jr nc,.counted
                inc (ix+3)
.counted:       ld hl,(FatPointer)
                ld de,FatBuffer+SECTOR_SIZE
                or a
                sbc hl,de
                jr nz,.advance
                xor a
                ld (FatValid),a                 ; следующая запись — в следующем секторе FAT
                jr .advance
.jump:          ld (Cluster),de
                ld (Cluster+2),bc
                xor a
                ld (FatValid),a
                call ValidateCluster
                ret nz
                jp .newExtent
.chainDone:     ; заголовок: сектор 0 файла
                ld hl,0
                ld bc,SectorBuffer
                call ReadFileSector
                ret nz
                ld hl,SectorBuffer
                ld de,Magic
                ld b,8
.magic:         ld a,(de)
                cp (hl)
                jr nz,.format
                inc hl
                inc de
                djnz .magic
                ; кэш секторов пуст (метки всех слотов #FFFF, возрасты и часы — 0): файл мог смениться
                ld hl,CacheTags
                ld de,CacheTags+1
                ld bc,CACHE_SLOTS*2-1
                ld (hl),#FF
                ldir
                ld hl,CacheAges
                ld de,CacheAges+1
                ld bc,CACHE_SLOTS
                ld (hl),0
                ldir                            ; возрасты и следующий за ними байт часов
                ld a,1
                ld (LOADER_READY),a
                xor a
                ret
.format:        ld a,ERROR_FORMAT
                or a
                ret
.tooLong:       ld a,ERROR_FORMAT
                or a
                ret

; Геометрия тома по BPB (сектор VolumeStart): секторов в кластере, начало FAT (активная копия),
; начало данных, корневой каталог. Z — успех.
VolumeGeometry: ld hl,VolumeStart
                ld de,Lba
                call Copy32
                ld bc,SectorBuffer
                call ReadLba
                ret nz
                ld a,(SectorBuffer+13)
                ld (ClusterSectors),a
                ld hl,(SectorBuffer+44)
                ld (RootCluster),hl
                ld hl,(SectorBuffer+46)
                ld (RootCluster+2),hl
                ; начало FAT = раздел + резерв + активная копия·размер FAT; данные = раздел + резерв + копии·размер
                ld hl,VolumeStart
                ld de,FatStart
                call Copy32
                ld hl,(SectorBuffer+14)
                ld (Temp32),hl
                ld hl,0
                ld (Temp32+2),hl
                ld hl,FatStart
                ld de,Temp32
                call Add32
                ld hl,FatStart
                ld de,DataStart
                call Copy32
                ld a,(SectorBuffer+40)
                ld c,0
                bit 7,a
                jr z,.mirrored
                and 15
                ld c,a                          ; зеркалирование выключено: активная копия
.mirrored:      ld a,(SectorBuffer+16)
                ld b,a                          ; копий FAT
.fats:          ld a,c
                or a
                jr z,.data
                push bc
                ld hl,FatStart
                ld de,SectorBuffer+36
                call Add32
                pop bc
                dec c
.data:          push bc
                ld hl,DataStart
                ld de,SectorBuffer+36
                call Add32
                pop bc
                djnz .fats
                xor a
                ret

; Поиск пака в глубину по всем каталогам (стек каталогов, как RawPak_FindByName у Zuma): обычный
; файл с коротким именем PACK_NAME и размером PACK_SIZE. Найденная запись — в PackEntry. Z — найден.
FindPack:       xor a
                ld (DirCount),a
                ld hl,RootCluster
                call DirPush
.pop:           ld a,(DirCount)
                or a
                jp z,.notFound
                dec a
                ld (DirCount),a
                call DirAddress
                ld de,Cluster
                call Copy32
.cluster:       call ClusterLba
                ld a,(ClusterSectors)
                ld (SectorsLeft),a
.sector:        ld bc,SectorBuffer
                call ReadLba
                ret nz
                ld ix,SectorBuffer
                ld b,16
.entry:         ld a,(ix+0)
                or a
                jr z,.pop                       ; конец каталога
                cp #E5
                jr z,.next
                ld a,(ix+11)
                cp #0F
                jr z,.next                      ; часть длинного имени
                bit 3,a
                jr nz,.next                     ; метка тома
                bit 4,a
                jr z,.file
                ld a,(ix+0)
                cp '.'
                jr z,.next                      ; «.» и «..»
                push bc
                ld a,(ix+26)
                ld (Temp32),a
                ld a,(ix+27)
                ld (Temp32+1),a
                ld a,(ix+20)
                ld (Temp32+2),a
                ld a,(ix+21)
                ld (Temp32+3),a
                ld hl,Temp32
                call DirPush
                pop bc
                jr .next
.file:          push bc
                push ix
                pop hl
                ld de,PackName
                ld b,11
.name:          ld a,(de)
                cp (hl)
                jr nz,.differ
                inc hl
                inc de
                djnz .name
                ld de,PackSize
                ld bc,17*256+4                  ; B: смещение до размера (+28) − 11; C: байт
.skip:          inc hl
                djnz .skip
.size:          ld a,(de)
                cp (hl)
                jr nz,.differ
                inc hl
                inc de
                dec c
                jr nz,.size
                pop bc
                push ix
                pop hl
                ld de,PackEntry
                ld bc,32
                ldir
                xor a
                ret
.differ:        pop bc
.next:          ld de,32
                add ix,de
                djnz .entry
                ; следующий сектор кластера или следующий кластер каталога
                ld hl,SectorsLeft
                dec (hl)
                jr z,.nextCluster
                ld hl,Lba
                ld de,One32
                call Add32
                jp .sector
.nextCluster:   call FatLocate
                ret nz
                ld hl,(FatPointer)
                ld de,Cluster
                call Copy32
                ld a,(Cluster+3)
                and #0F
                ld (Cluster+3),a
                call ValidateCluster
                jp nz,.pop                      ; конец цепочки каталога
                jp .cluster
.notFound:      ld a,ERROR_NO_FILE
                or a
                ret

; Кластер (HL) — в стек каталогов (переполнение — каталог пропускается).
DirPush:        ld a,(DirCount)
                cp MAX_DIRS
                ret nc
                push hl
                call DirAddress
                ex de,hl
                pop hl
                ld bc,4
                ldir
                ld hl,DirCount
                inc (hl)
                ret
; A — номер в стеке каталогов → HL — адрес.
DirAddress:     ld l,a
                ld h,0
                add hl,hl
                add hl,hl
                ld de,DirStack
                add hl,de
                ret

; Lba = DataStart + (Cluster − 2)·ClusterSectors.
ClusterLba:     ld hl,(Cluster)
                ld de,(Cluster+2)
                ld bc,2
                or a
                sbc hl,bc
                jr nc,.noBorrow
                dec de
.noBorrow:      ld a,(ClusterSectors)
.multiply:      rra
                jr c,.multiplied
                add hl,hl
                rl e
                rl d
                jr .multiply
.multiplied:    ld (Lba),hl
                ld (Lba+2),de
                ld hl,Lba
                ld de,DataStart
                jp Add32

; Кусок для Lba с сектора файла FileSector: продолжение последнего куска или новый. Z — успех.
AppendExtent:   ld hl,(ExtentCount)
                ld a,h
                or l
                jr z,.new
                ; последний кусок: файл + число = FileSector и сектор + число = Lba?
                dec hl
                call ExtentAddress              ; IX — кусок
                ld l,(ix+0)
                ld h,(ix+1)
                ld e,(ix+2)
                ld d,(ix+3)
                add hl,de                       ; следующий сектор файла куска
                ld de,(FileSector)
                or a
                sbc hl,de
                jr nz,.new
                ld l,(ix+4)
                ld h,(ix+5)
                ld e,(ix+2)
                ld d,(ix+3)
                add hl,de
                ld e,(ix+6)
                ld d,(ix+7)
                jr nc,.lbaLow
                inc de
.lbaLow:        ld bc,(Lba)
                or a
                sbc hl,bc
                jr nz,.new
                ex de,hl
                ld bc,(Lba+2)
                or a
                sbc hl,bc
                jr nz,.new
                ld a,(ClusterSectors)
                ld e,a
                ld d,0
                ld l,(ix+2)
                ld h,(ix+3)
                add hl,de
                ld (ix+2),l
                ld (ix+3),h
                xor a
                ret
.new:           ld hl,(ExtentCount)
                ld de,MAX_EXTENTS
                or a
                sbc hl,de
                jr c,.room
                ld a,ERROR_EXTENTS
                or a
                ret
.room:          ld hl,(ExtentCount)
                call ExtentAddress
                inc hl
                ld (ExtentCount),hl
                ld hl,(FileSector)
                ld (ix+0),l
                ld (ix+1),h
                ld a,(ClusterSectors)
                ld (ix+2),a
                ld (ix+3),0
                ld hl,(Lba)
                ld (ix+4),l
                ld (ix+5),h
                ld hl,(Lba+2)
                ld (ix+6),l
                ld (ix+7),h
                xor a
                ret

; HL — номер куска → IX — адрес (8 байт: сектор файла, секторов, сектор карты). Сохраняет HL.
ExtentAddress:  push hl
                add hl,hl
                add hl,hl
                add hl,hl
                ld de,Extents
                add hl,de
                push hl
                pop ix
                pop hl
                ret

; Запись FAT кластера Cluster: сектор FatStart + Cluster >> 7 (в буфере FatBuffer, если не тот
; же), FatPointer = FatBuffer + (Cluster & 127)·4, FatValid = 1. Z — успех.
FatLocate:      ld hl,(Cluster)
                ld de,(Cluster+2)
                ld a,l
                and 127
                ld (FatEntry),a
                ld b,7
.shift:         srl d
                rr e
                rr h
                rr l
                djnz .shift
                ld (Lba),hl
                ld (Lba+2),de
                ld hl,Lba
                ld de,FatStart
                call Add32
                ld hl,(Lba)
                ld de,(FatCached)
                or a
                sbc hl,de
                jr nz,.read
                ld hl,(Lba+2)
                ld de,(FatCached+2)
                or a
                sbc hl,de
                jr z,.cached
.read:          ld bc,FatBuffer
                call ReadLba
                ret nz
                ld hl,(Lba)
                ld (FatCached),hl
                ld hl,(Lba+2)
                ld (FatCached+2),hl
.cached:        ld a,(FatEntry)
                ld l,a
                ld h,0
                add hl,hl
                add hl,hl
                ld de,FatBuffer
                add hl,de
                ld (FatPointer),hl
                ld a,1
                ld (FatValid),a
                xor a
                ret

; Cluster — ссылка из FAT: свободный (< 2) или конец цепочки (>= #0FFFFFF8) до конца файла —
; ошибка. Z — годный кластер.
ValidateCluster:
                ld hl,(Cluster+2)
                ld a,h
                cp #0F
                jr c,.notEnd
                ld a,l
                inc a
                jr nz,.notEnd
                ld hl,(Cluster)
                ld a,h
                inc a
                jr nz,.notEnd
                ld a,l
                cp #F8
                jr nc,.bad
.notEnd:        ld hl,(Cluster+2)
                ld a,h
                or l
                jr nz,.good
                ld hl,(Cluster)
                ld a,h
                or a
                jr nz,.good
                ld a,l
                cp 2
                jr c,.bad
.good:          xor a
                ret
.bad:           ld a,ERROR_CHAIN
                or a
                ret

; --- чтение ------------------------------------------------------------------------------------
; Сектор карты Lba → буфер BC (обработчик read512 порта драйвера). Z — успех, A — код ошибки.
ReadLba:        ld hl,(Lba)
                ld de,(Lba+2)
                push ix
                call .port
                pop ix
                or a
                ret
.port:          push hl
                ld hl,(#3902)                   ; read512 таблицы устройства
                ex (sp),hl
                ret

; VDAC2+: сектор карты Lba → физическая страница DmaPage со смещения BC через DMA SPI→RAM (пятый вход обработчика
; порта, vdac2p_sdzc.asm). Процессор байты сектора не пишет и не читает: так — только секторы потока ячейки, которые
; дальше уходят в FT812 тоже через DMA (кэш процессора TS-Conf записи DMA может не видеть). Z — успех, A — код ошибки.
ReadLbaDma:     ld hl,(Lba)
                ld de,(Lba+2)
                ld a,(DmaPage)
                push ix
                call .port
                pop ix
                or a
                ret
.port:          push hl
                ld hl,(#3908)                   ; чтение через DMA таблицы устройства
                ex (sp),hl
                ret

; Сектор файла HL → страница DmaPage, смещение BC через DMA (ReadLbaDma). Z — успех.
ReadFileSectorDma:
                push hl
                ld hl,ReadLbaDma
                ld (ReadTail),hl
                pop hl
                call ReadFileSector
                push af
                ld hl,ReadLba
                ld (ReadTail),hl
                pop af
                ret

; Сектор файла HL → буфер BC. Z — успех.
ReadFileSector: push bc
                ld (FileSector),hl
                ld hl,0
.find:          ld de,(ExtentCount)
                push hl
                or a
                sbc hl,de
                pop hl
                jr nc,.outside
                call ExtentAddress
                ; FileSector − начало < число?
                push hl
                ld hl,(FileSector)
                ld e,(ix+0)
                ld d,(ix+1)
                or a
                sbc hl,de
                jr c,.next
                ld e,(ix+2)
                ld d,(ix+3)
                push hl
                or a
                sbc hl,de
                pop hl
                jr nc,.next
                ; Lba = сектор куска + смещение
                ld e,(ix+4)
                ld d,(ix+5)
                add hl,de
                ld (Lba),hl
                ld l,(ix+6)
                ld h,(ix+7)
                jr nc,.noCarry
                inc hl
.noCarry:       ld (Lba+2),hl
                pop hl
                pop bc
                ld hl,(ReadTail)
                jp (hl)                         ; ReadLba или ReadLbaDma
.next:          pop hl
                inc hl
                jr .find
.outside:       pop bc
                ld a,ERROR_CHAIN
                or a
                ret

; --- кэш секторов ---------------------------------------------------------------------------------------
; CACHE_SLOTS слотов по 512 байт в страницах CACHE_PAGES (только времени работы: в SPG их нет, выбор — rtype_loader.py):
; слот n — страница CACHE_PAGES[n >> 5], смещение (n & 31)·512. Наборы по 4 слота (CACHE_SETS): сектор файла s лежит в
; одном из слотов набора s mod CACHE_SETS; при промахе вытесняется самый давний слот набора (CacheAges — байт часов
; обращений CacheClock при последнем обращении к слоту, давность — по модулю 256). Метка слота в CacheTags — номер
; сектора в нём, #FFFF — пусто. Секторы одной ячейки идут подряд и попадают в разные наборы (соседние остатки), поэтому
; чтение следующего сектора не вытесняет прочитанный кусок той же ячейки. Модель спроса ячеек спрайтов (конец уровня 2,
; 2500 кадров): чтений SD за кадр 9,1 с прежними кэшами одного сектора и одного куска, 2,8 — прямое отображение тех же
; 480 слотов, 1,6 — наборы по 4.
; Набор: s mod (8·P) = ((s >> 3) mod P)·8 + (s & 7), P = CACHE_PAGE_COUNT; P делит 255, поэтому (s >> 3) mod P =
; (старший + младший байт s >> 3) mod P (256 ≡ 1), таблица CacheSetBase на суммы 0…286.
CACHE_SETS      EQU CACHE_SLOTS/4
                ASSERT 255 % CACHE_PAGE_COUNT == 0 && CACHE_SLOTS <= 512

; Сектор файла HL → в слоте кэша: A — страница (отображена в окно W3), D — старший байт смещения слота в странице
; (слот в окне W3 — #C000 + D·256). Z — успех; NZ — ошибка чтения (A — код, слот помечен пустым). Портит всё.
; CacheDma ≠ 0 — промах читается через DMA SPI→RAM (сектор, который процессор читать не будет), иначе — INIR.
CacheSector:    ld (CacheWanted),hl
                ld a,l
                and 7
                ld c,a                          ; s & 7
                ld a,l
                srl h
                rra
                srl h
                rra
                srl h
                rra                             ; H:A = s >> 3 (H < #20)
                add a,h
                ld l,a
                ld a,0
                adc a,a
                ld h,a                          ; HL = старший + младший байт s >> 3 (≤ 286)
                ld de,CacheSetBase
                add hl,de
                ld a,(hl)                       ; ((s >> 3) mod P)·8
                add a,c                         ; набор k = s mod CACHE_SETS
                ld l,a
                ld h,0
                add hl,hl
                add hl,hl                       ; 4k — первый слот набора
                ld (CacheSlot),hl
                add hl,hl
                ld de,CacheTags
                add hl,de                       ; HL → метка слота 4k
                ld de,(CacheWanted)
                ld c,0                          ; C — путь
.way:           ld a,(hl)
                inc hl
                cp e
                jr nz,.other
                ld a,(hl)
                cp d
                jr z,.hit
.other:         inc hl
                inc c
                ld a,c
                cp 4
                jr c,.way
                ; промах: самый давний слот набора
                ld hl,(CacheSlot)
                ld de,CacheAges
                add hl,de                       ; HL → возраст слота 4k
                ld a,(CacheClock)
                ld b,a                          ; B — часы
                ld de,0                         ; D — путь, E — давность выбранного
                ld c,e                          ; C — выбранный путь
.age:           ld a,b
                sub (hl)                        ; давность (по модулю 256)
                cp e
                jr c,.younger
                ld e,a
                ld c,d
.younger:       inc hl
                inc d
                ld a,d
                cp 4
                jr c,.age
                call CacheLocate
                ld hl,(CacheSlot)
                add hl,hl
                ld de,CacheTags
                add hl,de
                ld (hl),#FF
                inc hl
                ld (hl),#FF                     ; слот пуст, пока сектор не прочитан
                push hl                         ; → старший байт метки
                ld hl,(CacheWanted)
                ld a,(CacheDma)
                or a
                jr nz,.dma
                ld a,(CacheOffset)
                add a,#C0
                ld b,a
                ld c,0                          ; BC — слот в окне W3
                call ReadFileSector
                jr .read
.dma:           ld a,(CachePage)
                ld (DmaPage),a
                ld a,(CacheOffset)
                ld b,a
                ld c,0                          ; BC — смещение слота в странице
                call ReadFileSectorDma
.read:          pop hl
                jr nz,.fail
                ld de,(CacheWanted)
                ld (hl),d
                dec hl
                ld (hl),e                       ; метка — прочитанный сектор
                jr .done
.hit:           call CacheLocate
.done:          ld a,(CacheOffset)
                ld d,a
                ld a,(CachePage)
                cp a                            ; Z
                ret
.fail:          or a                            ; NZ (код ошибки ≠ 0)
                ret

; C — путь в наборе с первым слотом CacheSlot → CacheSlot — слот, его возраст — новые часы, CachePage и CacheOffset
; (старший байт смещения в странице); страница — в окне W3. Портит AF, BC, DE, HL.
CacheLocate:    ld hl,(CacheSlot)
                ld b,0
                add hl,bc
                ld (CacheSlot),hl
                ex de,hl                        ; DE = слот (< 512)
                ld hl,CacheAges
                add hl,de
                ld a,(CacheClock)
                inc a
                ld (CacheClock),a
                ld (hl),a                       ; возраст слота
                ld a,e
                and 31
                add a,a
                ld (CacheOffset),a
                ld a,e
                rlca
                rlca
                rlca
                and 7
                ld c,a
                ld a,d
                add a,a
                add a,a
                add a,a
                or c                            ; слот >> 5
                ld c,a
                ld b,0
                ld hl,CachePages
                add hl,bc
                ld a,(hl)
                ld (CachePage),a
                ld bc,#13AF
                out (c),a                       ; страница кэша — в окно W3
                ret

; Ячейка: A — набор·16 + палитра, HL — код. Выход: A — признаки (#40 — проход A, #80 — проход B,
; 0 — пустая), BC — байт потока zlib, DE — смещение потока в первом секторе; куски потока — LOADER_PIECES
; (секторы в слотах кэша); CF = 1 — ошибка чтения.
LoaderCell:     ld (HostSp),sp
                ld sp,LoaderStackTop
                push af
                call MapDriver
                pop af
                call CellWork
                call MapHost
                ld sp,(HostSp)
                ret

CellWork:       ld c,a
                ld a,(LOADER_READY)
                or a
                jr nz,.ready
                xor a
                scf
                ret
.ready:         ; запись индекса (8 байт): сектор 1 + набор_палитра·64 + код >> 6, смещение (код & 63)·8
                ld a,l
                and 63
                ld (IndexWithin),a
                ld a,h
                add a,a
                add a,a
                ld d,a
                ld a,l
                rlca
                rlca
                and 3
                or d
                ld e,a                          ; код >> 6 = H·4 + L >> 6 (код < 4096)
                ld d,0
                ld l,c
                ld h,0
                add hl,hl
                add hl,hl
                add hl,hl
                add hl,hl
                add hl,hl
                add hl,hl                       ; ·64
                add hl,de
                inc hl
                call CacheSector                ; индексный сектор — в слоте, слот в окне W3
                jp nz,.error
                ld a,(IndexWithin)
                ld l,a
                ld h,0
                add hl,hl
                add hl,hl
                add hl,hl                       ; (код & 63)·8
                ld a,d
                add a,#C0
                ld d,a
                ld e,0                          ; DE — слот в окне W3
                add hl,de
                ld e,(hl)
                inc hl
                ld d,(hl)                       ; первый сектор ячейки (файл < 32 МБ — слово)
                inc hl
                inc hl
                inc hl
                ld a,d
                or e
                jr nz,.present
                xor a
                ret                             ; пустая ячейка (CF = 0)
.present:       ld (RecordSector),de
                ld c,(hl)
                inc hl
                ld a,(hl)
                and #C0
                ld (CellFlags),a
                ld a,(hl)
                and 1
                ld b,a
                ld (RecordWithin),bc            ; смещение потока в первом секторе
                inc hl
                ld c,(hl)
                inc hl
                ld b,(hl)
                ld a,CELL_SECTORS_MAX+1
                ; Вход LoaderRecord: RecordSector, RecordWithin, CellFlags, BC — байт, A — предел кусков + 1.
.record:        ld (RecordLimit),a
                ld (CellBytes),bc
                ; секторов: (смещение + длина + 511) >> 9
                ld hl,(RecordWithin)
                add hl,bc
                ld bc,511
                add hl,bc
                ld a,h
                srl a
                ld (CellSectors),a
                ld hl,RecordLimit
                cp (hl)
                jr nc,.error                    ; запись испорчена: кусков больше, чем в паке (rtype_loader.py)
                ; секторы потока — в слоты кэша, куски (страница, старший байт смещения слота) — в LOADER_PIECES
                ld hl,LOADER_PIECES
                ld (PiecePointer),hl
                ld a,1
                ld (CacheDma),a                 ; поток ячейки процессор не читает (Inflate — DMA в FT812): DMA
.sector:        ld hl,(RecordSector)
                call CacheSector
                jr nz,.errorDma
                ld hl,(PiecePointer)
                ld (hl),a
                inc hl
                ld (hl),d
                inc hl
                ld (PiecePointer),hl
                ld hl,(RecordSector)
                inc hl
                ld (RecordSector),hl
                ld hl,CellSectors
                dec (hl)
                jr nz,.sector
                xor a
                ld (CacheDma),a
                ld de,(RecordWithin)            ; DE — смещение потока в первом секторе
                ld bc,(CellBytes)
                ld a,(CellFlags)
                or a                            ; CF = 0
                ret
.errorDma:      xor a
                ld (CacheDma),a
.error:         scf
                ret

; VDAC2+ (спрайты объектами, vdac2p_objects.asm): поток вне индекса ячеек — HL — первый сектор, DE — смещение потока в
; нём, BC — байт (кратно 4, не больше RECORD_SECTORS_MAX секторов) → секторы в слоты кэша через DMA, куски —
; LOADER_PIECES, как у LOADER_CELL. Выход: BC — байт, DE — смещение; CF = 1 — ошибка чтения или файл не открыт.
LoaderRecord:   ld (HostSp),sp
                ld sp,LoaderStackTop
                ld (RecordSector),hl
                ld (RecordWithin),de
                push bc
                call MapDriver
                pop bc
                ld a,(LOADER_READY)
                or a
                scf
                jr z,.done                      ; файл не открыт (CF = 1)
                ld a,#C0
                ld (CellFlags),a
                ld a,RECORD_SECTORS_MAX+1
                call CellWork.record
.done:          call MapHost                    ; флаги сохраняет
                ld sp,(HostSp)
                ret

; Прочитать BC секторов файла с сектора HL в DATA_BUF (#C000). Z — успех.
LoaderRead:     ld (HostSp),sp
                ld sp,LoaderStackTop
                push hl
                push bc
                call MapDriver
                pop bc
                pop hl
                ld de,#C000
.sector:        ld a,b
                or c
                jr z,.done
                push bc
                push de
                push hl
                ld b,d
                ld c,e
                call ReadFileSector
                pop hl
                pop de
                pop bc
                jr nz,.done
                inc hl
                inc d
                inc d
                dec bc
                jr .sector
.done:          call MapHost
                ld sp,(HostSp)
                ret

; VDAC2+: прочитать BC секторов файла с сектора HL через DMA SPI→RAM в страницы с A подряд (32 сектора на страницу, с
; её начала) — без буфера DATA_BUF и копии DmaCopy. Процессор байты не пишет: так читаются данные, которые и раньше
; попадали в свои страницы через DMA (кольцо фона, мелодии). Z — успех.
LoaderReadDma:  ld (HostSp),sp
                ld sp,LoaderStackTop
                ld (DmaPage),a
                push hl
                push bc
                call MapDriver
                pop bc
                pop hl
                ld de,0                         ; DE — смещение сектора в странице
.sector:        ld a,b
                or c
                jr z,.done
                push bc
                push de
                push hl
                ld b,d
                ld c,e
                call ReadFileSectorDma
                pop hl
                pop de
                pop bc
                jr nz,.done
                inc hl
                inc d
                inc d                           ; следующие 512 байт
                ld a,d
                cp #40
                jr c,.page
                ld d,0
                ld a,(DmaPage)
                inc a
                ld (DmaPage),a                  ; страница заполнена — следующая
.page:          dec bc
                jr .sector
.done:          call MapHost
                ld sp,(HostSp)
                ret

; --- 32 бита -------------------------------------------------------------------------------------
; (HL) += (DE), 4 байта.
Add32:          ld b,4
                or a
.add:           ld a,(de)
                adc a,(hl)
                ld (hl),a
                inc hl
                inc de
                djnz .add
                ret
; (DE) = (HL), 4 байта.
Copy32:         ld bc,4
                ldir
                ret

; Открываемый файл (LoaderOpen): короткое имя, размер, метка первого сектора — подряд, FILE_DESC байт.
PackName:       DB "RTYPELVLPAC"
PackSize:       DD PACK_SIZE
Magic:          DB "RTYPEDAT"
FILE_DESC       EQU $-PackName
DefaultFile:    DB "RTYPELVLPAC"                ; пак уровней — LOADER_INIT
                DD PACK_SIZE
                DB "RTYPEDAT"
                ASSERT $-DefaultFile == FILE_DESC && FILE_DESC == 23
One32:          DD 1
HostSp:         DW 0
FileSectors:    DW 0
FileSector:     DW 0
Cluster:        DS 4
VolumeStart:    DS 4
FatStart:       DS 4
DataStart:      DS 4
Lba:            DS 4
Temp32:         DS 4
FatCached:      DS 4
FatEntry:       DB 0
RootCluster:    DS 4
PackEntry:      DS 32
DirCount:       DB 0
SectorsLeft:    DB 0
DirStack:       DS MAX_DIRS*4
FatValid:       DB 0
FatPointer:     DW 0
ClusterSectors: DB 0
ExtentCount:    DW 0
IndexWithin:    DB 0
CellFlags:      DB 0
CellBytes:      DW 0
RecordSector:   DW 0
RecordWithin:   DW 0
CellSectors:    DB 0
RecordLimit:    DB 0                            ; предел кусков потока + 1 (ячейка или запись)
PiecePointer:   DW 0
CacheWanted:    DW 0
CacheOffset:    DB 0
CacheDma:       DB 0                            ; ≠ 0 — промахи CacheSector читать через DMA
DmaPage:        DB 0                            ; физическая страница приёмника ReadLbaDma
ReadTail:       DW ReadLba                      ; чтение сектора карты в конце ReadFileSector
Extents:        DS MAX_EXTENTS*8
SectorBuffer:   DS SECTOR_SIZE
FatBuffer:      DS SECTOR_SIZE
; Кэш секторов: страницы, ((старший + младший байт) mod P)·8 для сумм 0…286, метки и возрасты слотов, часы.
CachePages:
                CACHE_PAGE_LIST
                ASSERT $ - CachePages == CACHE_PAGE_COUNT
CacheIndex = 0
CacheSetBase:
                DUP 287
                DB (CacheIndex mod CACHE_PAGE_COUNT)*8
CacheIndex = CacheIndex + 1
                EDUP
CacheTags:      DS CACHE_SLOTS*2,#FF
CacheAges:      DS CACHE_SLOTS,0
CacheClock:     DB 0
CacheSlot:      DW 0
CachePage:      DB 0
LoaderStack:    DS 256
LoaderStackTop:
LoaderEnd:
                ASSERT LoaderEnd <= #C000
