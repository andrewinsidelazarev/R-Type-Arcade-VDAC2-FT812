"""Минимальная точная модель платы M72 для исполнения оригинального V30 ROM."""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parents[3]
TOOLS_DIR = ROOT / "Source" / "Tools"
DEPS_DIR = ROOT / "Build" / "PythonDeps"
for search_dir in (str(TOOLS_DIR), str(DEPS_DIR)):
    if search_dir not in sys.path:
        sys.path.insert(0, search_dir)

from m72_arcade import assemble_regions
from unicorn import Uc, UcError
from unicorn.unicorn_const import UC_ARCH_X86, UC_HOOK_CODE, UC_HOOK_INSN, UC_HOOK_INSN_INVALID
from unicorn.unicorn_const import UC_HOOK_MEM_WRITE
from unicorn.unicorn_const import UC_MODE_16
from unicorn.x86_const import UC_X86_INS_IN, UC_X86_INS_OUT
from unicorn.x86_const import (
    UC_X86_REG_CS, UC_X86_REG_CX, UC_X86_REG_DI, UC_X86_REG_DS,
    UC_X86_REG_EFLAGS, UC_X86_REG_ES, UC_X86_REG_IP, UC_X86_REG_SI,
    UC_X86_REG_SP, UC_X86_REG_SS,
)


MEMORY_SIZE = 0x100000
ROM_END = 0x40000
WORK_RAM = slice(0x40000, 0x44000)
SPRITE_RAM = slice(0xC0000, 0xC0400)
PALETTE_0 = slice(0xC8000, 0xC8C00)
PALETTE_1 = slice(0xCC000, 0xCCC00)
VIDEO_RAM_0 = slice(0xD0000, 0xD4000)
VIDEO_RAM_1 = slice(0xD8000, 0xDC000)
SOUND_RAM = slice(0xE0000, 0xF0000)

CPU_CLOCK = 8_000_000
PIXEL_CLOCK = 8_000_000
HTOTAL = 512
VTOTAL = 284
FRAME_RATE = PIXEL_CLOCK / HTOTAL / VTOTAL

# Unicorn исполняет `$0F20` как более поздний x86 MOV CR и съедает следующий
# байт, тогда как V30 World ROM использует двухбайтовый ADD4S. Линейные адреса
# включают базу CS=$0040; оба вызова принадлежат автомату начисления очков.
V30_ADD4S_ADDRESSES = (0x0ECEF, 0x0ED09)


@dataclass
class Inputs:
    """Активно-низкие входы M72 в точном формате портов IN0/IN1/DSW."""

    in0: int = 0xFFFF
    in1: int = 0xFF7F
    dsw: int = 0xFDFB

    def set_player(self, *, right: bool = False, left: bool = False,
                   down: bool = False, up: bool = False,
                   button1: bool = False, button2: bool = False) -> None:
        mask = 0
        for active, bit in ((right, 0x0001), (left, 0x0002),
                            (down, 0x0004), (up, 0x0008),
                            (button2, 0x0040), (button1, 0x0080)):
            if active:
                mask |= bit
        self.in0 = (self.in0 | 0x00CF) & ~mask

    def set_system(self, *, start1: bool = False, coin1: bool = False) -> None:
        mask = (0x0001 if start1 else 0) | (0x0004 if coin1 else 0)
        self.in1 = (self.in1 | 0x0005) & ~mask


@dataclass
class VideoRegisters:
    scroll_y: list[int] = field(default_factory=lambda: [0, 0])
    scroll_x: list[int] = field(default_factory=lambda: [0, 0])
    raster_irq_position: int = 0
    video_off: bool = False
    flip_screen: bool = False
    sprite_dma_count: int = 0


@dataclass(frozen=True)
class FrameState:
    """Видеопамять и построчные регистры одного завершённого кадра."""

    vram0: bytes
    vram1: bytes
    palette0: bytes
    palette1: bytes
    spriteram: bytes
    row_scroll: tuple[tuple[int, int, int, int], ...]
    video_off: bool


