"""Большие байтовые объекты, поля методов и ошибки провайдера памяти."""
import ctypes as ct
import struct
import unittest

from build_translator_demo import ROOT,write,command
from check_tilemap_buffer import View,Views,Transfer,Fault
from pyz80_compiler.buffer_backend import compile_buffer_function


class ViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path=ROOT/'Build/BufferViewTests'
        cls.formats=('<BbHh','>BbHh','!i2xHb','<i','>i')
        cls.functions=[];artifacts=[]
        for i,fmt in enumerate(cls.formats):
            count=len(struct.unpack(fmt,bytes(struct.calcsize(fmt))))
            names=', '.join('v'+str(j) for j in range(count))+(',' if count==1 else '')
            source=(f'def copy{i}(src:bytes,dst:bytearray,read:int,write:int)->None:\n'
                    f'    {names}=struct.unpack_from({fmt!r},src,read)\n'
                    f'    struct.pack_into({fmt!r},dst,write,'+','.join('v'+str(j) for j in range(count))+')\n')
            namespace={'struct':struct};exec(source,namespace)
            cls.functions.append(namespace['copy'+str(i)])
            artifacts.append(compile_buffer_function(source,'copy'+str(i),memory='view'))
        source="""class Store:
    def copy(self, layer:int, offset:int)->None:
        value=struct.unpack_from('<i',self.source,offset)[-1]
        struct.pack_into('>i',self.targets[layer],0,value)
"""
        artifacts.append(compile_buffer_function(source,'copy','method_copy',memory='view',owner='Store',
            fields={'self.source':'bytes','self.targets':'list[bytearray]'}))
        artifacts.append(compile_buffer_function('''def numeric(dst:bytearray,value:int)->None:
    bounded=min(500,max(-500,value))
    truth=int(bool(value))
    struct.pack_into('<ii',dst,0,bounded,truth)
''','numeric',memory='view'))
        write(cls.path/'views.c','\n'.join(a.header+a.code for a in artifacts))
        command(['E:/zx/tcc-0.9.27/tcc/tcc.exe','-shared','-DPY_BUFFER_API=__declspec(dllexport)',
                 '-I'+str(ROOT/'Source/C/python_vm'),cls.path/'views.c','-o',cls.path/'views.dll'])
        cls.dll=ct.CDLL(str(cls.path/'views.dll'))

    def buffer(self,raw,writable):
        data=(ct.c_uint8*len(raw)).from_buffer_copy(raw)
        def transfer(context,position,output,size,writing):
            if position+size>len(data): return 5
            if writing: ct.memmove(context+position,output,size)
            else: ct.memmove(output,context+position,size)
            return 0
        callback=Transfer(transfer)
        return data,callback,View(len(data),writable,ct.addressof(data),callback)

    def test_large_offsets_endian_negative_and_aliases(self):
        for i,fmt in enumerate(self.formats):
            fn=getattr(self.dll,'copy'+str(i));fn.restype=ct.c_uint8
            fn.argtypes=[ct.POINTER(Fault),ct.POINTER(View),ct.POINTER(View),ct.c_int32,ct.c_int32]
            for read in (0x3fff,0xffff,0x10000,0x7ffff,-16):
                initial=bytearray(bytes(range(256))*4096)
                size=struct.calcsize(fmt)
                for alias in (False,True):
                    expected=initial if alias else bytearray(len(initial))
                    write_at=(read%len(initial))+1
                    self.functions[i](initial,expected,read,write_at)
                    # Отдельная исходная копия, до эффектов Python на alias.
                    raw=bytes(range(256))*4096
                    data,callback,src=self.buffer(raw,0)
                    if alias:
                        target=data;target_callback=callback;dst=View(len(data),1,ct.addressof(data),callback)
                    else:
                        target,target_callback,dst=self.buffer(bytes(len(raw)),1)
                    fault=Fault()
                    self.assertEqual(fn(ct.byref(fault),ct.byref(src),ct.byref(dst),read,write_at),1)
                    self.assertEqual(bytes(target),expected,(fmt,read,alias,size))

    def test_method_index_readonly_and_backing_error(self):
        fn=self.dll.method_copy;fn.restype=ct.c_uint8
        fn.argtypes=[ct.POINTER(Fault),ct.POINTER(View),ct.POINTER(Views),ct.c_int32,ct.c_int32]
        data,callback,src=self.buffer(struct.pack('<i',-1234567),0)
        a,ca,first=self.buffer(bytes(4),1);b,cb,last=self.buffer(bytes(4),1)
        items=(View*2)(first,last);array=Views(items,2);fault=Fault()
        self.assertEqual(fn(ct.byref(fault),ct.byref(src),ct.byref(array),-1,0),1)
        self.assertEqual(bytes(a),bytes(4));self.assertEqual(bytes(b),struct.pack('>i',-1234567))
        for index in (-3,2):
            self.assertEqual(fn(ct.byref(fault),ct.byref(src),ct.byref(array),index,0),0)
            self.assertEqual(fault.error,6)
        items[1].writable=0
        self.assertEqual(fn(ct.byref(fault),ct.byref(src),ct.byref(array),1,0),0)
        self.assertEqual(fault.error,3)
        failing=Transfer(lambda *args:5);src.transfer=failing
        self.assertEqual(fn(ct.byref(fault),ct.byref(src),ct.byref(array),1,0),0)
        self.assertEqual((fault.error,fault.line),(5,3))

    def test_numeric_builtins_are_linked(self):
        fn=self.dll.numeric;fn.restype=ct.c_uint8
        fn.argtypes=[ct.POINTER(Fault),ct.POINTER(View),ct.c_int32]
        data,callback,view=self.buffer(bytes(8),1);fault=Fault()
        for value in (-2147483648,-501,-1,0,1,501,2147483647):
            self.assertEqual(fn(ct.byref(fault),ct.byref(view),value),1)
            self.assertEqual(bytes(data),struct.pack('<ii',min(500,max(-500,value)),int(bool(value))))

    def test_rebinding_receiver_is_rejected(self):
        source='class Store:\n    def move(self)->None:\n        self=0\n'
        with self.assertRaisesRegex(ValueError,'self'):
            compile_buffer_function(source,'move',owner='Store',memory='view')


if __name__=='__main__': unittest.main()
