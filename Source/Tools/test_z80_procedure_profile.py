"""Профиль считает вложенные вызовы и хвостовые переходы без изменения числа тактов."""
import unittest

import v30z80  # noqa: F401
from p2c_z80_check import TSConfModel
from z80_procedure_profile import ProcedureProfile


class ProcedureProfileTest(unittest.TestCase):
    def run_program(self, tail=False, profile=True):
        model = TSConfModel({0: bytes(0x4000)})
        model.map_all([0, 1, 2, 3])
        cpu = model.cpu
        model.memory[0x100:0x109] = bytes.fromhex('CD0002 CD0003 C30004')
        outer = bytes.fromhex('010A00 C30003') if tail else bytes.fromhex('010A00 CD0003 0B C9')
        model.memory[0x200:0x200 + len(outer)] = outer
        model.memory[0x300:0x304] = bytes.fromhex('211400 C9')
        cpu.pc, cpu.sp = 0x100, 0x3FF0
        cpu.set_breakpoint(0x400)
        meter = ProcedureProfile(model, {(0, 0x200): 'outer', (0, 0x300): 'inner'}, [0x400]) if profile else None
        if meter:
            meter.enabled = True
            meter.refresh()
        ticks = 0
        while cpu.pc != 0x400:
            if meter:
                meter.observe()
            cpu.ticks_to_stop = 100000
            cpu.run()
            used = 100000 - int.from_bytes(bytes(cpu._StateBase__ticks_to_stop), 'little')
            ticks += used
            if meter:
                meter.clock += used
        if meter:
            meter.observe()
        self.assertEqual(cpu.sp, 0x3FF0)
        return ticks, meter.report() if meter else {}

    def test_nested(self):
        ticks, report = self.run_program()
        self.assertEqual(ticks, self.run_program(profile=False)[0])
        self.assertEqual(ticks, 127)
        self.assertEqual(report['outer'], dict(calls=1, ticks=63, maximum=63))
        self.assertEqual(report['inner'], dict(calls=2, ticks=40, maximum=20))

    def test_tail_call(self):
        ticks, report = self.run_program(tail=True)
        self.assertEqual(ticks, self.run_program(tail=True, profile=False)[0])
        self.assertEqual(report['outer'], dict(calls=1, ticks=40, maximum=40))
        self.assertEqual(report['inner'], dict(calls=2, ticks=40, maximum=20))


if __name__ == '__main__':
    unittest.main()
