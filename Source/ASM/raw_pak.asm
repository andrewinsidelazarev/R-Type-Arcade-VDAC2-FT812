; ============================================================================
; raw_pak.asm — самодостаточный FAT32 reader поверх SD CMD17 (sd_zc.asm).
; Порт из Zuma Deluxe VDAC2 (ts-dos.asm RawPak_*), адаптирован под HMM2:
;   * убрана Zuma-специфика (WC active-panel path, debug-vars, Quit/BOOT, TOC,
;     EXPECTED_PAK_SIZE-чек) — остаётся generic open-by-name;
;   * sector/dir buffer = #8000 (slot2). При ЗАГРУЗКЕ slot2 мапится на buffer-page
;     (не Core), slot3 — на loader-page; trampoline восстанавливает после загрузки.
;   * FAT-sector buffer отдельный (RawPak_FatBuf), чтобы FAT-walk не затирал dir-буфер.
;
; Публичный API:
;   RawPak_Mount            — разобрать BPB/MBR (один раз за session). CF=1 ok.
;   RawPak_OpenFile(HL=имя) — найти файл по имени (DFS), Seek0, BuildRunTable. CF=1 ok.
;                             FileStartClus/FoundSize заполнены.
;   RawPak_ReadSectors(C=dst page, HL=dst off, B=count) — читать N секторов файла.
; ============================================================================

; RAWPAK_BUF_PAGE — определена в main.asm (страница в slot2 под dir/sector buffer).
RAWPAK_SEC_BUF    EQU #8000              ; dir/sector buffer (slot2 window)
RAWPAK_RUN_MAX    EQU 128                ; max extents (128*6=768 B)
RAWPAK_DIRSTACK_MAX EQU 96               ; max pending dirs (96*4=384 B)

; --- Mount: прочитать sector 0, разобрать BPB (superfloppy) или MBR (SDHC). ---
RawPak_Mount:
                LD   HL, #FFFF                  ; FAT cache invalid
                LD   (RawPak_FatBufLba + 0), HL
                LD   (RawPak_FatBufLba + 2), HL
                LD   HL, 0
                LD   DE, 0
                CALL RawPak_ReadSectorBuffer    ; sector 0 -> #8000
                JP   C, .err
                XOR  A                          ; part_lba = 0 (superfloppy)
                LD   (RawPak_PartLba + 0), A
                LD   (RawPak_PartLba + 1), A
                LD   (RawPak_PartLba + 2), A
                LD   (RawPak_PartLba + 3), A
                LD   IX, RAWPAK_SEC_BUF
                LD   A, (IX + 11)               ; bytes/sector low == 0 ?
                OR   A
                JR   NZ, .tryMbr
                LD   A, (IX + 12)               ; bytes/sector high == 2 (512) ?
                CP   2
                JR   Z, .bpbReady               ; sector 0 — BPB -> superfloppy (byte addr)
.tryMbr:        LD   IX, RAWPAK_SEC_BUF + 446   ; MBR partition table: 4 x 16 B
                LD   B, 4
.mbrScan:       LD   A, (IX + 4)
                CP   #0B
                JR   Z, .havePart
                CP   #0C
                JR   Z, .havePart
                LD   DE, 16
                ADD  IX, DE
                DJNZ .mbrScan
                JP   .err
.havePart:      LD   A, (IX + 8)  : LD (RawPak_PartLba + 0), A
                LD   A, (IX + 9)  : LD (RawPak_PartLba + 1), A
                LD   A, (IX + 10) : LD (RawPak_PartLba + 2), A
                LD   A, (IX + 11) : LD (RawPak_PartLba + 3), A
                LD   A, 1
                LD   (sd_blkt), A               ; MBR => SDHC => block addressing
                CALL RawPak_ReadPartBpb
                JP   C, .err
