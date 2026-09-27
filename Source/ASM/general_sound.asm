; ============================================================================
; General Sound / MultiSound transport for arcade R-Type audio.
;
; The PCM is prepared offline from two deterministic MAME runs.  At boot it is
; streamed from SPG pages to GS as one unsigned sample; runtime only sends the
; preloaded handle, note and volume.  Every #B3 write follows the hardware-safe
; Wild Commander/Zuma order: wait for #BB bit7=0, then OUT to #B3.
; ============================================================================

GS_PORT_DATA          EQU #00B3
GS_PORT_CMD           EQU #00BB
GS_WAIT_TIMEOUT       EQU #FFFF

GS_CMD_RESET          EQU #F3
GS_CMD_RAM_PAGES      EQU #23
GS_CMD_FX_VOLUME      EQU #2B
GS_CMD_LOAD_FX        EQU #38
GS_CMD_SELECT_FX      EQU #2E
GS_CMD_SAMPLE_NOTE    EQU #40
GS_CMD_SAMPLE_VOLUME  EQU #41
GS_CMD_PRIORITY       EQU #45
GS_CMD_SEEK_FIRST     EQU #46
GS_CMD_SEEK_LAST      EQU #47
GS_CMD_OPEN_STREAM    EQU #D1
GS_CMD_CLOSE_STREAM   EQU #D2
GS_CMD_PLAY_FX        EQU #98

; 11025 Hz payload calibration inherited from the hardware-proven Zuma GS
; path.  It remains a target-hardware tuning constant for this R-Type sample.
GS_WAVE_NOTE          EQU 53
; Обычный выстрел записан на 22050 Гц, вдвое выше остальных эффектов, поэтому
; играется нотой на октаву выше: скорость воспроизведения у General Sound
; задаётся нотой, и +12 полутонов — это ровно вдвое.
;
; Причина иной частоты: у выстрела 43 % энергии лежит выше 5.5 кГц — предела
; Найквиста для 11025 Гц. На общей частоте он терял характер, тогда как Wave
; Cannon (низкий гул) звучал верно.
GS_SHOT_NOTE          EQU GS_WAVE_NOTE + 12
GS_WAVE_VOLUME        EQU #40
GS_WAVE_PRIORITY      EQU #C0
GS_WAVE_CHANNEL       EQU 0

; Resident state directly after arcade_game.asm's #4200..#4213 block.
GeneralSound_Present       EQU #4214
GeneralSound_FxLoaded      EQU #4215
GeneralSound_WaveHandle    EQU #4216
GeneralSound_RamPages      EQU #4217
GeneralSound_LastError     EQU #4218 ; 0=OK, 1=no GS, 2=load/protocol failure
GeneralSound_StreamTable   EQU #4219 ; word
GeneralSound_StreamLength  EQU #421B ; word
GeneralSound_StreamCount   EQU #421D ; byte
GeneralSound_ShotHandle    EQU #421E ; handle обычного выстрела (команда $30)
GeneralSound_LastHandle    EQU #421F ; handle последней загрузки (возврат #38)

GeneralSound_Init:
                XOR  A
                LD   (GeneralSound_Present), A
                LD   (GeneralSound_FxLoaded), A
                LD   (GeneralSound_RamPages), A
                LD   (GeneralSound_LastError), A
                DEC  A
                LD   (GeneralSound_WaveHandle), A

                LD   A, GS_CMD_RESET
                CALL GeneralSound_SendCommand
                JR   NC, .absent
                LD   A, 1
                LD   (GeneralSound_Present), A

                LD   A, GS_CMD_RAM_PAGES
                CALL GeneralSound_SendCommand
                JR   NC, .failed
                CALL GeneralSound_ReadDataWait
                JR   C, .haveRamPages
                ; Unreal BASS-HLE 0.37.9 возвращает результат #23 в #B3,
                ; но оставляет статус #BB=$7E (bit7 data-ready не ставит).
                ; На реальном MultiSound сначала отрабатывает штатное ожидание
                ; выше; прямое чтение — только fallback после его таймаута.
                LD   BC, GS_PORT_DATA
                IN   A, (C)
                OR   A
                JR   Z, .failed
                CP   #FF
                JR   Z, .failed
