"""Упакованные bytes/bytearray: исходный Python против пошагового C runtime."""
import ast
from pathlib import Path
import unittest

from test_pyz80_callable_runtime import TCC
from test_pyz80_import_runtime import import_check
from test_pyz80_callable_runtime import PRELUDE,compile_run
from pyz80_compiler.module_imports import pinned_stdlib_sources


@unittest.skipUnless(TCC,'нужен локальный C-компилятор')
class BufferRuntimeTests(unittest.TestCase):
    def check(self,source,**options):
        sources={'app':source};libraries={}
        if 'from __future__ import annotations' in source:
            libraries['__future__']=pinned_stdlib_sources()['__future__']
            sources['__future__']=libraries['__future__'].read_text(encoding='utf-8')
        for banked in (False,True):
            with self.subTest(banked=banked):
                import_check(sources,library_paths=libraries,generators=True,banked=banked,**options)

    def test_construction_index_assignment_and_iteration(self):
        self.check('''a=bytearray(4)
a[0]=0x98
a[-1]=7
b=bytes(a)
a[0]=3
original=b[0]
changed=a[0]
tail=b[-1]
size=len(b)
values=list(b)
first=values[0]
last=values[-1]
''')

    def test_slices_repeat_and_equal_length_slice_assignment(self):
        self.check('''a=bytearray(range(130))
b=bytes(a)
forward=b[61:69]
back=b[68:60:-1]
whole=b[:] is b
a[61:69]=back
at_boundary=a[64]
first=a[61]
last=a[68]
a[::-1]=a
after=a[0]
repeated=forward*3
left=(3*forward)[-1]
right=repeated[8]
length=len(repeated)
same=b*1 is b
empty=bytes() is b[:0]
different=bytearray() is not bytearray()
''',sequences=True,heap_scale=2,max_slices=30000)

    def test_comparison_order_and_integer_membership(self):
        self.check('''a=bytes((1,2,3))
b=bytearray((1,2,3))
c=bytes((1,2,4))
eq=a==b
ne=a!=c
lt=a<c
le=a<=b
gt=c>b
ge=b>=a
prefix=a[:2]<b
empty=bytes()<a
found=2 in a
absent=255 not in b
zero=0 in bytes()
''',sequences=True)

    def test_source_generator_and_consumer_identity(self):
        self.check('''events=[]
def source():
    for i in range(150):
        events.append(i)
        yield i
b=bytes(source())
copy=bytes(b)
same=copy is b
calls=len(events)
first=b[0]
last=b[-1]
back=tuple(reversed(b))
first_back=back[0]
numbered=list(enumerate(b,7))
index=numbered[-1][0]
value=numbered[-1][1]
''',heap_scale=3,max_slices=60000)

    def test_native_types(self):
        self.check('''a=bytes((3,4))
b=bytearray(a)
ba=isinstance(a,bytes)
bb=isinstance(b,bytearray)
not_ba=not isinstance(a,bytearray)
not_bb=not isinstance(b,bytes)
parent=issubclass(bytes,object)
not_child=not issubclass(bytes,bytearray)
''',classes=True)

    def test_staticmethod_binding_inheritance_and_direct_source_call(self):
        self.check('''def source(value=7):
    return value+3
wrapped=staticmethod(source)
direct=wrapped(11)
class Base:
    f=staticmethod(source)
    constant=staticmethod(17)
class Child(Base):
    def call_parent(self):
        return super().f(19)
c=Child()
plain=Child.f is source
instance=c.f is source
saved=c.f
through_class=Child.f(23)
through_instance=c.f()
through_super=c.call_parent()
constant=Child.constant
Base.f=staticmethod(lambda value:value+5)
new=c.f(3)
old=saved(3)
kind=isinstance(wrapped,staticmethod)
parent=issubclass(staticmethod,object)
''',classes=True)

    def test_generated_contract_keeps_unimplemented_protocols_visible(self):
        from generate_pzvt_target_adapters import container_protocol
        from pyz80_compiler.whole_program_vm_backend import RUNTIME_SOURCE_PATHS
        contract=container_protocol({})
        self.assertFalse(contract['dynamic_call_sites_proved'])
        self.assertIn('serialized bytes literals',contract['buffer_protocol']['pending'])
        self.assertIn('classmethod',contract['staticmethod_protocol']['pending'])
        self.assertIn('bytearray',contract['type_check_protocol']['native_types'])
        self.assertIn('Source/C/python_vm/pyz80_target_buffers.c',RUNTIME_SOURCE_PATHS)

    def test_iterator_sees_value_changes_and_retains_owner(self):
        self.check('''a=bytearray(range(130))
it=iter(a)
first=next(it)
a[1]=255
second=next(it)
it=iter(a)
a=None
values=tuple(it)
kept=values[1]
last=values[-1]
size=len(values)
''',heap_scale=2,max_slices=30000)

    def test_native_storage_is_packed_and_append_does_not_move_prefix(self):
        compile_run(PRELUDE+r'''
#include "pyz80_target_buffers.h"
#include "pyz80_target_gc.h"
int main(void) {
    PyZ80TargetContext o;PyZ80TargetNode nodes[32];PyZ80TargetField fields[1];PyZ80VMValue items[256],b,v,out,noise;
    PyZ80TargetNode *n,*head;unsigned i;uint16_t first_start;
    uint8_t marks[32];uint16_t queue[32],fm[1],im[256];
    PyZ80TargetGC gc={marks,queue,fm,im,32,1,256,0,0,0,0};
    PyZ80Target_Init(&o,nodes,32,fields,1,items,256,0,0,0,0,0,0);
    CHECK(PyZ80Target_EmptyList(&o,&noise));v=integer(999);
    CHECK(PyZ80Target_ListAppend(&o,&noise,&v));
    CHECK(PyZ80Target_EmptyBuffer(&o,&b));
    for(i=0;i<129;++i) { v=integer(i);CHECK(PyZ80Target_BufferAppend(&o,&b,&v)); }
    n=PyZ80Target_Node(&o,&b);head=PyZ80Target_Node(&o,&n->current);first_start=head->item_start;
    CHECK(o.item_used==1+3*PYZ80_BUFFER_BLOCK_SLOTS);
    CHECK(PyZ80Target_EmptyList(&o,&noise));v=integer(888);CHECK(PyZ80Target_ListAppend(&o,&noise,&v));
    for(i=129;i<200;++i) { v=integer(i);CHECK(PyZ80Target_BufferAppend(&o,&b,&v)); }
    CHECK(head->item_start==first_start);
    CHECK(PyZ80Target_Collect(&o,0,0,&b,1,&gc));
    CHECK(o.item_used==4*PYZ80_BUFFER_BLOCK_SLOTS);
    for(i=0;i<200;++i) { CHECK(PyZ80Target_BufferRead(&o,&b,i,&out));CHECK(out.payload==i); }
    return 0;
}
''',gc=True)

    def test_corrupted_block_owner_slice_and_cache_are_rejected(self):
        for damage in ('b->source_generation^=1u;', 'b->current=n->current;',
                       'b->item_start=objects.item_used;', 'b->field_head=7u;',
                       'n->field_head=n->source_link;n->class_symbol=n->source_generation;n->cursor=0;'):
            with self.subTest(damage=damage):
                self.check('a=bytearray(range(130))\nphase=1\nx=a[65]\n',expect_vm_error=True,
                    c_helpers='static unsigned damaged;',after_slice=r'''
if(!damaged && PyZ80Target_LoadField(&objects,&modules[$app$],@phase@,&value)) {
    PyZ80TargetNode *n,*b;
    CHECK(PyZ80Target_LoadField(&objects,&modules[$app$],@a@,&value));
    n=PyZ80Target_Node(&objects,&value);b=PyZ80Target_Node(&objects,&n->current);
    '''+damage+r'''
    damaged=1;
}
''',after='CHECK(damaged==1u);CHECK(vm.error==PYZ80_VM_E_HEAP_ROOTS);')

    def test_full_u16_length_all_octets_survive_gc_and_overflow_is_atomic(self):
        compile_run(PRELUDE+r'''
#include "pyz80_target_buffers.h"
#include "pyz80_target_gc.h"
int main(void) {
    static PyZ80TargetContext o;
    static PyZ80TargetNode nodes[1032];static PyZ80TargetField fields[1];
    static PyZ80VMValue items[8200];
    static uint8_t marks[1032];static uint16_t queue[1032],fm[1],im[8200];
    PyZ80TargetGC gc={marks,queue,fm,im,1032,1,8200,0,0,0,0};
    PyZ80VMValue b,v,out;uint32_t i;uint16_t count,index;
    PyZ80Target_Init(&o,nodes,1032,fields,1,items,8200,0,0,0,0,0,0);
    CHECK(!PyZ80Target_BufferTraceValid(&o,0));
    CHECK(PyZ80Target_EmptyBuffer(&o,&b));
    for(i=0;i<65535UL;++i) { v=integer(i&255u);CHECK(PyZ80Target_BufferAppend(&o,&b,&v)); }
    count=o.node_used;CHECK(o.item_used==8192u);
    CHECK(!PyZ80Target_BufferAppend(&o,&b,&v));
    CHECK(o.node_used==count && o.item_used==8192u);
    CHECK(PyZ80Target_Collect(&o,0,0,&b,1,&gc));
    CHECK(PyZ80Target_Node(&o,&b)->item_count==65535u);
    for(i=0;i<65535UL;++i) { CHECK(PyZ80Target_BufferRead(&o,&b,(uint16_t)i,&out));CHECK(out.payload==(i&255u)); }
    v=integer(-65535L);CHECK(PyZ80Target_BufferIndex(&o,&b,&v,&index));CHECK(!index);
    v=integer(-65536L);CHECK(!PyZ80Target_BufferIndex(&o,&b,&v,&index));
    CHECK(PyZ80Target_BufferFreeze(&o,&b));v=integer(7);
    CHECK(!PyZ80Target_BufferWrite(&o,&b,0,&v));
    CHECK(PyZ80Target_BufferRead(&o,&b,0,&out));CHECK(!out.payload);
    return 0;
}
''',gc=True)

    def test_slice_snapshot_allocation_failure_does_not_change_target(self):
        for banked in (False,True):
            import_check({'app':'import saved\nsaved.target[:]=bytes(range(130))\n',
                          'saved':'target=bytearray(130)\n'},banked=banked,generators=True,
                sequences=True,expect_vm_error=True,c_helpers='#include "pyz80_target_buffers.h"\nstatic unsigned limited;',after_slice=r'''
for(j=0;j<DEPTH;++j)if(!limited && sequence_frames[j].mode==4u && sequence_frames[j].produced==64u) {
    objects.item_capacity=objects.item_used;limited=1u;
}
''',after=r'''
CHECK(limited==1u);CHECK(vm.error!=PYZ80_VM_E_HEAP_ROOTS);
CHECK(PyZ80Target_LoadField(&objects,&modules[$saved$],@target@,&value));
CHECK(PyZ80Target_Length(&objects,&value,&step_count));CHECK(step_count==130u);
for(j=0;j<130u;++j) { PyZ80VMValue byte;CHECK(PyZ80Target_BufferRead(&objects,&value,j,&byte));CHECK(byte.payload==0u); }
for(j=0;j<DEPTH;++j)CHECK(!sequence_frames[j].mode);
for(j=0;j<DEPTH*2;++j)CHECK(sequence_roots[j].kind==PYZ80_VM_VALUE_NONE);
''')

    def test_constructor_failure_keeps_published_value_and_prefix_effects(self):
        for banked in (False,True):
            import_check({'app':'''import saved
def source():
    saved.events.append(1)
    yield 17
    saved.events.append(2)
    yield 256
saved.result=bytes(source())
''','saved':'events=[]\nresult=99\n'},banked=banked,generators=True,expect_vm_error=True,after=r'''
CHECK(PyZ80Target_LoadField(&objects,&modules[$saved$],@result@,&value));CHECK(value.payload==99u);
CHECK(PyZ80Target_LoadField(&objects,&modules[$saved$],@events@,&value));
CHECK(PyZ80Target_Length(&objects,&value,&step_count));CHECK(step_count==2u);
for(j=0;j<DEPTH;++j)CHECK(!generator_frames[j].state);
for(j=0;j<DEPTH*3;++j)CHECK(generator_roots[j].kind==PYZ80_VM_VALUE_NONE);
''')

    def test_unchanged_tsfm_decoder_uses_real_byte_buffers(self):
        from test_pyz80_defaultdict_runtime import DefaultDictTests
        checker=DefaultDictTests()
        source=checker.decoder_source()+'''data=bytes((0,2,0,46,0,1,40,2,3,1,1,39,17,0,1,0,39,19,255,0))
events,frames=decode_stream(data)
count=len(events)
first=events[0][0][0]
second=events[0][1][1]
joined=events[3][1][2]
'''
        checker.check(source,classes=True,sequences=True)

    def test_unchanged_tsfm_page_jump_with_packed_16kb_buffer(self):
        from test_pyz80_defaultdict_runtime import DefaultDictTests
        checker=DefaultDictTests()
        source=checker.decoder_source()+'''data=bytearray(PAGE_SIZE+7)
data[0]=PAGE_MARKER
data[PAGE_SIZE]=3
data[PAGE_SIZE+1]=1
data[PAGE_SIZE+2]=1
data[PAGE_SIZE+3]=40
data[PAGE_SIZE+4]=19
data[PAGE_SIZE+5]=END_MARKER
events,frames=decode_stream(bytes(data))
size=len(events)
chip=events[3][0][0]
register=events[3][0][1]
value=events[3][0][2]
'''
        checker.check(source,classes=True,sequences=True,heap_scale=10,budget=64,max_slices=3000)

    def test_invalid_values_and_unsupported_protocols_fail_closed(self):
        for expression in ('bytearray(-1)','bytes((256,))','bytes((-1,))','bytes(None)',
                           'bytes(source=[1])','a[0]=256','a[-9]=1','b[0]=1',
                           'a[:]=bytes((1,2,3))','a*=2','256 in b','bytes("hi")'):
            with self.subTest(expression=expression):
                self.check('a=bytearray((1,2))\nb=bytes(a)\n'+expression+'\n',
                           sequences=True,expect_vm_error=True)

    @staticmethod
    def score_source():
        path=Path(__file__).resolve().parents[1]/'Python/rtype_port/enemies.py'
        text=path.read_text(encoding='utf-8-sig');tree=ast.parse(text);lines=text.splitlines(keepends=True)
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='M72EnemyWorld')
        methods=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name in ('_add_packed_bcd','_packed_bcd_value')]
        constant=next(n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='SCORE_BCD_MAX' for t in n.targets))
        return ('from __future__ import annotations\n'+''.join(lines[constant.lineno-1:constant.end_lineno])+
                '\nclass M72EnemyWorld:\n'+''.join(''.join(lines[min([n.lineno]+[d.lineno for d in n.decorator_list])-1:n.end_lineno])+'\n' for n in methods))

    def test_unchanged_packed_bcd_arithmetic_and_saturation(self):
        source=self.score_source()+'''results=[]
for initial in ((0,0,0,0),(0x99,0x99,0x99,0),(0x99,0x99,0x99,9),(0x89,0x67,0x45,3)):
    for increment in ((1,0,0,0),(0x99,0,0,0),(0,0x10,0,0),(0x11,0x11,0x11,1)):
        value=bytearray(initial)
        M72EnemyWorld._add_packed_bcd(value,bytes(increment))
        results.append((bytes(value),M72EnemyWorld._packed_bcd_value(value)))
'''
        for case in range(16):
            for byte in range(4):source+=f'v_{case}_{byte}=results[{case}][0][{byte}]\n'
            source+=f'score_{case}=results[{case}][1]\n'
        self.check(source,classes=True,sequences=True,heap_scale=3,max_slices=100000)


if __name__=='__main__':
    unittest.main()