.bpbReady:      LD   IX, RAWPAK_SEC_BUF
                LD   A, (IX + 11)
                OR   A
                JP   NZ, .err
                LD   A, (IX + 12)
                CP   2
                JP   NZ, .err
                LD   A, (IX + 13)
                OR   A
                JP   Z, .err
                LD   (RawPak_Spc), A
                ; fatstart = part_lba + reserved sectors
                LD   HL, RawPak_PartLba
                LD   DE, RawPak_FatStart
                CALL RawPak_Copy32
                LD   A, (IX + 14) : LD (RawPak_Tmp + 0), A
                LD   A, (IX + 15) : LD (RawPak_Tmp + 1), A
                XOR  A : LD (RawPak_Tmp + 2), A : LD (RawPak_Tmp + 3), A
                LD   HL, RawPak_Tmp
                LD   DE, RawPak_FatStart
                CALL RawPak_Add32
                ; datastart = fatstart + numFATs * FATSz32
                LD   HL, RawPak_FatStart
                LD   DE, RawPak_DataStart
                CALL RawPak_Copy32
                LD   A, (IX + 16)
                LD   B, A
.fatLoop:       PUSH BC
                LD   A, (IX + 36) : LD (RawPak_Tmp + 0), A
                LD   A, (IX + 37) : LD (RawPak_Tmp + 1), A
                LD   A, (IX + 38) : LD (RawPak_Tmp + 2), A
                LD   A, (IX + 39) : LD (RawPak_Tmp + 3), A
                LD   HL, RawPak_Tmp
                LD   DE, RawPak_DataStart
                CALL RawPak_Add32
                POP  BC
                DJNZ .fatLoop
                ; root cluster
                LD   A, (IX + 44) : LD (RawPak_RootClus + 0), A
                LD   A, (IX + 45) : LD (RawPak_RootClus + 1), A
                LD   A, (IX + 46) : LD (RawPak_RootClus + 2), A
                LD   A, (IX + 47) : LD (RawPak_RootClus + 3), A
                ; volume guard: sd_lba_max = PartLba + TotSec32 (0 = выключено)
                XOR  A
                LD   (sd_lba_max + 0), A
                LD   (sd_lba_max + 1), A
                LD   (sd_lba_max + 2), A
                LD   (sd_lba_max + 3), A
                LD   A, (IX + 32) : LD (RawPak_Tmp + 0), A : LD C, A
                LD   A, (IX + 33) : LD (RawPak_Tmp + 1), A : OR C : LD C, A
                LD   A, (IX + 34) : LD (RawPak_Tmp + 2), A : OR C : LD C, A
                LD   A, (IX + 35) : LD (RawPak_Tmp + 3), A : OR C
                JR   Z, .noGuard
                LD   HL, RawPak_PartLba
                LD   DE, sd_lba_max
                CALL RawPak_Copy32
                LD   HL, RawPak_Tmp
                LD   DE, sd_lba_max
                CALL RawPak_Add32
.noGuard:       SCF
                RET
.err:           OR   A
                RET

; --- OpenFile: HL = zero-term имя. Найти DFS, Seek0, построить run-table. CF=1 ok.
RawPak_OpenFile:
                LD   DE, RawPak_TargetName      ; скопировать имя uppercased
.cpy:           LD   A, (HL)
                CALL RawPak_Upcase
                LD   (DE), A
                INC  HL
                INC  DE
                OR   A
                JR   NZ, .cpy
                XOR  A
                LD   (RawPak_CheckSize), A      ; match только по имени
                CALL RawPak_FindByName
                JP   NC, .fail
                CALL RawPak_Seek0
                CALL RawPak_BuildRunTable
                JP   NC, .fail
                LD   HL, 0
                LD   (RawPak_LogCur), HL
                SCF
                RET
.fail:          OR   A
                RET

; --- FindByName: DFS дерева FAT по RawPak_TargetName. CF=1 найдено. ---
RawPak_FindByName:
                XOR  A
                LD   (RawPak_DirStackCnt), A
                LD   HL, RawPak_RootClus
                CALL RawPak_DirStackPush
.popLoop:       CALL RawPak_DirStackPop
                JP   C, .notFound
                XOR  A
                LD   (RawPak_CurSecInClus), A
                LD   (RawPak_HaveLfn), A
.sec:           CALL RawPak_CurrentLbaRegs
                CALL RawPak_ReadSectorBuffer
                JP   C, .notFound
                LD   IX, RAWPAK_SEC_BUF