.haveRamPages:
                LD   (GeneralSound_RamPages), A

                LD   A, #40
                CALL GeneralSound_SendData
                JR   NC, .failed
                LD   A, GS_CMD_FX_VOLUME
                CALL GeneralSound_SendCommand
                JR   NC, .failed

                ; Два эффекта в свои FX-слоты: $31 Wave Cannon и $30 выстрел.
                LD   HL, GSWavePageTable
                LD   A, GS_WAVE_PAGE_COUNT
                CALL GeneralSound_LoadEffect
                JR   NC, .failed
                LD   A, (GeneralSound_LastHandle)
                LD   (GeneralSound_WaveHandle), A
                LD   HL, GSShotPageTable
                LD   A, GS_SHOT_PAGE_COUNT
                CALL GeneralSound_LoadEffect
                JR   NC, .failed
                LD   A, (GeneralSound_LastHandle)
                LD   (GeneralSound_ShotHandle), A
                LD   A, 1
                LD   (GeneralSound_FxLoaded), A
                XOR  A
                LD   (GeneralSound_LastError), A
                SetPage3 0
                SCF
                RET

.absent:       LD   A, 1
                JR   .recordFailure
.failed:       LD   A, 2
.recordFailure:
                LD   (GeneralSound_LastError), A
                XOR  A
                LD   (GeneralSound_FxLoaded), A
                SetPage3 0
                OR   A
                RET

; Загрузка одного эффекта: HL = таблица страниц SPG, A = число страниц.
; Полученный handle остаётся в GeneralSound_LastHandle.
GeneralSound_LoadEffect:
                LD   (GeneralSound_StreamTable), HL
                LD   (GeneralSound_StreamCount), A
                LD   A, GS_CMD_LOAD_FX
                CALL GeneralSound_SendCommand
                RET  NC
                ; #38 returns the FX handle after command completion, without WN.
                LD   BC, GS_PORT_DATA
                IN   A, (C)
                LD   (GeneralSound_LastHandle), A
                CALL GeneralSound_SendData
                RET  NC
                LD   A, GS_CMD_SELECT_FX
                CALL GeneralSound_SendCommand
                RET  NC

                LD   A, GS_WAVE_NOTE
                CALL GeneralSound_SendData
                RET  NC
                LD   A, GS_CMD_SAMPLE_NOTE
                CALL GeneralSound_SendCommand
                RET  NC
                LD   A, GS_WAVE_VOLUME
                CALL GeneralSound_SendData
                RET  NC
                LD   A, GS_CMD_SAMPLE_VOLUME
                CALL GeneralSound_SendCommand
                RET  NC
                LD   A, GS_WAVE_PRIORITY
                CALL GeneralSound_SendData
                RET  NC
                LD   A, GS_CMD_PRIORITY
                CALL GeneralSound_SendCommand
                RET  NC
                LD   A, #FF
                CALL GeneralSound_SendData
                RET  NC
                LD   A, GS_CMD_SEEK_FIRST
                CALL GeneralSound_SendCommand
                RET  NC
                LD   A, #FF
                CALL GeneralSound_SendData
                RET  NC
                LD   A, GS_CMD_SEEK_LAST
                CALL GeneralSound_SendCommand
                RET  NC

                LD   A, GS_CMD_OPEN_STREAM
                CALL GeneralSound_SendCommand
                RET  NC
                CALL GeneralSound_StreamWavePages
                JR   NC, .streamFailed
                LD   A, GS_CMD_CLOSE_STREAM
                JP   GeneralSound_SendCommand
.streamFailed: LD   A, GS_CMD_CLOSE_STREAM
                CALL GeneralSound_SendCommand
                OR   A
                RET

; Copy the generated SPG page table to GS.  DE is a true byte count, so a
; partial final page is supported without transmitting unrelated bytes.
GeneralSound_StreamWavePages:
                ; Таблица и счётчик уже заданы вызывающим (GeneralSound_LoadEffect).
