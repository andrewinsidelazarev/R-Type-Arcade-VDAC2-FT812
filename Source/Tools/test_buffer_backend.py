"""Контракты буферного backend против CPython, включая опасные границы."""
import ctypes as ct
import random
import struct
import unittest

from build_translator_demo import ROOT,write,command
from check_terrain_buffer import Span,Fault
from pyz80_compiler.buffer_backend import compile_buffer_function


class BufferTests(unittest.TestCase):
    formats=('<BbHh','>BbHh','!i2xHb','<i','>i')

    @classmethod
    def setUpClass(cls):
        cls.build=ROOT/'Build/BufferTests';cls.sources=[];artifacts=[]
        for i,fmt in enumerate(cls.formats):
            count=len(struct.unpack(fmt,bytes(struct.calcsize(fmt))))
            names=', '.join('a'+str(j) for j in range(count))+(',' if count==1 else '')
            source=(f'def transfer{i}(src: bytes, dst: bytearray, read: int, write: int) -> None:\n'
                    f'    {names} = struct.unpack_from({fmt!r}, src, read)\n'
                    f'    struct.pack_into({fmt!r}, dst, write, '+', '.join('a'+str(j) for j in range(count))+')\n')
            cls.sources.append(source);artifacts.append(compile_buffer_function(source,'transfer'+str(i)))
        loop='''def loop(dst: bytearray) -> None:
    for index in range(3):
        struct.pack_into('<H', dst, index * 2, index)
        index = 7
    struct.pack_into('<H', dst, 6, index)
'''
        cls.loop_source=loop;artifacts.append(compile_buffer_function(loop,'loop'))
        cls.pack_source="def put(dst: bytearray, value: int, offset: int) -> None:\n    struct.pack_into('<h', dst, offset, value)\n"
        artifacts.append(compile_buffer_function(cls.pack_source,'put'))
        cls.copy_source='''def copy_loop(src: bytes, dst: bytearray, read: int, write: int) -> None:
    cursor = read
    for index in range(8):
        a, b = struct.unpack_from('<HH', src, cursor)
        struct.pack_into('<HH', dst, write + index * 4, a, b)
        cursor += 4
'''
        fast=compile_buffer_function(cls.copy_source,'copy_loop','copy_fast')
        slow=compile_buffer_function(cls.copy_source,'copy_loop','copy_slow',optimise=False)
        assert len(fast.manifest['copy_runs'])==1 and slow.manifest['copy_runs']==[]
        artifacts.extend((fast,slow))
        write(cls.build/'cases.c','\n'.join(a.header+a.code for a in artifacts))
        command(['E:/zx/tcc-0.9.27/tcc/tcc.exe','-shared','-DPY_BUFFER_API=__declspec(dllexport)',
                 '-I'+str(ROOT/'Source/C/python_vm'),cls.build/'cases.c','-o',cls.build/'cases.dll'])
        cls.dll=ct.CDLL(str(cls.build/'cases.dll'))

    def test_formats_offsets_sign_and_padding(self):
        rng=random.Random(72)
        for i,fmt in enumerate(self.formats):
            fn=getattr(self.dll,'transfer'+str(i));fn.restype=ct.c_uint8
            fn.argtypes=[ct.POINTER(Fault),ct.POINTER(Span),ct.POINTER(Span),ct.c_int32,ct.c_int32]
            for _ in range(100):
                data=rng.randbytes(64);target=bytearray(rng.randbytes(64));size=struct.calcsize(fmt)
                read=rng.randrange(65-size);write_at=rng.randrange(65-size)
                if rng.randrange(2): read-=64
                if rng.randrange(2): write_at-=64
                src=(ct.c_uint8*64).from_buffer_copy(data);dst=(ct.c_uint8*64).from_buffer_copy(target)
                a=Span(src,64,0);b=Span(dst,64,1);fault=Fault()
                struct.pack_into(fmt,target,write_at,*struct.unpack_from(fmt,data,read))
                self.assertEqual(fn(ct.byref(fault),ct.byref(a),ct.byref(b),read,write_at),1)
                self.assertEqual(bytes(dst),target)

    def test_for_variable_is_not_range_counter(self):
        data=(ct.c_uint8*8)();buffer=Span(data,8,1);fault=Fault()
        self.dll.loop.argtypes=[ct.POINTER(Fault),ct.POINTER(Span)]
        self.assertEqual(self.dll.loop(ct.byref(fault),ct.byref(buffer)),1)
        self.assertEqual(bytes(data),struct.pack('<4H',0,1,2,7))

    def test_integer_range_and_negative_offset(self):
        fn=self.dll.put;fn.restype=ct.c_uint8
        fn.argtypes=[ct.POINTER(Fault),ct.POINTER(Span),ct.c_int32,ct.c_int32]
        for value in (-32769,-32768,-1,0,32767,32768):
            data=(ct.c_uint8*4)(1,2,3,4);buffer=Span(data,4,1);fault=Fault()
            result=fn(ct.byref(fault),ct.byref(buffer),value,-2)
            if -32768<=value<=32767:
                self.assertEqual(result,1);self.assertEqual(bytes(data)[2:],struct.pack('<h',value))
            else: self.assertEqual((result,fault.error),(0,4))
        self.assertEqual(fn(ct.byref(fault),ct.byref(buffer),0,-5),0)
        self.assertEqual(fault.error,2)

    def test_reject_unsupported_semantics(self):
        for body in ("struct.pack_into('<H', src, 0, 1)",
                     "a, = struct.unpack_from('<I', src, 0)",
                     "a, = struct.unpack_from(fmt, src, 0)",
                     "a = unknown(1)","a = 1 or 2","while True:\n        pass"):
            source='def bad(src: bytes) -> None:\n    '+body+'\n'
            with self.assertRaises((ValueError,TypeError)): compile_buffer_function(source,'bad')

    def test_copy_fusion_preserves_partial_writes_and_aliasing(self):
        namespace={'struct':struct};exec(self.copy_source,namespace);source=namespace['copy_loop']
        rng=random.Random(654)
        for alias in (False,True):
            for _ in range(300):
                raw=bytearray(rng.randbytes(64));target=raw if alias else bytearray(rng.randbytes(64))
                read=rng.randrange(-70,71);write_at=rng.randrange(-70,71)
                reference_raw=bytearray(raw);reference_target=reference_raw if alias else bytearray(target)
                ok=True
                try: source(reference_raw,reference_target,read,write_at)
                except struct.error: ok=False
                for name in ('copy_fast','copy_slow'):
                    csrc=(ct.c_uint8*64).from_buffer_copy(raw)
                    cdst=csrc if alias else (ct.c_uint8*64).from_buffer_copy(target)
                    src=Span(csrc,64,0);dst=Span(cdst,64,1);fault=Fault()
                    fn=getattr(self.dll,name);fn.restype=ct.c_uint8
                    fn.argtypes=[ct.POINTER(Fault),ct.POINTER(Span),ct.POINTER(Span),ct.c_int32,ct.c_int32]
                    self.assertEqual(bool(fn(ct.byref(fault),ct.byref(src),ct.byref(dst),read,write_at)),ok)
                    self.assertEqual(bytes(cdst),reference_target,(name,alias,read,write_at))

    def test_uninitialised_local_is_rejected(self):
        source="def bad(dst:bytearray, condition:int)->None:\n    if condition:\n        x=1\n    struct.pack_into('<H', dst, 0, x)\n"
        with self.assertRaisesRegex(ValueError,'доказанного присваивания'): compile_buffer_function(source,'bad')

if __name__=='__main__': unittest.main()