.entry:         LD   A, (IX + 0)
                OR   A
                JP   Z, .dirDone
                CP   #E5
                JP   Z, .skip
                LD   A, (IX + 11)
                CP   #0F
                JP   Z, .lfnFrag
                LD   A, (IX + 11)
                AND  #08
                JR   NZ, .skip
                LD   A, (IX + 11)
                AND  #10
                JR   NZ, .isDir
                ; regular file: сверить имя
                LD   A, (RawPak_HaveLfn)
                OR   A
                JR   NZ, .haveName
                CALL RawPak_Build83
.haveName:      CALL RawPak_NameMatch
                JR   NZ, .skip
                LD   A, (IX + 26) : LD (RawPak_FileStartClus + 0), A
                LD   A, (IX + 27) : LD (RawPak_FileStartClus + 1), A
                LD   A, (IX + 20) : LD (RawPak_FileStartClus + 2), A
                LD   A, (IX + 21) : LD (RawPak_FileStartClus + 3), A
                LD   A, (IX + 28) : LD (RawPak_FoundSize + 0), A
                LD   A, (IX + 29) : LD (RawPak_FoundSize + 1), A
                LD   A, (IX + 30) : LD (RawPak_FoundSize + 2), A
                LD   A, (IX + 31) : LD (RawPak_FoundSize + 3), A
                SCF
                RET
.isDir:         LD   A, (IX + 0)
                CP   '.'
                JR   Z, .skip
                LD   A, (IX + 26) : LD (RawPak_Tmp + 0), A
                LD   A, (IX + 27) : LD (RawPak_Tmp + 1), A
                LD   A, (IX + 20) : LD (RawPak_Tmp + 2), A
                LD   A, (IX + 21) : LD (RawPak_Tmp + 3), A
                LD   HL, RawPak_Tmp
                CALL RawPak_DirStackPush
.skip:          XOR  A
                LD   (RawPak_HaveLfn), A
.next:          LD   DE, 32
                ADD  IX, DE
                PUSH IX
                POP  HL
                LD   A, H
                CP   (RAWPAK_SEC_BUF >> 8) + 2  ; конец 512-B сектора?
                JP   C, .entry
                CALL RawPak_AdvanceOne
                JP   NC, .sec
                JP   .popLoop
.dirDone:       JP   .popLoop
.lfnFrag:       CALL RawPak_StoreLfn
                JR   .next
.notFound:      OR   A
                RET

; --- DirStack (DFS LIFO, 4-byte clusters) ---
RawPak_DirStackPush:
                LD   A, (RawPak_DirStackCnt)
                CP   RAWPAK_DIRSTACK_MAX
                RET  NC
                PUSH HL
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                ADD  HL, HL
                LD   DE, RawPak_DirStack
                ADD  HL, DE
                EX   DE, HL
                POP  HL
                LD   BC, 4
                LDIR
                LD   A, (RawPak_DirStackCnt)
                INC  A
                LD   (RawPak_DirStackCnt), A
                RET
RawPak_DirStackPop:
                LD   A, (RawPak_DirStackCnt)
                OR   A
                JR   Z, .empty
                DEC  A
                LD   (RawPak_DirStackCnt), A
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                ADD  HL, HL
                LD   DE, RawPak_DirStack
                ADD  HL, DE
                LD   DE, RawPak_CurClus
                LD   BC, 4
                LDIR
                OR   A
                RET
.empty:         SCF
                RET

; --- name helpers ---
RawPak_Upcase:  CP   'a'
                RET  C
                CP   'z' + 1
                RET  NC
                SUB  #20
                RET
RawPak_Build83:
                LD   DE, RawPak_EntName
                PUSH IX
                POP  HL
                LD   B, 8
                CALL .copytrim
                PUSH IX
                POP  HL
                LD   BC, 8
                ADD  HL, BC
                LD   A, (HL)
                CP   ' '
                JR   Z, .noext
                LD   A, '.'
                LD   (DE), A
                INC  DE
                LD   B, 3
                CALL .copytrim
