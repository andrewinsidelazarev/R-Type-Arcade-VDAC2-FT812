"""Состояние машины M72 после загрузки ROM — начальная точка переведённой программы.

Полный runtime при создании накладывает патч баланса и проходит тесты ROM до цикла
простоя (`RTypeM72Machine.boot`). Этот участок не зависит от ввода и времени, поэтому
Z80-программа начинает с того же состояния: памяти V30 1 МБ, регистров, PIC, видео-
регистров и зеркал палитры. Состояние берётся у эталонной машины.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
for extra in (ROOT / 'Build' / 'PythonDeps', ROOT / 'Source' / 'Tools', ROOT / 'Source' / 'Python'):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))
os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')

REGISTERS = ('ax', 'cx', 'dx', 'bx', 'sp', 'bp', 'si', 'di')
SEGMENTS = ('es', 'cs', 'ss', 'ds')


@dataclass
class MachineState:
    memory: bytes
    registers: dict[str, int]
    flags: int
    ip: int
    pic: tuple[int, int, int]
    video: dict[str, object]
    inputs: tuple[int, int, int]
    sprite_buffer: bytes
    palettes: tuple[bytes, bytes]


def new_reference_machine(sound_command=None):
    """Эталонная машина полного runtime: патчи баланса и исправлений, затем загрузка ROM."""
    from rtype_m72.machine import RTypeM72Machine
    from rtype_port.full_runtime import (
        ATTRACT_GAME_OVER_X_HIGH_ADDRESS, BONUS_LIFE_TABLES, DSW_LIVES_TABLE_ADDRESS, INITIAL_LIVES,
        LIVES_CAP_IMMEDIATE_ADDRESS, MAX_LIVES, _bonus_life_table)
    machine = RTypeM72Machine(sound_command)
    # Те же записи, что FullRuntimeGame._apply_balance и _apply_fixes: транслятор
    # берёт код из этой памяти, поэтому патченные immediate попадают в Z80-код.
    machine.cpu.mem_write(DSW_LIVES_TABLE_ADDRESS, bytes((INITIAL_LIVES,)) * 4)
    machine.cpu.mem_write(LIVES_CAP_IMMEDIATE_ADDRESS, bytes((MAX_LIVES,)))
    for address, thresholds in BONUS_LIFE_TABLES:
        machine.cpu.mem_write(address, _bonus_life_table(thresholds))
    machine.cpu.mem_write(ATTRACT_GAME_OVER_X_HIGH_ADDRESS, b'\x00')
    machine.boot()
    return machine


def restore_board_bytes(machine, memory: bytearray, base: int) -> None:
    """Эталон заменяет двухбайтовый ADD4S NEC на NOP NOP с перехватом (unicorn не знает
    опкод V30). На плате по этим адресам исходные байты ROM: они возвращаются в копию
    памяти `memory`, начинающуюся с линейного адреса `base`."""
    from rtype_m72.machine import V30_ADD4S_ADDRESSES
    rom = machine.regions['maincpu']
    for address in V30_ADD4S_ADDRESSES:
        if base <= address and address + 2 <= base + len(memory):
            memory[address - base:address - base + 2] = rom[address:address + 2]


STACK_GARBAGE = 512             # байт стека V30 ниже SP, которые сверка не сравнивает


def mask_stack_garbage(ours: bytearray, theirs: bytearray, base: int, sp: int) -> None:
    """Остатки стека V30 ниже SP (SS = #4000) в копиях страницы с линейного адреса `base` обнуляются в обеих:
    код ROM оставляет там адреса возврата и сохранённые регистры, нативные ядра резидента
    (v30z80_kernels.asm) — нет; ROM ниже SP не читает."""
    low = max(0x40000, 0x40000 + sp - STACK_GARBAGE)
    high = 0x40000 + sp
    for address in range(max(low, base), min(high, base + len(ours))):
        ours[address - base] = 0
        theirs[address - base] = 0


def patch_second_bytes() -> set[int]:
    """Адреса второго NOP патча ADD4S: эталон исполняет их, на плате это не начало инструкции."""
    from rtype_m72.machine import V30_ADD4S_ADDRESSES
    return {address + 1 for address in V30_ADD4S_ADDRESSES}


def capture(machine) -> MachineState:
    from unicorn import x86_const as X
    cpu = machine.cpu
    names = {'ax': X.UC_X86_REG_AX, 'cx': X.UC_X86_REG_CX, 'dx': X.UC_X86_REG_DX, 'bx': X.UC_X86_REG_BX,
             'sp': X.UC_X86_REG_SP, 'bp': X.UC_X86_REG_BP, 'si': X.UC_X86_REG_SI, 'di': X.UC_X86_REG_DI,
             'es': X.UC_X86_REG_ES, 'cs': X.UC_X86_REG_CS, 'ss': X.UC_X86_REG_SS, 'ds': X.UC_X86_REG_DS}
    registers = {name: cpu.reg_read(reg) & 0xFFFF for name, reg in names.items()}
    video = machine.video
    memory = bytearray(cpu.mem_read(0, 0x100000))
    restore_board_bytes(machine, memory, 0)
    return MachineState(
        memory=bytes(memory),
        registers=registers,
        flags=cpu.reg_read(X.UC_X86_REG_EFLAGS) & 0xFFFF,
        ip=cpu.reg_read(X.UC_X86_REG_IP) & 0xFFFF,
        pic=(machine.pic.vector_base, machine.pic.mask, machine.pic._icw_step),
        video={'scroll_x': list(video.scroll_x), 'scroll_y': list(video.scroll_y),
               'raster': video.raster_irq_position, 'video_off': video.video_off,
               'flip': video.flip_screen, 'dma': video.sprite_dma_count},
        inputs=(machine.inputs.in0, machine.inputs.in1, machine.inputs.dsw),
        sprite_buffer=bytes(machine.buffered_sprite_ram),
        palettes=(bytes(machine.palette_ram[0]), bytes(machine.palette_ram[1])),
    )
