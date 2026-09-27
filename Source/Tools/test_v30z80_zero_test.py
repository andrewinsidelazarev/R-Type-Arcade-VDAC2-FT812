"""Проверка коротких CMP/TEST: ограничения живости и все 65536 значений на ядре Z80."""
import re
import struct
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from v30z80.codegen import Fragment, Generator
from v30z80.decode import Imm, Instruction, Mem, Reg
from p2c_z80_check import TSConfModel


def generate(operation, value, condition='e', live=0, operand=None, external=False):
    instruction = Instruction(0x10000, 3, operation, 2, [operand or Reg(0, 2), Imm(value, 2)])
    jump = Instruction(0x10003, 2, 'jcc', target=0x10010, condition=condition)
    program = SimpleNamespace(labels={jump.address} if external else set(), entries=set(), constant_only=set(),
                              instructions={instruction.address: instruction, jump.address: jump})
    generator = Generator(program, {instruction.address: 63, jump.address: live}, {})
    fragment = Fragment(instruction)
    generator.binary(instruction, fragment, operation)
    return fragment.lines


class ZeroTestTests(unittest.TestCase):
    def test_templates(self):
        self.assertEqual(generate('cmp', 0), ['ld hl,(V_AX)', 'ld a,h', 'or l'])
        self.assertEqual(generate('cmp', 0xFFFF), ['ld hl,(V_AX)', 'ld a,h', 'and l', 'inc a'])
        self.assertEqual(generate('test', 0x80), ['ld a,(V_AX)', 'and #80'])
        self.assertEqual(generate('test', 0x8000), ['ld a,(V_AX+1)', 'and #80'])
        self.assertEqual(generate('test', 0), ['xor a'])
        self.assertEqual(generate('test', 0xFF00, 'ne'), ['ld a,(V_AX+1)', 'and #FF'])

    def test_live_flags_and_other_conditions_keep_general_path(self):
        for operation, value in (('cmp', 0), ('cmp', 0xFFFF), ('test', 0x8000)):
            for live in (1, 2, 4, 8, 16, 32, 63):
                self.assertNotEqual(generate(operation, value, live=live), generate(operation, value))
            for condition in ('b', 'ae', 's', 'ns', 'l', 'ge', 'o', 'no', 'p', 'np'):
                self.assertNotEqual(generate(operation, value, condition), generate(operation, value))
            self.assertNotEqual(generate(operation, value, external=True), generate(operation, value))
        self.assertIn('sbc hl,de', generate('cmp', 0x1234))
        self.assertIn('and d', generate('test', 0x0101))

    def test_memory_still_reads_whole_word(self):
        for operation, value in (('cmp', 0), ('cmp', 0xFFFF), ('test', 0), ('test', 0x80), ('test', 0x8000)):
            # Даже нулевая маска не убирает чтение и обработку границы страницы адаптером.
            with patch.object(Generator, 'read16', return_value=['call RW_DS']) as read:
                lines = generate(operation, value, operand=Mem(3, (), 0x3FFF, 2))
                read.assert_called_once()
                self.assertEqual(lines[0], 'call RW_DS')

    def test_all_word_values_on_z80(self):
        cases = [('cmp', 0), ('cmp', 0xFFFF)] + [('test', mask) for mask in (0, 1, 0x80, 0xFF, 0x100, 0x8000, 0xFF00)]
        lines = ['\tORG #C000', 'V_AX EQU #2000']
        for index, (operation, value) in enumerate(cases):
            lines += [f'CASE{index}:'] + ['\t' + line for line in generate(operation, value)] + ['\tjp #0100']
        folder = Path(__file__).resolve().parents[2] / 'Build' / 'V30Z80ZeroTest'
        folder.mkdir(parents=True, exist_ok=True)
        source, binary, symbols = (folder / name for name in ('test.asm', 'test.bin', 'test.sym'))
        source.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        result = subprocess.run(['E:/zx/z80/tsconf_project/exe/sjasmplus/sjasmplus.exe', '--nologo', '--msg=err',
                                 f'--raw={binary}', f'--sym={symbols}', str(source)], capture_output=True)
        self.assertEqual(result.returncode, 0, (result.stdout + result.stderr).decode('utf-8', 'replace'))
        code = binary.read_bytes()
        starts = {int(index): int(value, 16) for index, value in
                  re.findall(r'^CASE(\d+): EQU 0x([0-9A-Fa-f]+)', symbols.read_text(), re.M)}
        model = TSConfModel({page: bytes(0x4000) for page in range(4)})
        model.map_all([0, 1, 2, 3])
        model.memory[0xC000:0xC000 + len(code)] = code
        cpu = model.cpu
        cpu.set_breakpoint(0x0100)
        for index, (operation, operand) in enumerate(cases):
            for value in range(65536):
                model.memory[0x2000:0x2002] = struct.pack('<H', value)
                cpu.pc, cpu.af, cpu.hl, cpu.de = starts[index], 0xA5FF, 0x1234, 0x5678
                for _ in range(3):
                    cpu.ticks_to_stop = 1000
                    cpu.run()
                    if cpu.pc == 0x0100:
                        break
                if cpu.pc != 0x0100:
                    self.fail(f'Случай {index}: PC={cpu.pc:04X}')
                expected = value == operand if operation == 'cmp' else (value & operand) == 0
                if bool(cpu.f & 0x40) != expected or model.word(0x2000) != value:
                    self.fail(f'{operation} {operand:04X}, значение {value:04X}: F={cpu.f:02X}')


if __name__ == '__main__':
    unittest.main()