.noext:         XOR  A
                LD   (DE), A
                RET
.copytrim:      LD   A, (HL)
                CP   ' '
                RET  Z
                CALL RawPak_Upcase
                LD   (DE), A
                INC  DE
                INC  HL
                DJNZ .copytrim
                RET
RawPak_NameMatch:
                LD   HL, RawPak_EntName
                LD   DE, RawPak_TargetName
.nm:            LD   A, (DE)
                CP   (HL)
                RET  NZ
                OR   A
                RET  Z
                INC  HL
                INC  DE
                JR   .nm
RawPak_StoreLfn:
                LD   A, (IX + 0)
                AND  #1F
                DEC  A
                LD   HL, RawPak_EntName
                OR   A
                JR   Z, .pos
                LD   DE, 13
.mul:           ADD  HL, DE
                DEC  A
                JR   NZ, .mul
.pos:           LD   A, (IX + 1)  : CALL .put
                LD   A, (IX + 3)  : CALL .put
                LD   A, (IX + 5)  : CALL .put
                LD   A, (IX + 7)  : CALL .put
                LD   A, (IX + 9)  : CALL .put
                LD   A, (IX + 14) : CALL .put
                LD   A, (IX + 16) : CALL .put
                LD   A, (IX + 18) : CALL .put
                LD   A, (IX + 20) : CALL .put
                LD   A, (IX + 22) : CALL .put
                LD   A, (IX + 24) : CALL .put
                LD   A, (IX + 28) : CALL .put
                LD   A, (IX + 30) : CALL .put
                LD   A, 1
                LD   (RawPak_HaveLfn), A
                RET
.put:           CALL RawPak_Upcase
                LD   (HL), A
                INC  HL
                RET

; --- seek / FAT walk / cluster->LBA ---
RawPak_Seek0:
                LD   HL, RawPak_FileStartClus
                LD   DE, RawPak_CurClus
                CALL RawPak_Copy32
                XOR  A
                LD   (RawPak_CurSecInClus), A
                RET
RawPak_AdvanceOne:
                PUSH BC
                LD   A, (RawPak_CurSecInClus)
                INC  A
                LD   E, A
                LD   A, (RawPak_Spc)
                CP   E
                JR   Z, .nextCluster
                JR   C, .nextCluster
                LD   A, E
                LD   (RawPak_CurSecInClus), A
                POP  BC
                OR   A
                RET
.nextCluster:   XOR  A
                LD   (RawPak_CurSecInClus), A
                CALL RawPak_FatNext
                POP  BC
                RET
RawPak_FatNext:
                LD   HL, RawPak_CurClus
                LD   DE, RawPak_Tmp
                CALL RawPak_Copy32
                LD   B, 7
.shr:           CALL RawPak_ShrTmp1
                DJNZ .shr
                LD   HL, RawPak_FatStart
                LD   DE, RawPak_Tmp
                CALL RawPak_Add32
                LD   HL, RawPak_Tmp
                LD   DE, RawPak_FatBufLba
                CALL RawPak_Cmp32
                JR   Z, .fatCached
                LD   HL, (RawPak_Tmp)
                LD   DE, (RawPak_Tmp + 2)
                CALL RawPak_ReadFatSector
                JR   C, .err
                LD   HL, RawPak_Tmp
                LD   DE, RawPak_FatBufLba
                CALL RawPak_Copy32
.fatCached:     LD   A, (RawPak_CurClus)
                AND  127
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                ADD  HL, HL
                LD   DE, RawPak_FatBuf
                ADD  HL, DE
                LD   DE, RawPak_CurClus
                LD   BC, 4
                LDIR
                LD   A, (RawPak_CurClus + 3)
                AND  #0F
                LD   (RawPak_CurClus + 3), A
                CP   #0F
                JR   NZ, .notEoc
                LD   A, (RawPak_CurClus + 2)
                CP   #FF
                JR   NZ, .notEoc
                LD   A, (RawPak_CurClus + 1)
                CP   #FF
                JR   NZ, .notEoc
                LD   A, (RawPak_CurClus + 0)
                CP   #F8
                JR   C, .notEoc
                SCF
                RET
