; SD/MMC через Z-Controller: секторный обмен по портам #57/#77.
; Используется тот же интерфейс, что в WC; зависимости от страниц WC нет.
; Все ожидания ограничены. Код работает при сохранённых приложением банках.
; VDAC2+: копия ports/sdzc.asm проекта E:\zx\FAT32 Driver (сам проект не меняется) с пятым входом таблицы — SD_READ_DMA,
; чтение сектора через DMA SPI→RAM TS-Conf прямо в физическую страницу. Остальные входы — как у драйвера, байт в байт.
; Собирает Source/Tools/rtype_loader.py (--raw с #3900) вместо build/port_sdzc.bin драйвера.
        ORG #3900
PORT_TABLE:
        DW SD_INIT,SD_READ,SD_WRITE,SD_SYNC,SD_READ_DMA
SD_DATA EQU #0057
SD_CONF EQU #0077
SD_ERROR_TIMEOUT EQU #E1
SD_ERROR_REPLY   EQU #E2
SD_ERROR_RANGE   EQU #E3

SD_INIT:
        OR A
        LD A,1
        JR Z,.unit
        LD A,11
.unit:
        LD (SD_SELECT+1),A
        XOR A
        LD (SD_BLOCK_ADDRESS),A
        LD (SD_V2),A
        LD (SD_MMC),A
        CALL SD_DESELECT
        LD BC,SD_DATA,DE,80
.clock:
        LD A,#FF
        OUT (C),A
        DEC DE
        LD A,D:OR E
        JR NZ,.clock
        LD HL,256
        LD (SD_RETRIES),HL
.idle:
        LD A,0,DE,0,HL,0
        CALL SD_COMMAND
        CP 1
        JR Z,.version
        CALL SD_RETRY
        JR NZ,.idle
        JP SD_TIMEOUT
.version:
        LD A,8,DE,0,HL,#01AA
        CALL SD_COMMAND
        JP C,SD_FAILED
        BIT 2,A
        JR NZ,.old_card
        CP 1
        JP NZ,SD_BAD_REPLY
        LD BC,SD_DATA
        IN A,(C)
        IN A,(C)
        IN H,(C)
        IN L,(C)
        LD DE,#01AA
        OR A:SBC HL,DE
        JP NZ,SD_BAD_REPLY
        LD A,1
        LD (SD_V2),A
.old_card:
        LD HL,8000
        LD (SD_RETRIES),HL
.activate:
        LD A,(SD_MMC)
        OR A
        JR NZ,.mmc
        LD A,55,DE,0,HL,0
        CALL SD_COMMAND
        JP C,SD_FAILED
        BIT 2,A
        JR Z,.acmd
        LD A,1
        LD (SD_MMC),A
.mmc:
        LD A,1,DE,0,HL,0
        CALL SD_COMMAND
        JR .activation_reply
.acmd:
        LD A,(SD_V2)
        OR A
        LD DE,0
        JR Z,.argument
        LD D,#40
.argument:
        LD A,41,HL,0
        CALL SD_COMMAND
.activation_reply:
        JP C,SD_FAILED
        OR A
        JR Z,.active
        CP 1
        JP NZ,SD_BAD_REPLY
        CALL SD_RETRY
        JR NZ,.activate
        JP SD_TIMEOUT
.active:
        LD A,(SD_V2)
        OR A
        JR Z,.byte_mode
        LD A,58,DE,0,HL,0
        CALL SD_COMMAND
        JP C,SD_FAILED
        OR A
        JP NZ,SD_BAD_REPLY
        LD BC,SD_DATA
        IN A,(C)
        LD D,A
        IN A,(C)
        IN A,(C)
        IN A,(C)
        BIT 6,D
        JR Z,.byte_mode
        LD A,1
        LD (SD_BLOCK_ADDRESS),A
        JR SD_SUCCESS
.byte_mode:
        LD A,16,DE,0,HL,512
        CALL SD_COMMAND
        JP C,SD_FAILED
        OR A
        JP NZ,SD_BAD_REPLY
        JR SD_SUCCESS

SD_RETRY:
        LD HL,(SD_RETRIES)
        DEC HL
        LD (SD_RETRIES),HL
        LD A,H:OR L
        RET

; На входе DE:HL=LBA, BC=буфер. Для SDSC переводим LBA в байтовый адрес.
SD_ADDRESS:
        LD (SD_BUFFER),BC
        LD A,(SD_BLOCK_ADDRESS)
        OR A
        RET NZ
        LD B,9
.shift:
        ADD HL,HL
        RL E:RL D
        JR C,.range
        DJNZ .shift
        XOR A
        RET
.range:
        LD A,SD_ERROR_RANGE
        SCF
        RET
SD_READ:
        CALL SD_ADDRESS
        RET C
        LD A,17
        CALL SD_COMMAND
        JR C,SD_FAILED
        OR A
        JR NZ,SD_BAD_REPLY
        CALL SD_WAIT_TOKEN
        JR C,SD_FAILED
        CP #FE
        JR NZ,SD_BAD_REPLY
        LD HL,(SD_BUFFER)
        LD BC,SD_DATA
        INIR
        INIR
        IN A,(C)
        IN A,(C)
SD_SUCCESS:
        XOR A
SD_FAILED:
        PUSH AF
        CALL SD_DESELECT
        POP AF
        OR A
        RET
SD_WRITE:
        CALL SD_ADDRESS
        RET C
        LD A,24
        CALL SD_COMMAND
        JR C,SD_FAILED
        OR A
        JR NZ,SD_BAD_REPLY
        LD BC,SD_DATA,A,#FE
        OUT (C),A
        LD HL,(SD_BUFFER)
        OTIR
        OTIR
        LD A,#FF
        OUT (C),A
        OUT (C),A
        CALL SD_WAIT_TOKEN
        JR C,SD_FAILED
        AND #1F
        CP 5
        JR NZ,SD_BAD_REPLY
        CALL SD_WAIT_READY
        JR C,SD_FAILED
        JR SD_SUCCESS
SD_SYNC:
        CALL SD_SELECT_CARD
        JR C,SD_FAILED
        JR SD_SUCCESS
SD_BAD_REPLY:
        LD A,SD_ERROR_REPLY
        JR SD_FAILED
SD_TIMEOUT:
        LD A,SD_ERROR_TIMEOUT
        JR SD_FAILED

SD_DESELECT:
        LD BC,SD_CONF,A,3
        OUT (C),A
        LD BC,SD_DATA,A,#FF
        OUT (C),A
        RET
SD_SELECT_CARD:
        LD BC,SD_CONF
SD_SELECT:
        LD A,1
        OUT (C),A
        LD BC,SD_DATA,A,#FF
        OUT (C),A
        JP SD_WAIT_READY

; Команда A, аргумент DE:HL. Ответ R1 в A, CF=1 только при тайм-ауте.
SD_COMMAND:
        LD (SD_COMMAND_BYTE),A
        PUSH DE,HL
        CALL SD_DESELECT
        CALL SD_SELECT_CARD
        POP HL,DE
        RET C
        LD BC,SD_DATA
        LD A,(SD_COMMAND_BYTE)
        OR #40
        OUT (C),A
        OUT (C),D
        OUT (C),E
        OUT (C),H
        OUT (C),L
        LD A,(SD_COMMAND_BYTE)
        LD D,#95
        OR A
        JR Z,.crc
        LD D,#87
        CP 8
        JR Z,.crc
        LD D,#FF
.crc:
        OUT (C),D
        LD D,16
.response:
        IN A,(C)
        BIT 7,A
        JR Z,.ready
        DEC D
        JR NZ,.response
        LD A,SD_ERROR_TIMEOUT
        SCF
        RET
.ready:
        OR A
        RET
SD_WAIT_READY:
        LD HL,0
        LD BC,SD_DATA
.loop:
        IN A,(C)
        CP #FF
        JR Z,.ready
        DEC HL
        LD A,H:OR L
        JR NZ,.loop
        LD A,SD_ERROR_TIMEOUT
        SCF
        RET
.ready:
        XOR A
        RET
SD_WAIT_TOKEN:
        LD HL,0
        LD BC,SD_DATA
.loop:
        IN A,(C)
        CP #FF
        JR NZ,.ready
        DEC HL
        LD A,H:OR L
        JR NZ,.loop
        LD A,SD_ERROR_TIMEOUT
        SCF
        RET
.ready:
        OR A
        RET
; VDAC2+: сектор DE:HL → физическая страница A со смещения BC (чётное; 512 байт не переходят конец страницы) через DMA
; TS-Conf в режиме SPI→RAM (#02): каждое чтение DMA — как IN из #57 (прошлый байт, запуск следующего обмена), то есть
; те же байты, что у INIR в SD_READ, но без процессора. Ответ, маркер и CRC — как у SD_READ. A = 0 — успех, иначе код
; ошибки. Только для секторов, которые процессор не читает: кэш процессора TS-Conf записи DMA может не видеть.
SD_DMA_PAGE: DB 0
SD_READ_DMA:
        LD (SD_DMA_PAGE),A
        CALL SD_ADDRESS
        RET C
        LD A,17
        CALL SD_COMMAND
        JP C,SD_FAILED
        OR A
        JP NZ,SD_BAD_REPLY
        CALL SD_WAIT_TOKEN
        JP C,SD_FAILED
        CP #FE
        JP NZ,SD_BAD_REPLY
        LD HL,(SD_BUFFER)
        LD BC,#1DAF             ; DMADADDRL
        OUT (C),L
        INC B                   ; DMADADDRH
        OUT (C),H
        INC B                   ; DMADADDRX
        LD A,(SD_DMA_PAGE)
        OUT (C),A
        LD B,#26                ; DMALEN: 256 слов в пакете
        LD A,#FF
        OUT (C),A
        LD B,#28                ; DMANUM: один пакет
        XOR A
        OUT (C),A
        LD B,#27                ; DMACTR: SPI → RAM
        LD A,#02
        OUT (C),A
.wait:
        IN A,(C)                ; DMASTATUS: бит 7 — передача идёт
        RLA
        JR C,.wait
        LD BC,SD_DATA
        IN A,(C)                ; CRC16 (не проверяется, как у SD_READ)
        IN A,(C)
        JP SD_SUCCESS
SD_BUFFER: DS 2
SD_RETRIES: DS 2
SD_BLOCK_ADDRESS: DB 0
SD_V2: DB 0
SD_MMC: DB 0
SD_COMMAND_BYTE: DB 0
PORT_END:
        ASSERT PORT_END <= #4000