.page:         LD   HL, (GeneralSound_StreamTable)
                LD   A, (HL)
                INC  HL
                LD   E, (HL)
                INC  HL
                LD   D, (HL)
                INC  HL
                LD   (GeneralSound_StreamTable), HL
                LD   (GeneralSound_StreamLength), DE
                SetPage3_A
                LD   HL, #C000
                LD   DE, (GeneralSound_StreamLength)
                CALL GeneralSound_StreamBuffer
                RET  NC
                LD   HL, GeneralSound_StreamCount
                DEC  (HL)
                JR   NZ, .page
                SCF
                RET

GeneralSound_StreamBuffer:
                LD   A, D
                OR   E
                JR   Z, .done
.byte:         LD   A, (HL)
                INC  HL
                CALL GeneralSound_SendData
                RET  NC
                DEC  DE
                LD   A, D
                OR   E
                JR   NZ, .byte
.done:         SCF
                RET

; Called once after ArcadeGame_Update.  A pending Wave Cannon shot is consumed
; by the next game tick; no PCM conversion or upload happens in this path.
GeneralSound_Update:
                LD   A, (GeneralSound_Present)
                OR   A
                RET  Z
                LD   A, (GeneralSound_FxLoaded)
                OR   A
                RET  Z

                ; Обычный выстрел — свой эффект; фронт снимается здесь.
                LD   A, (ArcadeShotPending)
                OR   A
                JR   Z, .checkWave
                XOR  A
                LD   (ArcadeShotPending), A
                LD   A, (GeneralSound_ShotHandle)
                LD   D, GS_SHOT_NOTE
                CALL GeneralSound_PlayHandle
                JR   NC, GeneralSound_RuntimeFailure

.checkWave:     LD   A, (ArcadeWaveShotPending)
                OR   A
                RET  Z
                LD   A, (GeneralSound_WaveHandle)
                LD   D, GS_WAVE_NOTE
                ; fall through

; A = handle эффекта, D = нота (скорость воспроизведения). CF=1 при успехе.
; D переживает оба вызова: SendData сохраняет DE, SendCommand его не трогает.
GeneralSound_PlayHandle:
                CALL GeneralSound_SendData
                JR   NC, GeneralSound_RuntimeFailure
                LD   A, GS_CMD_PLAY_FX + GS_WAVE_CHANNEL
                CALL GeneralSound_SendCommand
                JR   NC, GeneralSound_RuntimeFailure
                LD   A, D
                CALL GeneralSound_SendData
                JR   NC, GeneralSound_RuntimeFailure
                LD   A, GS_WAVE_VOLUME
                CALL GeneralSound_SendData
                RET  C

GeneralSound_RuntimeFailure:
                LD   A, 2
                LD   (GeneralSound_LastError), A
                XOR  A
                LD   (GeneralSound_FxLoaded), A
                RET

; A = command.  Completion is #BB bit0=0; carry reports success.
GeneralSound_SendCommand:
                LD   BC, GS_PORT_CMD
                OUT  (C), A
                LD   HL, GS_WAIT_TIMEOUT
.wait:         IN   A, (C)
                RRCA
                JR   NC, .ready
                DEC  HL
                LD   A, H
                OR   L
                JR   NZ, .wait
                OR   A
                RET
.ready:        SCF
                RET

; A = data.  Real MultiSound requires waiting for FIFO space before OUT #B3.
GeneralSound_SendData:
                PUSH HL
                PUSH DE
                LD   E, A
                LD   BC, GS_PORT_CMD
                LD   HL, GS_WAIT_TIMEOUT
.wait:         IN   A, (C)
                RLCA
                JR   NC, .ready
                DEC  HL
                LD   A, H
                OR   L
                JR   NZ, .wait
                POP  DE
                POP  HL
                OR   A
                RET
.ready:        LD   A, E
                LD   BC, GS_PORT_DATA
                OUT  (C), A
                POP  DE
                POP  HL
                SCF
                RET

; Wait for #BB bit7=1, then read one byte from #B3.
GeneralSound_ReadDataWait:
                LD   BC, GS_PORT_CMD
                LD   HL, GS_WAIT_TIMEOUT
.wait:         IN   A, (C)
                RLCA
                JR   C, .ready
                DEC  HL
                LD   A, H
                OR   L
                JR   NZ, .wait
                OR   A
                RET
.ready:        LD   BC, GS_PORT_DATA
                IN   A, (C)
                SCF
                RET