.notEoc:        LD   A, (RawPak_CurClus + 3)
                OR   A
                JR   NZ, .ok
                LD   A, (RawPak_CurClus + 2)
                OR   A
                JR   NZ, .ok
                LD   A, (RawPak_CurClus + 1)
                OR   A
                JR   NZ, .ok
                LD   A, (RawPak_CurClus + 0)
                CP   2
                JR   NC, .ok
.err:           SCF
                RET
.ok:            OR   A
                RET
RawPak_CurrentLbaRegs:
                LD   HL, RawPak_CurClus
                LD   DE, RawPak_Tmp
                CALL RawPak_Copy32
                LD   HL, (RawPak_Tmp)
                LD   DE, 2
                OR   A
                SBC  HL, DE
                LD   (RawPak_Tmp), HL
                JR   NC, .noBorrow
                LD   HL, (RawPak_Tmp + 2)
                DEC  HL
                LD   (RawPak_Tmp + 2), HL
.noBorrow:      LD   A, (RawPak_Spc)
.spcShift:      CP   1
                JR   Z, .spcDone
                SRL  A
                PUSH AF
                LD   HL, (RawPak_Tmp)
                ADD  HL, HL
                LD   (RawPak_Tmp), HL
                LD   HL, (RawPak_Tmp + 2)
                ADC  HL, HL
                LD   (RawPak_Tmp + 2), HL
                POP  AF
                JR   .spcShift
.spcDone:       LD   A, (RawPak_CurSecInClus)
                LD   E, A
                LD   D, 0
                LD   HL, (RawPak_Tmp)
                ADD  HL, DE
                LD   (RawPak_Tmp), HL
                JR   NC, .addData
                LD   HL, (RawPak_Tmp + 2)
                INC  HL
                LD   (RawPak_Tmp + 2), HL
.addData:       LD   HL, RawPak_DataStart
                LD   DE, RawPak_Tmp
                CALL RawPak_Add32
                LD   HL, (RawPak_Tmp)
                LD   DE, (RawPak_Tmp + 2)
                RET

; --- run-table (contiguous + fragmented) ---
RawPak_BuildRunTable:
                LD   HL, RawPak_FileStartClus
                LD   DE, RawPak_CurClus
                CALL RawPak_Copy32
                XOR  A
                LD   (RawPak_CurSecInClus), A
                LD   IX, RawPak_RunTable
                CALL RawPak_CurrentLbaRegs
                LD   (IX + 0), L
                LD   (IX + 1), H
                LD   (IX + 2), E
                LD   (IX + 3), D
                LD   (IX + 4), 0
                LD   (IX + 5), 0
                LD   A, 1
                LD   (RawPak_RunCount), A
                PUSH IX
                CALL RawPak_FatEntryPtr
                POP  IX
                JP   C, .fail
                LD   (RawPak_FatPtr), HL
.enter:         LD   A, (RawPak_Spc)
                ADD  A, (IX + 4)
                LD   (IX + 4), A
                JR   NC, .noLenCy
                INC  (IX + 5)
.noLenCy:       LD   HL, (RawPak_FatPtr)
                LD   A, (HL) : LD (RawPak_NextClus + 0), A : INC HL
                LD   A, (HL) : LD (RawPak_NextClus + 1), A : INC HL
                LD   A, (HL) : LD (RawPak_NextClus + 2), A : INC HL
                LD   A, (HL) : AND #0F : LD (RawPak_NextClus + 3), A : INC HL
                LD   (RawPak_FatPtr), HL
                LD   A, (RawPak_NextClus + 3) : CP #0F : JR NZ, .notEoc
                LD   A, (RawPak_NextClus + 2) : CP #FF : JR NZ, .notEoc
                LD   A, (RawPak_NextClus + 1) : CP #FF : JR NZ, .notEoc
                LD   A, (RawPak_NextClus + 0) : CP #F8 : JP NC, .done
