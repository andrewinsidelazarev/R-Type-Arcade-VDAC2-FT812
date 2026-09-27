"""Общие конструкции агрегатного backend, не зависящие от имён игровой логики."""
import ctypes as ct
import unittest

from pyz80_compiler.aggregate_backend import compile_aggregate
from pyz80_compiler.frozen_constructor import freeze_constructor
from build_translator_demo import ROOT,write,command
from check_tilemap_buffer import Fault


SOURCE='''class Counter:
    def step(self, value:int)->None:
        values=(value,0)
        for index in range(2):
            if values[index]==0:
                continue
            self.add(index,values[index])
    def add(self, index:int, value:int)->None:
        self.data[index]=(self.data[index]+value)&65535
'''


class AggregateTests(unittest.TestCase):
    def test_c_arrays_calls_and_error(self):
        artifact=compile_aggregate(SOURCE,'Counter','CounterC',fields={'data':2},providers={})
        directory=ROOT/'Build/AggregateTests'
        write(directory/'counter.h',artifact.header)
        write(directory/'counter.c','#include "counter.h"\n'+artifact.code)
        command(['E:/zx/tcc-0.9.27/tcc/tcc.exe','-shared','-DPY_AGGREGATE_API=__declspec(dllexport)',
                 '-I'+str(ROOT/'Source/C/python_vm'),directory/'counter.c','-o',directory/'counter.dll'])
        class Counter(ct.Structure):
            _fields_=[('data',ct.c_int32*2)]
        dll=ct.CDLL(str(directory/'counter.dll'))
        for name,count in [('step',1),('add',2)]:
            fn=getattr(dll,'CounterC_'+name)
            fn.argtypes=[ct.POINTER(Fault),ct.POINTER(Counter),*[ct.c_int32]*count];fn.restype=ct.c_uint8
        value=Counter((ct.c_int32*2)(65534,9));fault=Fault()
        self.assertEqual(dll.CounterC_step(ct.byref(fault),ct.byref(value),3),1)
        self.assertEqual(list(value.data),[1,9])
        self.assertEqual(dll.CounterC_add(ct.byref(fault),ct.byref(value),-1,7),1)
        self.assertEqual(list(value.data),[1,16])
        self.assertEqual(dll.CounterC_add(ct.byref(fault),ct.byref(value),2,5),0)
        self.assertEqual(fault.error,6);self.assertEqual(list(value.data),[1,16])
        self.assertEqual(artifact.manifest['max_method_depth'],2)

    def test_recursive_call_rejected(self):
        with self.assertRaisesRegex(ValueError,'Рекурсия'):
            compile_aggregate(SOURCE.replace('self.data[index]=(self.data[index]+value)&65535','self.step(value)'),
                              'Counter','C',fields={'data':2},providers={})

    def test_uninitialised_after_continue_rejected(self):
        source='''class Counter:
    def step(self, value:int)->None:
        for index in range(2):
            if value:
                continue
            local=1
        self.data[0]=local
'''
        with self.assertRaisesRegex(ValueError,'присваивания'):
            compile_aggregate(source,'Counter','C',fields={'data':2},providers={})

    def test_tuple_mutation_rejected(self):
        with self.assertRaisesRegex(ValueError,'tuple'):
            compile_aggregate(SOURCE.replace('self.add(index,values[index])','values[index]=4'),
                              'Counter','C',fields={'data':2},providers={})

    def test_reserved_parameter_rejected(self):
        with self.assertRaisesRegex(ValueError,'Зарезервированное'):
            compile_aggregate(SOURCE.replace('value:int','record:int'),'Counter','C',fields={'data':2},providers={})

    def test_frozen_constructor_resource_changes(self):
        source='''class ResourceObject:
    def __init__(self)->None:
        self.rom=DATA.read_bytes()
        self.values=[1,2]
        self.outputs=[bytearray(4),bytearray(4)]
        value=struct.unpack_from('<H',self.rom,0)[0]
        struct.pack_into('>H',self.outputs[1],1,value)
'''
        fields={'rom':'bytes','values':2,'outputs':'list[bytearray]'}
        first,proof=freeze_constructor(source,'ResourceObject',resources={'DATA':b'\x01\x02'},fields=fields)
        second,_=freeze_constructor(source,'ResourceObject',resources={'DATA':b'\x03\x04'},fields=fields)
        self.assertEqual(first['outputs'][1],b'\0\x02\x01\0')
        self.assertNotEqual(first,second)
        self.assertFalse(proof['source_module_imported']);self.assertFalse(proof['runtime_io'])
        with self.assertRaisesRegex(ValueError,'вызов'):
            freeze_constructor(source.replace('DATA.read_bytes()','open("secret")'),
                               'ResourceObject',resources={},fields=fields)


if __name__=='__main__': unittest.main()