class Pic8259:
    """Часть uPD71059C, которую R-Type использует для двух кадровых IRQ."""

    def __init__(self) -> None:
        self.vector_base = 0x08
        self._icw_step = 0
        self.mask = 0xFF

    def write(self, register: int, value: int) -> None:
        value &= 0xFF
        if register == 0:
            if value & 0x10:
                self._icw_step = 1
                self.mask = 0
            return
        if self._icw_step == 1:
            self.vector_base = value & 0xF8
            self._icw_step = 2
        elif self._icw_step in (2, 3):
            self._icw_step += 1
        else:
            self.mask = value

    def read(self, register: int) -> int:
        return 0 if register == 0 else self.mask


class RTypeM72Machine:
    """Исполняет ROM World на x86-16 и сохраняет аппаратное состояние M72."""

    def __init__(self, sound_command: Callable[[int], None] | None = None) -> None:
        self.regions = assemble_regions()
        self.inputs = Inputs()
        self.video = VideoRegisters()
        self.pic = Pic8259()
        self.sound_command = sound_command
        self.sound_latch: list[int] = []
        self.port_log: list[tuple[int, int, int]] = []
        self.buffered_sprite_ram = bytes(SPRITE_RAM.stop - SPRITE_RAM.start)
        self.palette_ram = [bytearray(0xC00), bytearray(0xC00)]
        self.invalid_address: int | None = None
        self.waiting_for_interrupt = False
        self.cpu = Uc(UC_ARCH_X86, UC_MODE_16)
        self.cpu.mem_map(0, MEMORY_SIZE)
        self.cpu.mem_write(0, self.regions["maincpu"])
        # В памяти экземпляра две инструкции заменяются двумя NOP. Арифметику
        # до первого NOP выполняют точечные hooks ниже; исходный ROM-образ и
        # `regions["maincpu"]` остаются неизменными.
        for address in V30_ADD4S_ADDRESSES:
            self.cpu.mem_write(address, b"\x90\x90")
            self.cpu.hook_add(
                UC_HOOK_CODE, self._add4s_hook, None, address, address)
        self.cpu.hook_add(UC_HOOK_INSN, self._port_in, None, 1, 0, UC_X86_INS_IN)
        self.cpu.hook_add(UC_HOOK_INSN, self._port_out, None, 1, 0, UC_X86_INS_OUT)
        self.cpu.hook_add(UC_HOOK_CODE, self._idle_hook, None, 0x392FB, 0x392FB)
        self.cpu.hook_add(UC_HOOK_CODE, self._main_idle_hook, None, 0x004D6, 0x004D6)
        self.cpu.hook_add(UC_HOOK_MEM_WRITE, self._palette_write, 0,
                          PALETTE_0.start, PALETTE_0.stop - 1)
        self.cpu.hook_add(UC_HOOK_MEM_WRITE, self._palette_write, 1,
                          PALETTE_1.start, PALETTE_1.stop - 1)
        self.cpu.hook_add(UC_HOOK_INSN_INVALID, self._invalid_instruction)
        self.reset()

    def reset(self) -> None:
        """Установить аппаратный reset-вектор V30 FFFF:0000."""
        self.cpu.mem_write(WORK_RAM.start, bytes(WORK_RAM.stop - WORK_RAM.start))
        for area in (SPRITE_RAM, PALETTE_0, PALETTE_1, VIDEO_RAM_0, VIDEO_RAM_1, SOUND_RAM):
            self.cpu.mem_write(area.start, bytes(area.stop - area.start))
        self.cpu.reg_write(UC_X86_REG_CS, 0xFFFF)
        self.cpu.reg_write(UC_X86_REG_IP, 0)
        self.cpu.reg_write(UC_X86_REG_SS, 0)
        self.cpu.reg_write(UC_X86_REG_SP, 0)
        self.cpu.reg_write(UC_X86_REG_EFLAGS, 0x0002)
        self.waiting_for_interrupt = False
        self.invalid_address = None
        self.palette_ram[0][:] = bytes(0xC00)
        self.palette_ram[1][:] = bytes(0xC00)

    def linear_pc(self) -> int:
        return ((self.cpu.reg_read(UC_X86_REG_CS) << 4) +
                self.cpu.reg_read(UC_X86_REG_IP)) & 0xFFFFF

    def run(self, instruction_limit: int = 1_000_000) -> int:
        """Исполнять до HLT, ошибки или заданного числа инструкций."""
        self.waiting_for_interrupt = False
        start = self.linear_pc()
        try:
            self.cpu.emu_start(start, MEMORY_SIZE, count=instruction_limit)
        except UcError as error:
            if self.invalid_address is not None:
                raise RuntimeError(
                    f"V30 opcode не поддержан по адресу {self.invalid_address:05X}") from error
            raise
        return self.linear_pc()

    def boot(self) -> None:
        """Пройти штатные тесты ROM до разрешения прерываний и idle-loop."""
        self.run(50_000_000)
        if not self.waiting_for_interrupt:
            raise RuntimeError(f"V30 не дошёл до idle-loop: PC={self.linear_pc():05X}")

    def interrupt(self, irq: int, instruction_limit: int = 1_000_000) -> None:
        """Подать аппаратный IRQ через таблицу векторов, настроенную uPD71059C."""
        if not 0 <= irq <= 7:
            raise ValueError("номер IRQ должен быть в диапазоне 0..7")
        if self.pic.mask & (1 << irq):
            return
        flags = self.cpu.reg_read(UC_X86_REG_EFLAGS) & 0xFFFF
        cs = self.cpu.reg_read(UC_X86_REG_CS) & 0xFFFF
        ip = self.cpu.reg_read(UC_X86_REG_IP) & 0xFFFF
        ss = self.cpu.reg_read(UC_X86_REG_SS) & 0xFFFF
        sp = self.cpu.reg_read(UC_X86_REG_SP) & 0xFFFF
        for word in (flags, cs, ip):
            sp = (sp - 2) & 0xFFFF
            linear = ((ss << 4) + sp) & 0xFFFFF
            self.cpu.mem_write(linear, word.to_bytes(2, "little"))
        self.cpu.reg_write(UC_X86_REG_SP, sp)
        self.cpu.reg_write(UC_X86_REG_EFLAGS, flags & ~0x0300)
        vector = self.pic.vector_base + irq
        entry = bytes(self.cpu.mem_read(vector * 4, 4))
        self.cpu.reg_write(UC_X86_REG_IP, int.from_bytes(entry[0:2], "little"))
        self.cpu.reg_write(UC_X86_REG_CS, int.from_bytes(entry[2:4], "little"))
        self.run(instruction_limit)
        if not self.waiting_for_interrupt:
            raise RuntimeError(f"обработчик IRQ{irq} не вернулся в idle-loop")

    def step_frame(self) -> FrameState:
        """Вернуть текущий кадр и выполнить IRQ, готовящие следующий кадр."""
        initial = (self.video.scroll_x[0], self.video.scroll_y[0],
                   self.video.scroll_x[1], self.video.scroll_y[1])
        raster = self.video.raster_irq_position
        rows = [initial] * 256
        vram0 = self.memory(VIDEO_RAM_0)
        vram1 = self.memory(VIDEO_RAM_1)
        palette0 = bytes(self.palette_ram[0])
        palette1 = bytes(self.palette_ram[1])
        spriteram = self.buffered_sprite_ram
        video_off = self.video.video_off
        if 0 <= raster < 256:
            self.interrupt(2)
            after_raster = (self.video.scroll_x[0], self.video.scroll_y[0],
                            self.video.scroll_x[1], self.video.scroll_y[1])
            rows[raster:] = [after_raster] * (256 - raster)
        self.interrupt(0)
        return FrameState(vram0, vram1, palette0, palette1, spriteram,
                          tuple(rows), video_off)

    def _idle_hook(self, cpu: Uc, address: int, size: int, _: object) -> None:
        self.waiting_for_interrupt = True
        cpu.emu_stop()

    def _main_idle_hook(self, cpu: Uc, address: int, size: int, _: object) -> None:
        head = int.from_bytes(cpu.mem_read(0x42ED8, 2), "little")
        tail = int.from_bytes(cpu.mem_read(0x42EDA, 2), "little")
        if head == tail:
            self.waiting_for_interrupt = True
            cpu.emu_stop()

    def _palette_write(self, cpu: Uc, access: int, address: int,
                       size: int, value: int, bank: int) -> None:
        base = PALETTE_0.start if bank == 0 else PALETTE_1.start
        relative = address - base
        for lane in range(size):
            byte_address = relative + lane
            word_offset = byte_address >> 1
            canonical_word = word_offset & ~0x100
            canonical_byte = canonical_word * 2 + (byte_address & 1)
            self.palette_ram[bank][canonical_byte] = (value >> (lane * 8)) & 0xFF

    def _invalid_instruction(self, cpu: Uc, _: object) -> bool:
        self.invalid_address = self.linear_pc()
        return False

    def _add4s_hook(self, cpu: Uc, _: int, __: int, ___: object) -> None:
        """Исполнить V30 ADD4S для строк packed BCD DS:SI → ES:DI."""
        count = ((cpu.reg_read(UC_X86_REG_CX) & 0xFF) + 1) // 2
        source_segment = cpu.reg_read(UC_X86_REG_DS) & 0xFFFF
        target_segment = cpu.reg_read(UC_X86_REG_ES) & 0xFFFF
        source_offset = cpu.reg_read(UC_X86_REG_SI) & 0xFFFF
        target_offset = cpu.reg_read(UC_X86_REG_DI) & 0xFFFF
        carry = 0
        zero = True
        for index in range(count):
            source_address = (
                (source_segment << 4) + ((source_offset + index) & 0xFFFF)
            ) & 0xFFFFF
            target_address = (
                (target_segment << 4) + ((target_offset + index) & 0xFFFF)
            ) & 0xFFFFF
            source = int(cpu.mem_read(source_address, 1)[0])
            target = int(cpu.mem_read(target_address, 1)[0])
            source_decimal = (source >> 4) * 10 + (source & 0x0F)
            target_decimal = (target >> 4) * 10 + (target & 0x0F)
            result = source_decimal + target_decimal + carry
            carry = int(result > 99)
            result %= 100
            packed = ((result // 10) << 4) | (result % 10)
            cpu.mem_write(target_address, bytes((packed,)))
            zero = zero and packed == 0

        flags = cpu.reg_read(UC_X86_REG_EFLAGS)
        flags = (flags & ~0x0041) | carry | (0x0040 if zero else 0)
        cpu.reg_write(UC_X86_REG_EFLAGS, flags)

    @staticmethod
    def _byte_from_word(word: int, port: int, base: int, size: int) -> int:
        if size == 2:
            return word
        return (word >> (8 if port != base else 0)) & 0xFF

    def _port_in(self, _: Uc, port: int, size: int, __: object) -> int:
        if 0x00 <= port <= 0x01:
            return self._byte_from_word(self.inputs.in0, port, 0x00, size)
        if 0x02 <= port <= 0x03:
            return self._byte_from_word(self.inputs.in1, port, 0x02, size)
        if 0x04 <= port <= 0x05:
            return self._byte_from_word(self.inputs.dsw, port, 0x04, size)
        if 0x40 <= port <= 0x43:
            register = (port - 0x40) >> 1
            return self.pic.read(register)
        return 0xFFFF if size == 2 else 0xFF

    def _port_out(self, _: Uc, port: int, size: int, value: int, __: object) -> None:
        value &= 0xFFFF if size == 2 else 0xFF
        self.port_log.append((port, size, value))
        if port == 0x00:
            command = value & 0xFF
            self.sound_latch.append(command)
            if self.sound_command is not None:
                self.sound_command(command)
        elif port == 0x02:
            self.video.flip_screen = bool(value & 0x04)
            self.video.video_off = bool(value & 0x08)
        elif port == 0x04:
            self.buffered_sprite_ram = bytes(
                self.cpu.mem_read(SPRITE_RAM.start, SPRITE_RAM.stop - SPRITE_RAM.start))
            self.video.sprite_dma_count += 1
            self.inputs.in1 |= 0x0080
        elif 0x40 <= port <= 0x43:
            self.pic.write((port - 0x40) >> 1, value)
        elif port in (0x80, 0x82, 0x84, 0x86):
            layer = 0 if port < 0x84 else 1
            target = self.video.scroll_y if port in (0x80, 0x84) else self.video.scroll_x
            target[layer] = value & 0xFFFF
        elif port in (0x06, 0x07):
            self.video.raster_irq_position = (value & 0x1FF) - 128

    def memory(self, area: slice) -> bytes:
        return bytes(self.cpu.mem_read(area.start, area.stop - area.start))


def main() -> int:
    machine = RTypeM72Machine()
    pc = machine.run()
    state = "HLT" if machine.waiting_for_interrupt else "лимит"
    print(f"V30: {state}, PC={pc:05X}, портовых записей={len(machine.port_log)}, "
          f"команд звука={len(machine.sound_latch)}")
    if machine.port_log:
        print("Первые записи:", machine.port_log[:16])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
