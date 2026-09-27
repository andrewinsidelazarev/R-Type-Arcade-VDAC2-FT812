"""Разбор инструкций V30 (x86-16 с расширениями NEC) в операции транслятора.

Разбор байтов делает capstone (x86-16); ADD4S NEC (`0F 20`) разбирается здесь. Операнды
приводятся к номерам регистров x86: 16-битные AX CX DX BX SP BP SI DI = 0..7, 8-битные
AL CL DL BL AH CH DH BH = 0..7, сегментные ES CS SS DS = 0..3. У памяти сегмент по
умолчанию SS для базы BP и DS иначе; смещение хранится по модулю 2^16.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from capstone import CS_ARCH_X86, CS_MODE_16, Cs
from capstone import x86_const as X

CODE_SEGMENT = 0x0040
CODE_BASE = CODE_SEGMENT << 4

REG16 = {'ax': 0, 'cx': 1, 'dx': 2, 'bx': 3, 'sp': 4, 'bp': 5, 'si': 6, 'di': 7}
REG8 = {'al': 0, 'cl': 1, 'dl': 2, 'bl': 3, 'ah': 4, 'ch': 5, 'dh': 6, 'bh': 7}
SREG = {'es': 0, 'cs': 1, 'ss': 2, 'ds': 3}
ES, CS, SS, DS = 0, 1, 2, 3
BP = 5

CONDITIONS = {
    'jo': 'o', 'jno': 'no', 'jb': 'b', 'jae': 'ae', 'je': 'e', 'jne': 'ne', 'jbe': 'be', 'ja': 'a',
    'js': 's', 'jns': 'ns', 'jp': 'p', 'jnp': 'np', 'jl': 'l', 'jge': 'ge', 'jle': 'le', 'jg': 'g',
}


class DecodeError(Exception):
    pass


@dataclass(frozen=True)
class Reg:
    index: int
    width: int


@dataclass(frozen=True)
class SReg:
    index: int


@dataclass(frozen=True)
class Mem:
    segment: int
    bases: tuple[int, ...]
    disp: int
    width: int
    override: bool = False


@dataclass(frozen=True)
class Imm:
    value: int
    width: int


@dataclass
class Instruction:
    address: int
    size: int
    mnemonic: str
    width: int = 0
    operands: list = field(default_factory=list)
    target: int | None = None
    condition: str | None = None
    rep: int = 0
    text: str = ''

    @property
    def ip(self) -> int:
        return (self.address - CODE_BASE) & 0xFFFF

    @property
    def next(self) -> int:
        return self.address + self.size


class Decoder:
    def __init__(self, memory: bytes) -> None:
        self.memory = memory
        self.md = Cs(CS_ARCH_X86, CS_MODE_16)
        self.md.detail = True
        self.cache: dict[int, Instruction] = {}

    def decode(self, address: int) -> Instruction:
        cached = self.cache.get(address)
        if cached is not None:
            return cached
        code = self.memory[address:address + 16]
        if code[:2] == b'\x0f\x20':
            result = Instruction(address, 2, 'add4s', text='add4s')
            self.cache[address] = result
            return result
        insn = next(self.md.disasm(code, (address - CODE_BASE) & 0xFFFF), None)
        if insn is None:
            raise DecodeError(f'не разобрано {address:05X}: {code[:6].hex()}')
        result = self._convert(address, insn)
        self.cache[address] = result
        return result

    def _operand(self, insn, op):
        if op.type == X.X86_OP_REG:
            name = insn.reg_name(op.reg)
            if name in REG16:
                return Reg(REG16[name], 2)
            if name in REG8:
                return Reg(REG8[name], 1)
            if name in SREG:
                return SReg(SREG[name])
            raise DecodeError(f'регистр {name}')
        if op.type == X.X86_OP_IMM:
            return Imm(op.imm & (0xFFFF if op.size == 2 else 0xFF if op.size == 1 else 0xFFFF), op.size)
        if op.type == X.X86_OP_MEM:
            memory = op.mem
            names = [insn.reg_name(reg) for reg in (memory.base, memory.index) if reg]
            if any(name not in REG16 for name in names) or (
                    memory.segment and insn.reg_name(memory.segment) not in SREG):
                raise DecodeError(f'адресация {insn.mnemonic} {insn.op_str}')
            bases = tuple(REG16[name] for name in names)
            if memory.segment:
                segment = SREG[insn.reg_name(memory.segment)]
                override = True
            else:
                segment = SS if bases and bases[0] == BP else DS
                override = False
            return Mem(segment, bases, memory.disp & 0xFFFF, op.size, override)
        raise DecodeError(f'тип операнда {op.type}')

    def _convert(self, address: int, insn) -> Instruction:
        opcode = insn.bytes[0]
        mnemonic = insn.mnemonic
        text = f'{mnemonic} {insn.op_str}'.strip()
        rep = insn.prefix[0]
        result = Instruction(address, insn.size, mnemonic, text=text, rep=rep)
        # Префиксы повторения у строковых команд: мнемоника без rep/repe/repne.
        for prefix in ('rep ', 'repe ', 'repne ', 'repz ', 'repnz '):
            if mnemonic.startswith(prefix):
                result.mnemonic = mnemonic[len(prefix):]
        base_opcode = next((byte for byte in insn.bytes if byte not in (0x26, 0x2E, 0x36, 0x3E, 0xF2, 0xF3)),
                           opcode)
        if base_opcode == 0x98:
            result.mnemonic = 'cbw'
        elif base_opcode == 0x99:
            result.mnemonic = 'cwd'
        elif mnemonic in ('pushaw', 'pusha'):
            result.mnemonic = 'pusha'
        elif mnemonic in ('popaw', 'popa'):
            result.mnemonic = 'popa'
        elif mnemonic in ('pushfw', 'pushf'):
            result.mnemonic = 'pushf'
        elif mnemonic in ('popfw', 'popf'):
            result.mnemonic = 'popf'
        result.operands = [self._operand(insn, op) for op in insn.operands]
        widths = [operand.width for operand in result.operands if isinstance(operand, (Reg, Mem))]
        result.width = widths[0] if widths else 0
        if result.mnemonic in CONDITIONS:
            result.condition = CONDITIONS[result.mnemonic]
            result.mnemonic = 'jcc'
        if result.mnemonic in ('jcc', 'jmp', 'call', 'loop', 'loope', 'loopne', 'jcxz') and result.operands:
            operand = result.operands[0]
            if isinstance(operand, Imm):
                result.target = CODE_BASE + (operand.value & 0xFFFF)
                result.operands = []
        if result.mnemonic in ('ljmp', 'lcall'):
            # Дальний переход в другой сегмент (в World ROM — только перезапуск `3F00:0800`):
            # переведённая программа останавливается с отказом по адресу.
            result.mnemonic = 'far'
            result.operands = []
        return result