.notEoc:        LD   HL, RawPak_CurClus
                LD   DE, RawPak_Tmp
                CALL RawPak_Copy32
                CALL RawPak_IncTmp32
                LD   HL, RawPak_Tmp
                LD   DE, RawPak_NextClus
                CALL RawPak_Cmp32
                JR   NZ, .jump
                LD   HL, RawPak_NextClus
                LD   DE, RawPak_CurClus
                CALL RawPak_Copy32
                LD   A, (RawPak_CurClus)
                AND  127
                JP   NZ, .enter
                PUSH IX
                CALL RawPak_FatEntryPtr
                POP  IX
                JP   C, .fail
                LD   (RawPak_FatPtr), HL
                JP   .enter
.jump:          LD   A, (RawPak_RunCount)
                CP   RAWPAK_RUN_MAX
                JP   NC, .fail
                INC  A
                LD   (RawPak_RunCount), A
                LD   DE, 6
                ADD  IX, DE
                LD   HL, RawPak_NextClus
                LD   DE, RawPak_CurClus
                CALL RawPak_Copy32
                CALL RawPak_CurrentLbaRegs
                LD   (IX + 0), L
                LD   (IX + 1), H
                LD   (IX + 2), E
                LD   (IX + 3), D
                LD   (IX + 4), 0
                LD   (IX + 5), 0
                PUSH IX
                CALL RawPak_FatEntryPtr
                POP  IX
                JP   C, .fail
                LD   (RawPak_FatPtr), HL
                JP   .enter
.done:          SCF
                RET
.fail:          OR   A
                RET
RawPak_FatEntryPtr:
                LD   HL, RawPak_CurClus
                LD   DE, RawPak_Tmp
                CALL RawPak_Copy32
                LD   B, 7
.shr:           CALL RawPak_ShrTmp1
                DJNZ .shr
                LD   HL, RawPak_FatStart
                LD   DE, RawPak_Tmp
                CALL RawPak_Add32
                LD   HL, RawPak_Tmp
                LD   DE, RawPak_FatBufLba
                CALL RawPak_Cmp32
                JR   Z, .have
                LD   HL, (RawPak_Tmp)
                LD   DE, (RawPak_Tmp + 2)
                CALL RawPak_ReadFatSector
                RET  C
                LD   HL, RawPak_Tmp
                LD   DE, RawPak_FatBufLba
                CALL RawPak_Copy32
.have:          LD   A, (RawPak_CurClus)
                AND  127
                LD   L, A
                LD   H, 0
                ADD  HL, HL
                ADD  HL, HL
                LD   DE, RawPak_FatBuf
                ADD  HL, DE
                OR   A
                RET

; --- read file sectors через run-table -> dest page/off ---
; Вход: C=dest page (slot2 window), HL=dest offset, B=count.
RawPak_ReadSectors:
                LD   A, B
                OR   A
                RET  Z
                LD   A, C
                LD   (RawPak_DstPage), A
                LD   (RawPak_DstOff), HL
                LD   A, B
                LD   (RawPak_ReadCount), A
.loop:          LD   A, (RawPak_DstPage)
                SetPage2_A
                LD   HL, (RawPak_DstOff)
                LD   DE, RAWPAK_SEC_BUF
                ADD  HL, DE
                PUSH HL
                POP  IX
                CALL RawPak_ReadOneLogicalIX
                JR   C, .err
                LD   HL, (RawPak_DstOff)
                LD   DE, #0200
                ADD  HL, DE
                BIT  6, H                       ; перешли за #C000 в slot2-окне?
                JR   Z, .same
                RES  6, H
                LD   A, (RawPak_DstPage)
                INC  A
                LD   (RawPak_DstPage), A
.same:          LD   (RawPak_DstOff), HL
                LD   A, (RawPak_ReadCount)
                DEC  A
                LD   (RawPak_ReadCount), A
                JR   NZ, .loop
                OR   A
                RET
.err:           SCF
                RET
RawPak_ReadOneLogicalIX:
                PUSH IX
                LD   DE, (RawPak_LogCur)
                LD   IX, RawPak_RunTable
                LD   A, (RawPak_RunCount)
                LD   B, A
.scan:          LD   L, (IX + 4)
                LD   H, (IX + 5)
                LD   A, D
                CP   H
                JR   C, .found
                JR   NZ, .sub
                LD   A, E
                CP   L
                JR   C, .found
