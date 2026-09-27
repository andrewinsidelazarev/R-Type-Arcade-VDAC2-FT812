;//////////////////////////////////////////////////////////////
;//  Самодостаточное чтение raw sector с SD (Z-Controller).
;//  Порт из Zuma Deluxe VDAC2 (Source/ASM/sd_zc.asm), то же железо TS-Conf.
;//  Карта инициализирована хостом (WC) до старта SPG (hardware state живёт),
;//  поэтому здесь отправляются только CMD17 reads.
;//  Unreal/этот host использует BYTE addressing (sd_blkt = 0): CMD17 argument
;//  равен LBA*512.
;//////////////////////////////////////////////////////////////

SD_CONF         equ     #77             ; config / chip-select port
SD_DATA         equ     #57             ; data port
SD_CMD17        equ     %01000000+17    ; single-block read
SD_CS1          equ     %00000001       ; chip select, SD1

;--- sd_init: byte addressing (Unreal). sd_blkt = 0.
sd_init:
                xor     a
                ld      (sd_blkt),a
                call    sd_csh
                call    sd_snb
                ret

;--- sd_read_sector: прочитать один 512-byte sector
;    Вход: HL = LBA (low 16), DE = LBA (high 16) [LBA is 32-bit]
;          IX = destination buffer (512 bytes)
;    Выход: CF = 1 on error, CF = 0 on success
sd_read_sector:
                ld      (sd_lba+0),hl
                ld      (sd_lba+2),de
                call    sd_lba_in_range         ; защита: не слать CMD17 за пределы тома
                jr      c,.range
                push    ix
                pop     hl                      ; HL = buffer
                call    sd_cmd17
                jr      nz,.err                 ; R1 обязан быть #00
                call    sd_wait_token
                jr      c,.err
                call    sd_reads                ; прочитать 512 bytes -> (HL), HL += 512
                in      a,(SD_DATA)             ; CRC16 lo (ignored)
                in      a,(SD_DATA)             ; CRC16 hi (ignored)
                call    sd_csh
                or      a                       ; CF=0
                ret
.err            call    sd_csh
                scf
                ret
.range          scf                             ; LBA вне тома — карту не трогаем
                ret

;--- CMD17 (single-block read). Address из sd_lba. byte addressing: arg = LBA*512.
sd_cmd17:
                ld      a,SD_CMD17
                call    sd_csh
                call    sd_csl
                push    hl                      ; сохранить buffer pointer
                ld      de,(sd_lba+0)           ; DE = LBA low16
                ld      bc,(sd_lba+2)           ; BC = LBA high16
                ld      l,c
                ld      h,b                     ; HL = high16
                ld      c,a                     ; C = command
                ld      a,(sd_blkt)
                or      a
                jr      nz,.send                ; block addressing -> LBA как есть
                ; byte addressing: [HL:DE] = LBA*512
                ex      de,hl : add hl,hl
                ex      de,hl : adc hl,hl
                ld      h,l : ld l,d : ld d,e : ld e,a  ; A=sd_blkt=0
.send
                ld      a,c                     ; A = command
                ld      bc,SD_DATA
                out     (c),a                   ; command byte
                out     (c),h
                out     (c),l
                out     (c),d
                out     (c),e
                ld      a,#FF
                out     (c),a                   ; CRC (ignored)
                pop     hl                      ; восстановить buffer pointer
                jp      sd_resp

;--- прочитать 512 bytes из data port в (HL); HL advances by 512
sd_reads:
                push    bc
                ld      bc,SD_DATA              ; B=0 -> 256 per INIR
                inir
                inir
                pop     bc
                ret

;--- chip select high (deselect) + clock
sd_csh:
                push    bc : push af
                ld      bc,SD_CONF : ld a,%00000011 : out (c),a
                ld      bc,SD_DATA : ld a,#FF : out (c),a
                pop     af : pop bc
                ret

;--- chip select low (select) + clock, затем wait ready
sd_csl:
                push    bc : push af
                ld      bc,SD_CONF : ld a,SD_CS1 : out (c),a
                ld      bc,SD_DATA : ld a,#FF : out (c),a
                pop     af : pop bc
                jp      sd_wait

;--- ждать ready (#FF), bounded
sd_wait:
                push    bc : push de : push af
                ld      bc,SD_DATA
                ld      de,0                    ; 65536 polls then give up
.w              in      a,(c) : inc a : jr z,.done   ; #FF -> ready
                dec     de : ld a,d : or e : jr nz,.w
.done           pop     af : pop de : pop bc
                ret

;--- ждать data token #FE с bounded timeout. CF=0 ok, CF=1 timeout/error.
sd_wait_token:
                push    bc
                ld      bc,SD_DATA
                ld      d,4
.outer          ld      e,0
.inner          in      a,(c)
                cp      #FE
                jr      z,.ok
                bit     7,a
                jr      z,.err                  ; data error token
                dec     e
                jr      nz,.inner
                dec     d
                jr      nz,.outer
.err            pop     bc
                scf
                ret
.ok             pop     bc
                or      a
                ret

;--- 16 dummy reads
sd_snb:
                push    bc : push af
                ld      b,16
.s              in      a,(SD_DATA) : djnz .s
                pop     af : pop bc
                ret

;--- прочитать R1 response (bit7=0), до 10 попыток
sd_resp:
                push    de : push bc
                ld      bc,SD_DATA
                ld      d,10
.r              in      a,(c) : bit 7,a : jr z,.done
                dec     d : jr nz,.r
.done           pop     bc : pop de
                ret

;--- sd_lba_in_range: sd_lba против sd_lba_max. CF=1 отвергнуть, CF=0 ок.
;    sd_lba_max==0 => защита выключена (bootstrap).
sd_lba_in_range:
                push    hl : push de : push bc
                ld      a,(sd_lba_max+0)
                ld      b,a
                ld      a,(sd_lba_max+1) : or b : ld b,a
                ld      a,(sd_lba_max+2) : or b : ld b,a
                ld      a,(sd_lba_max+3) : or b
                jr      z,.disabled
                ld      hl,sd_lba
                ld      de,sd_lba_max
                or      a
                ld      b,4
.cmp            ld      a,(de)
                ld      c,a
                ld      a,(hl)
                sbc     a,c
                inc     hl
                inc     de
                djnz    .cmp
                ccf
                pop     bc : pop de : pop hl
                ret
.disabled       pop     bc : pop de : pop hl
                or      a
                ret

;--- SD state ---
sd_lba          ds      4
sd_blkt         db      0
sd_lba_max      ds      4               ; верхняя граница LBA тома; 0=выключено

