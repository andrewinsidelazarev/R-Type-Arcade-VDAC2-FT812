"""Регрессии генератора демо: раскладка банков, ASR и точные границы строк."""
import ast
import ctypes
import random
import struct
import unittest

from build_translator_demo import ROOT, command, validate_layout, write
from pyz80_compiler.demo_projection import ScalarRecordEmitter
from pyz80_compiler.finite_expression import tabulate_i32
from check_translator_demo import StrictDemoMachine

TEST=ROOT/'Build/TranslatorDemoUnitTests'


class DemoTests(unittest.TestCase):
    def test_ordered_slots_match_python_list(self):
        source='''#include "pyz80_ordered_slots.h"
__declspec(dllexport) uint8_t append_slot(uint8_t *a,uint8_t *n,uint8_t cap,uint8_t slot) {
    return pyz80_slots_append(a,n,cap,slot);
}
__declspec(dllexport) uint8_t remove_slot(uint8_t *a,uint8_t *n,uint8_t slot) {
    return pyz80_slots_remove(a,n,slot);
}
'''
        write(TEST/'ordered_slots.c',source)
        command(['E:/zx/tcc-0.9.27/tcc/tcc.exe','-shared','-I'+str(ROOT/'Source/C/python_vm'),
                 TEST/'ordered_slots.c','-o',TEST/'ordered_slots.dll'])
        dll=ctypes.CDLL(str(TEST/'ordered_slots.dll'))
        pointer=ctypes.POINTER(ctypes.c_uint8)
        dll.append_slot.argtypes=[pointer,pointer,ctypes.c_uint8,ctypes.c_uint8]
        dll.remove_slot.argtypes=[pointer,pointer,ctypes.c_uint8]
        dll.append_slot.restype=dll.remove_slot.restype=ctypes.c_uint8
        rng=random.Random(812)
        for capacity in (1,3,22,255):
            order=(ctypes.c_uint8*capacity)(); length=ctypes.c_uint8()
            expected=[]
            for operation in range(1000):
                slot=rng.randrange(capacity)
                if rng.randrange(2):
                    accepted=slot not in expected and len(expected)<capacity
                    self.assertEqual(bool(dll.append_slot(order,ctypes.byref(length),capacity,slot)),accepted)
                    if accepted: expected.append(slot)
                else:
                    accepted=slot in expected
                    self.assertEqual(bool(dll.remove_slot(order,ctypes.byref(length),slot)),accepted)
                    if accepted: expected.remove(slot)
                self.assertEqual(list(order[:length.value]),expected)

    def test_finite_expression_full_domain(self):
        node=ast.parse('((shot.native_x - 328) * 5 * Q8) // 3',mode='eval').body
        data,proof=tabulate_i32(node,'shot.native_x',65536,{'Q8':256})
        self.assertEqual(proof['entries'],65536)
        self.assertEqual([x[0] for x in struct.iter_unpack('<i',data)],
                         [((x-328)*5*256)//3 for x in range(65536)])
        for text in ('other.x + value','danger(value)','value * 2147483648'):
            with self.assertRaises(ValueError):
                tabulate_i32(ast.parse(text,mode='eval').body,'value',3,{})

    def test_reject_section_overlap_and_stack(self):
        valid='_CODE 0000C000 00002F00 =\n_HOME 0000F000 00000305 =\n_DATA 00002200 00000500 ='
        self.assertEqual(validate_layout(valid)['_HOME']['end'],0xf305)
        for text in (valid.replace('00002F00','00003100'),
                     valid.replace('00000500','00001B00'),
                     valid+'\n_INITIALIZED 00002700 00000001 ='):
            with self.assertRaises(RuntimeError): validate_layout(text)

    def test_exact_line_budget_host_c(self):
        source='''#include <stdint.h>
uint8_t demo_fault;
#define DEMO_ENEMY_CAPACITY 22
#include "demo_line_budget.h"
__declspec(dllexport) uint16_t evaluate(const uint16_t *rows,const int16_t *changes,uint8_t count) {
    uint8_t i; line_reset(); demo_fault=0;
    for(i=0;i<count;++i) line_event(rows[i],changes[i]);
    return demo_fault ? 65535 : line_peak();
}
'''
        write(TEST/'line.c',source)
        command(['E:/zx/tcc-0.9.27/tcc/tcc.exe','-shared','-I'+str(ROOT/'Source/C/demo'),
                 TEST/'line.c','-o',TEST/'line.dll'])
        dll=ctypes.CDLL(str(TEST/'line.dll'))
        dll.evaluate.argtypes=[ctypes.POINTER(ctypes.c_uint16),ctypes.POINTER(ctypes.c_int16),ctypes.c_uint8]
        dll.evaluate.restype=ctypes.c_uint16
        rng=random.Random(812)
        for case in range(2000):
            intervals=[]
            for _ in range(rng.randrange(1,41)):
                first=rng.randrange(768); last=rng.randrange(first+1,769)
                intervals.append((first,last,rng.randrange(1,400)))
            if case==0: intervals=[(723,747,500),(747,768,900),(726,740,400)]
            delta=[0]*769; events=[]
            for first,last,cost in intervals:
                delta[first]+=cost; delta[last]-=cost
                events.extend(((first,cost),(last,-cost)))
            rng.shuffle(events)
            current=peak=0
            for change in delta:
                current+=change; peak=max(peak,current)
            rows=(ctypes.c_uint16*len(events))(*(e[0] for e in events))
            changes=(ctypes.c_int16*len(events))(*(e[1] for e in events))
            self.assertEqual(dll.evaluate(rows,changes,len(events)),peak,case)
        rows=(ctypes.c_uint16*1)(769); changes=(ctypes.c_int16*1)(1)
        self.assertEqual(dll.evaluate(rows,changes,1),65535)

    def test_floor_power_of_two_on_z80(self):
        emitter=ScalarRecordEmitter({'Q8':256})
        expr=emitter.expr(ast.parse('value // Q8',mode='eval').body)
        self.assertIn('>> 8',expr)
        self.assertEqual(emitter.expr(ast.parse('value // 3',mode='eval').body),'py_floor(value, 3L)')
        write(TEST/'shift.c','#include <stdint.h>\nvolatile int32_t value,result;\n'
              +'void shift(void) { result='+expr+'; }\n')
        command(['E:/zx/sdcc/bin/sdcc.exe','-mz80','--no-std-crt0','--code-loc','0xc000',
                 '--data-loc','0x2200','--sdcccall','1',TEST/'shift.c','-o',TEST/'shift.ihx'])
        m=StrictDemoMachine(ROOT)
        m.mem.pages[:]=[0,5,0x30,6]; m.reg.SP=0x3fff
        for line in (TEST/'shift.ihx').read_text().splitlines():
            data=bytes.fromhex(line[1:])
            if data[3]==0:
                m.mem.write_block_linear(int.from_bytes(data[1:3],'big'),data[4:4+data[0]])
        values={-2147483648,2147483647,0}
        for base in (-65536,-256,0,256,65536):
            values.update(range(base-260,base+261))
        for value in sorted(values):
            m.mem.write_block_linear(0x2200,struct.pack('<i',value))
            m.call(0xc000)
            actual=struct.unpack('<i',m.get_memory(0x2204,4))[0]
            self.assertEqual(actual,value//256,value)


if __name__=='__main__': unittest.main()
