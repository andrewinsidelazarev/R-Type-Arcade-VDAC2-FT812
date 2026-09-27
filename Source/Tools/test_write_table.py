"""Проверки общей специализации без привязки к тайлам и игровым координатам."""
import unittest
import ctypes as ct

from pyz80_compiler.write_table import compile_write_table, emit_write_table, NotTableable


SOURCE = '''class Decoder:
    def apply(self, key:int, offset:int)->None:
        for i in range(4):
            value=struct.unpack_from('<H',self.rom,key+i*2)[0]
            struct.pack_into('>H',self.outputs[0],offset+i*4,value)
'''


def compile_example(source=SOURCE):
    return compile_write_table(source, 'Decoder', 'apply',
        immutable_fields={'rom': bytes(range(32))}, target_field='outputs',
        target_count=1, target_bytes=64, key_domains={'key': range(0, 32, 2)},
        placement='offset', placements=[0, 16, 32])


class WriteTableTests(unittest.TestCase):
    def test_full_domain_and_misses(self):
        table=compile_example()
        self.assertEqual(table.manifest['cached_keys'], 13)
        self.assertEqual(table.lookup[-3:], [65535]*3)
        self.assertEqual(table.records[:8], bytes([1,0,3,2,5,4,7,6]))
        self.assertEqual(table.placements[1], [[16,2],[20,2],[24,2],[28,2]])
        header,code=emit_write_table(table, 'Example')
        self.assertIn('pywt_arg0>30L', code)
        self.assertIn('record==65535u', code)
        self.assertIn('PyBufferSpan *scratch', header)

    def test_mutable_read_rejected(self):
        with self.assertRaisesRegex(NotTableable, 'изменяемое'):
            compile_example(SOURCE.replace('self.rom,key+i*2', 'self.outputs[0],key+i*2'))

    def test_repeated_write_rejected(self):
        with self.assertRaisesRegex(NotTableable, 'Повторная'):
            compile_example(SOURCE.replace('offset+i*4', 'offset'))

    def test_negative_offsets_and_size_contract(self):
        table=compile_example(SOURCE.replace('offset+i*4', 'offset+i*4-64'))
        self.assertEqual(table.placements[0], [[0,2],[4,2],[8,2],[12,2]])
        _,code=emit_write_table(table,'NegativeOffsets')
        self.assertIn('targets->size!=1u',code)
        self.assertIn('.size!=64UL',code)

    def test_placement_changes_data_rejected(self):
        with self.assertRaisesRegex(NotTableable, 'зависят от размещения'):
            compile_example(SOURCE.replace('i*4,value', 'i*4,value+offset'))

    def test_key_changes_layout_rejected(self):
        with self.assertRaisesRegex(NotTableable, 'Адреса зависят'):
            compile_example(SOURCE.replace('offset+i*4', 'offset+i*4+key'))

    def test_unbound_call_rejected(self):
        with self.assertRaises(ValueError):
            compile_example(SOURCE.replace('value=struct.unpack_from', 'value=unknown.unpack_from'))

    def test_c_dispatch_int32_edges(self):
        from build_stage_record import ROOT
        from build_translator_demo import command, write
        from check_tilemap_buffer import Transfer, View, Views
        from check_terrain_buffer import Span
        source=SOURCE.replace('key+i*2', 'i*2').replace('i*4,value', 'i*4+16,value^(key&65535)')
        table=compile_write_table(source, 'Decoder', 'apply',
            immutable_fields={'rom': bytes(range(32))}, target_field='outputs',
            target_count=1, target_bytes=64, key_domains={'key': [-2147483648,2147483647]},
            placement='offset', placements=[-16,0,16])
        header,code=emit_write_table(table,'Edges')
        build=ROOT/'Build/WriteTableTests'
        write(build/'edges.c', header+code)
        command(['E:/zx/tcc-0.9.27/tcc/tcc.exe','-shared','-DPY_BUFFER_API=__declspec(dllexport)',
                 '-I'+str(ROOT/'Source/C/python_vm'),build/'edges.c','-o',build/'edges.dll'])
        dll=ct.CDLL(str(build/'edges.dll'))
        fn=dll.Edges
        fn.argtypes=[ct.POINTER(View),ct.POINTER(Views),ct.POINTER(Span),
                     ct.c_int32,ct.c_int32,ct.POINTER(ct.c_uint8)]
        fn.restype=ct.c_uint8
        def transfer(context,position,data,size,writing):
            if writing: ct.memmove(context+position,data,size)
            else: ct.memmove(data,context+position,size)
            return 0
        callback=Transfer(transfer)
        raw=(ct.c_uint8*len(table.records)).from_buffer_copy(table.records)
        output=(ct.c_uint8*64)()
        scratch_data=(ct.c_uint8*8)()
        resource=View(len(raw),0,ct.addressof(raw),callback)
        views=(View*1)(View(64,1,ct.addressof(output),callback))
        targets=Views(views,1);scratch=Span(scratch_data,8,1);error=ct.c_uint8()
        for key_index,key in enumerate([-2147483648,2147483647]):
            for position_index,position in enumerate([-16,0,16]):
                ct.memset(output,0xa5,64)
                self.assertEqual(fn(ct.byref(resource),ct.byref(targets),ct.byref(scratch),key,position,ct.byref(error)),1)
                expected=bytearray([0xa5]*64)
                cursor=table.lookup[key_index]*table.manifest['record_stride']
                for address,size in table.placements[position_index]:
                    expected[address:address+size]=table.records[cursor:cursor+size]
                    cursor+=size
                self.assertEqual(bytes(output),expected)
        for key,position in [(0,0),(-2147483647,0),(2147483646,0),(2147483647,-17),(2147483647,1)]:
            before=bytes(output)
            self.assertEqual(fn(ct.byref(resource),ct.byref(targets),ct.byref(scratch),key,position,ct.byref(error)),0)
            self.assertEqual(bytes(output),before)
        for value in (63,65):
            views[0].size=value
            self.assertEqual(fn(ct.byref(resource),ct.byref(targets),ct.byref(scratch),2147483647,0,ct.byref(error)),0)
            self.assertEqual(bytes(output),before)


if __name__ == '__main__':
    unittest.main()