.sub:           LD   A, E
                SUB  L
                LD   E, A
                LD   A, D
                SBC  A, H
                LD   D, A
                PUSH DE
                LD   DE, 6
                ADD  IX, DE
                POP  DE
                DJNZ .scan
                POP  IX
                SCF
                RET
.found:         LD   L, (IX + 0)
                LD   H, (IX + 1)
                ADD  HL, DE
                EX   DE, HL
                LD   L, (IX + 2)
                LD   H, (IX + 3)
                JR   NC, .noCy
                INC  HL
.noCy:          EX   DE, HL
                POP  IX
                CALL sd_read_sector
                LD   HL, (RawPak_LogCur)
                INC  HL
                LD   (RawPak_LogCur), HL
                RET

; --- low-level reads ---
RawPak_ReadSectorBuffer:
                LD   A, RAWPAK_BUF_PAGE
                SetPage2_A
                LD   IX, RAWPAK_SEC_BUF
                JP   sd_read_sector
RawPak_ReadFatSector:
                LD   IX, RawPak_FatBuf
                JP   sd_read_sector
RawPak_ReadPartBpb:
                LD   HL, (RawPak_PartLba + 0)
                LD   DE, (RawPak_PartLba + 2)
                CALL RawPak_ReadSectorBuffer
                RET  C
                LD   IX, RAWPAK_SEC_BUF
                LD   A, (IX + 11)
                OR   A
                JR   NZ, .bad
                LD   A, (IX + 12)
                CP   2
                JR   NZ, .bad
                OR   A
                RET
.bad:           SCF
                RET

; --- 32-bit helpers ---
RawPak_Copy32:  PUSH BC
                LD   BC, 4
                LDIR
                POP  BC
                RET
RawPak_Add32:   PUSH BC
                LD   B, 4
                OR   A
.a:             LD   A, (DE)
                ADC  A, (HL)
                LD   (DE), A
                INC  HL
                INC  DE
                DJNZ .a
                POP  BC
                RET
RawPak_Cmp32:   LD   B, 4
.c:             LD   A, (DE)
                CP   (HL)
                RET  NZ
                INC  HL
                INC  DE
                DJNZ .c
                RET
RawPak_ShrTmp1: LD   HL, RawPak_Tmp + 3
                SRL  (HL)
                DEC  HL
                RR   (HL)
                DEC  HL
                RR   (HL)
                DEC  HL
                RR   (HL)
                RET
RawPak_IncTmp32:
                LD   HL, RawPak_Tmp
                INC  (HL)
                RET  NZ
                INC  HL : INC (HL)
                RET  NZ
                INC  HL : INC (HL)
                RET  NZ
                INC  HL : INC (HL)
                RET

; --- state ---
RawPak_Spc:            DEFB 0
RawPak_CurSecInClus:   DEFB 0
RawPak_ReadCount:      DEFB 0
RawPak_DstPage:        DEFB 0
RawPak_DstOff:         DEFW 0
RawPak_TargetName:     DEFS 64
RawPak_EntName:        DEFS 64
RawPak_CheckSize:      DEFB 0
RawPak_FoundSize:      DEFS 4
RawPak_HaveLfn:        DEFB 0
RawPak_PartLba:        DEFS 4
RawPak_FatStart:       DEFS 4
RawPak_DataStart:      DEFS 4
RawPak_RootClus:       DEFS 4
RawPak_FileStartClus:  DEFS 4
RawPak_CurClus:        DEFS 4
RawPak_Tmp:            DEFS 4
RawPak_FatBuf:         DEFS 512
RawPak_FatBufLba:      DEFS 4
RawPak_NextClus:       DEFS 4
RawPak_FatPtr:         DEFW 0
RawPak_RunCount:       DEFB 0
RawPak_RunTable:       DEFS RAWPAK_RUN_MAX * 6
RawPak_LogCur:         DEFW 0
RawPak_DirStackCnt:    DEFB 0
RawPak_DirStack:       DEFS RAWPAK_DIRSTACK_MAX * 4

