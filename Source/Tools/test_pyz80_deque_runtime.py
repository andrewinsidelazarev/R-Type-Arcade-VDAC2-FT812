"""Очередь collections: исходные модули против C VM с GC на каждом шаге."""
import ast
from pathlib import Path
import sysconfig
import unittest

from test_pyz80_callable_runtime import TCC, PRELUDE, compile_run
from test_pyz80_import_runtime import import_check


LIBRARY = Path(sysconfig.get_path('stdlib')) / 'collections/__init__.py'


@unittest.skipUnless(TCC, 'нужен локальный C-компилятор')
class DequeRuntimeTests(unittest.TestCase):
    def check(self, source, **options):
        sources = {'app': source, 'collections': LIBRARY.read_text(encoding='utf-8')}
        libraries = {'collections': LIBRARY}
        if 'from __future__ import annotations' in source:
            path = LIBRARY.parent.parent / '__future__.py'
            sources['__future__'] = path.read_text(encoding='utf-8')
            libraries['__future__'] = path
        for banked in (False, True):
            with self.subTest(banked=banked):
                import_check(sources, library_paths=libraries,
                             skip_oracle_modules=('collections',), generators=True,
                             banked=banked, **options)

    def test_fifo_crosses_blocks(self):
        self.check('''from collections import deque
q=deque(range(97))
first=q.popleft()
q.append(97)
count=len(q)
total=0
for i in range(1,98):
    total += q.popleft() == i
empty=not q
q.append(123)
last=q.popleft()
''', max_slices=100000)

    def test_iteration_and_sequence_consumers(self):
        self.check('''from collections import deque
q=deque(range(37))
q.popleft()
q.popleft()
t=tuple(q)
l=list(q)
copied=deque(q)
first=t[0]
last=l[-1]
length=len(copied)
different=copied is not q
total=0
for x in q:
    total+=x
has=36 in q
absent=99 not in q
positive=any(q)
it=iter(q)
same=iter(it) is it
next_value=next(it)
numbered=tuple(enumerate(q,100))
index=numbered[-1][0]
value=numbered[-1][1]
''', max_slices=100000)

    def test_source_generator_constructor(self):
        self.check('''from collections import deque
events=[]
def source():
    for i in range(35):
        events.append(i)
        yield [i]
q=deque(source())
calls=len(events)
first=q.popleft()[0]
values=list(q)
last=values[-1][0]
''', max_slices=100000)

    def test_shallow_alias_cycles_and_retained_method(self):
        self.check('''from collections import deque
child=[1]
q=deque((child,child))
put=q.append
take=q.popleft
alias=q
child[0]=7
left=take()
right=take()
same=left is right
value=right[0]
put(q)
self_reference=take() is q
q=None
put(13)
value_after_owner_deleted=take()
empty=not alias
''')

    def test_clear_and_exhaustion(self):
        self.check('''from collections import deque
q=deque()
it=iter(q)
q.clear()
empty=next(it,99)
q.append(1)
q.clear()
q.append(7)
it=iter(q)
first=next(it)
end=next(it,77)
again=next(it,88)
q.clear()
size=len(q)
''')

    def test_mutation_invalidates_iterator_even_when_size_restored(self):
        for change in ('q.append(7)', 'q.popleft()', 'q.clear()', 'q.popleft();q.append(7)'):
            with self.subTest(change=change):
                self.check('from collections import deque\nq=deque(range(17))\nit=iter(q)\nfirst=next(it)\n' +
                           change + '\nnext(it)\n', expect_vm_error=True)

    def test_exhausted_iterator_still_detects_mutation(self):
        self.check('''from collections import deque
q=deque()
it=iter(q)
first=next(it,99)
q.append(7)
next(it,88)
''', expect_vm_error=True)

    def test_invalid_signatures_and_unimplemented_protocols(self):
        for expression in ('deque(None)', 'deque([1],2)', 'deque(iterable=[1])',
                           'q.popleft(0)', 'q.popleft(x=1)', 'q.append()', 'q.append(1,2)',
                           'q.clear(1)', 'q[0]', 'q[0:1]', 'reversed(q)', 'set(q)'):
            with self.subTest(expression=expression):
                self.check('from collections import deque\nq=deque([1])\n' + expression + '\n',
                           expect_vm_error=True, sequences=True)

    def test_empty_pop_errors(self):
        self.check('from collections import deque\nq=deque()\nq.popleft()\n', expect_vm_error=True)

    def test_type_identity_and_source_shadowing(self):
        self.check('''import collections
from collections import deque as Queue
q=Queue([1])
same=Queue is collections.deque
is_queue=isinstance(q,Queue)
is_object=isinstance(q,object)
is_not_list=not isinstance(q,list)
sub=issubclass(Queue,object)
def deque(items):
    return items[0]+10
local=deque([7])
collections.deque=deque
from collections import deque as changed
changed_value=changed([13])
old_type_still_valid=Queue([8]).popleft()
''', classes=True)

    def test_deque_is_not_a_global_builtin(self):
        self.check('import collections\nq=deque()\n', expect_vm_error=True, expected_external=1)

    def test_local_collections_module_is_never_specialized(self):
        for banked in (False, True):
            import_check({'app': 'from collections import deque\nvalue=deque([5])\n',
                          'collections': 'def deque(items):\n    return items[0]+17\n'},
                         generators=True, banked=banked)

    def test_none_getattr_default_and_hasattr(self):
        self.check('''x=getattr(None,'x_fraction',17)
y=getattr(None,'y_fraction',23)
absent=not hasattr(None,'object_slot')
fallback=[1]
same=getattr(None,'missing_attribute',fallback) is fallback
''')

    def test_existing_none_attribute_never_reports_absent(self):
        for name in ('__class__','__repr__','__bool__','__doc__'):
            with self.subTest(name=name):
                self.check('value=getattr(None,'+repr(name)+',123)\n', expect_vm_error=True)

    @staticmethod
    def pool_source():
        path=Path(__file__).resolve().parents[1]/'Python/rtype_port/enemies.py'
        text=path.read_text(encoding='utf-8-sig')
        names={'M72ObjectPool','STAGE1_CHECKPOINT_FREE_SLOTS','STAGE1_CHECKPOINT_SLOT_RESIDUE'}
        selected=[n for n in ast.parse(text).body if
                  isinstance(n,ast.ClassDef) and n.name in names or
                  isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in names for t in n.targets)]
        return 'from __future__ import annotations\nfrom collections import deque\n'+ast.unparse(ast.Module(body=selected,type_ignores=[]))

    def test_unchanged_object_pool_constructs_and_reuses_slots(self):
        source=self.pool_source()
        source+='''
class Owner:
    inherit_slot_fractions=True
    x_fraction=999
    y_fraction=-1
    object_slot=None
owner=Owner()
pool=M72ObjectPool(False)
first=pool.take()
pool.bind(owner,first)
owner.x_fraction=321
owner.y_fraction=-1
pool.release(first,owner)
released=owner.object_slot is None
for i in range(93):
    pool.take()
reused=pool.take()
pool.bind(owner,reused)
x_fraction=owner.x_fraction
y_fraction=owner.y_fraction
serial=owner.scheduler_serial
empty=pool.take() is None
pool.release(None)
pool.release(123)
pool.release(first)
pool.release(first)
one=len(pool.free)
pool=M72ObjectPool(True)
checkpoint_first=pool.take()
checkpoint_length=len(pool.free)
'''
        self.check(source, classes=True, sequences=True, heap_scale=4, max_args=128, max_slices=200000)

    def test_object_pool_every_state_matches_source(self):
        prefix=self.pool_source()+'''
class Owner:
    inherit_slot_fractions=True
    x_fraction=999
    y_fraction=-1
    object_slot=None
    scheduler_serial=0
'''
        driver='''
for checkpoint in (False,True):
    pool=M72ObjectPool(checkpoint)
    owner=Owner()
    slot=None
    capture()
    for round_number in range(2):
        for i in range(100):
            owner.inherit_slot_fractions=i%2==0
            slot=pool.take()
            if slot is not None:
                pool.bind(owner,slot)
            capture()
        for slot in pool.SLOTS:
            owner.x_fraction=slot+round_number
            owner.y_fraction=-slot-round_number
            pool.release(slot,owner)
            capture()
        for slot in pool.SLOTS:
            pool.release(slot)
            capture()
        pool.release(None)
        capture()
        pool.release(123)
        capture()
'''
        oracle={}
        exec(compile(prefix,'object-pool-source','exec',dont_inherit=True),oracle)
        expected=[]
        def scalar(value):
            return 0xffffffff if value is None else value & 0xffffffff
        def capture():
            pool,owner=oracle['pool'],oracle['owner']
            free=list(pool.free)
            expected.append([scalar(oracle['slot']),pool.serial,len(free),
                             scalar(owner.object_slot),owner.scheduler_serial,
                             scalar(owner.x_fraction),scalar(owner.y_fraction),int(owner.inherit_slot_fractions),
                             *free,*([0]*(96-len(free))),
                             *(int(slot in pool.allocated) for slot in pool.SLOTS),
                             *(value for slot in pool.SLOTS for value in pool.residue[slot])])
        oracle['capture']=capture
        exec(compile(driver,'object-pool-inputs','exec',dont_inherit=True),oracle)
        self.assertEqual(len(expected),1178)
        width=len(expected[0])
        table='static const uint32_t expected[]['+str(width)+']={'+','.join(
            '{'+','.join(str(v)+'UL' for v in row)+'}' for row in expected)+'};\nstatic unsigned checked_steps;'
        source=prefix+'''
step_ready=0
def capture():
    global step_ready
    step_ready+=1
'''+driver
        self.check(source,classes=True,sequences=True,heap_scale=4,max_args=128,max_slices=2000000,c_helpers=table,
                   after_slice='''
if(PyZ80Target_LoadField(&objects,&modules[0],@step_ready@,&value) && value.payload!=checked_steps) {
    unsigned n=(unsigned)value.payload,index,at;PyZ80VMValue pool,owner,free,block,key,residue,allocated;
    PyZ80TargetNode *node,*part;
    CHECK(n==checked_steps+1 && n<=1178);
    CHECK(PyZ80Target_LoadField(&objects,&modules[0],@slot@,&value));
    CHECK((value.kind==PYZ80_VM_VALUE_NONE ? 0xffffffffUL : value.payload)==expected[n-1][0]);
    CHECK(PyZ80Target_LoadField(&objects,&modules[0],@pool@,&pool));
    CHECK(PyZ80Target_LoadField(&objects,&pool,@serial@,&value) && value.payload==expected[n-1][1]);
    CHECK(PyZ80Target_LoadField(&objects,&pool,@free@,&free));
    node=PyZ80Target_Node(&objects,&free);CHECK(node && node->kind==PYZ80_TARGET_NODE_DEQUE && node->item_count==expected[n-1][2]);
    block=node->current;at=8;
    while(block.kind!=PYZ80_VM_VALUE_NONE) {
        part=PyZ80Target_Node(&objects,&block);CHECK(part && part->kind==PYZ80_TARGET_NODE_DEQUE_BLOCK);
        for(index=part->cursor;index<part->reserved;++index) {
            CHECK(at<8+expected[n-1][2]);
            CHECK(items[part->item_start+index].payload==expected[n-1][at++]);
        }
        block=part->current;
    }
    CHECK(at==8+expected[n-1][2]);
    CHECK(PyZ80Target_LoadField(&objects,&modules[0],@owner@,&owner));
    CHECK(PyZ80Target_FindAttribute(&objects,&owner,@object_slot@,&value)==1);
    CHECK((value.kind==PYZ80_VM_VALUE_NONE ? 0xffffffffUL : value.payload)==expected[n-1][3]);
    CHECK(PyZ80Target_FindAttribute(&objects,&owner,@scheduler_serial@,&value)==1 && value.payload==expected[n-1][4]);
    CHECK(PyZ80Target_FindAttribute(&objects,&owner,@x_fraction@,&value)==1 && value.payload==expected[n-1][5]);
    CHECK(PyZ80Target_FindAttribute(&objects,&owner,@y_fraction@,&value)==1 && value.payload==expected[n-1][6]);
    CHECK(PyZ80Target_FindAttribute(&objects,&owner,@inherit_slot_fractions@,&value)==1 && value.payload==expected[n-1][7]);
    CHECK(PyZ80Target_LoadField(&objects,&pool,@allocated@,&allocated));
    CHECK(PyZ80Target_LoadField(&objects,&pool,@residue@,&residue));
    { uint32_t size;CHECK(PyZ80Target_Length(&objects,&residue,&size) && size==96); }
    at=0;
    for(index=0;index<96;++index) {
        key=integer(0x540+64*index);
        CHECK(PyZ80Target_SetFind(&objects,&allocated,&key)==(expected[n-1][104+index] ? 1 : 2));
        at+=expected[n-1][104+index];
        CHECK(PyZ80Target_DictFind(&objects,&residue,&key,&value)==1);
        part=PyZ80Target_Node(&objects,&value);CHECK(part && part->kind==PYZ80_TARGET_NODE_TUPLE && part->item_count==2);
        CHECK(items[part->item_start].payload==expected[n-1][200+2*index]);
        CHECK(items[part->item_start+1].payload==expected[n-1][201+2*index]);
    }
    { uint32_t size;CHECK(PyZ80Target_Length(&objects,&allocated,&size) && size==at); }
    checked_steps=n;
}''',after='CHECK(checked_steps==1178);')

    def test_native_pop_never_shifts_items_and_capacity_failure_is_atomic(self):
        compile_run(PRELUDE+'''
#include "pyz80_target_deque.h"
int main(void) {
    PyZ80TargetContext o;PyZ80TargetNode nodes[8],*q,*head,*tail;PyZ80TargetField fields[2];
    PyZ80VMValue items[32],owner,v,out;unsigned i;uint16_t start,epoch;
    PyZ80Target_Init(&o,nodes,8,fields,2,items,32,0,0,0,0,0,0);
    CHECK(PyZ80Target_EmptyDeque(&o,&owner));q=PyZ80Target_Node(&o,&owner);
    for(i=0;i<32;++i) { v=integer(i);CHECK(PyZ80Target_DequeAppend(&o,&owner,&v)); }
    epoch=q->item_start;CHECK(!PyZ80Target_DequeAppend(&o,&owner,&v));
    CHECK(q->item_start==epoch && q->item_count==32 && o.item_used==32);
    head=PyZ80Target_Node(&o,&q->current);start=head->item_start;
    tail=&nodes[q->source_link-1];
    CHECK(PyZ80Target_DequePopleft(&o,&owner,&out) && out.payload==0);
    CHECK(head->item_start==start && head->cursor==1 && o.item_used==32);
    CHECK(items[start].kind==PYZ80_VM_VALUE_NONE);
    for(i=1;i<16;++i)CHECK(items[start+i].payload==i);
    for(i=0;i<16;++i)CHECK(items[tail->item_start+i].payload==i+16);
    q->item_start=q->cursor=65535;
    CHECK(!PyZ80Target_DequeAppend(&o,&owner,&v));
    CHECK(!PyZ80Target_DequePopleft(&o,&owner,&out));
    CHECK(!PyZ80Target_DequeClear(&o,&owner));
    CHECK(q->item_count==31 && head->cursor==1);
    return 0;
}
''')

    def test_sorted_and_extrema_consume_deque(self):
        self.check('''from collections import deque
q=deque([5,-3,7,1])
s=sorted(q)
low=s[0]
high=s[-1]
minimum=min(q)
maximum=max(q)
size=len(q)
''', sorting=True)

    def test_recycling_has_bounded_live_storage(self):
        self.check('''from collections import deque
q=deque(range(33))
matching=0
for i in range(2048):
    matching+=q.popleft()==i
    q.append(i+33)
left=q.popleft()
length=len(q)
''', max_slices=500000,after='CHECK(gc.live_items<96 && gc.live_nodes<32);')

    def test_gc_rejects_corrupt_blocks_before_using_them(self):
        for corruption in ('head->reserved=17;', 'head->item_start=objects.item_used;',
                           'head->current=q->current;', 'head->source_generation=0;'):
            with self.subTest(corruption=corruption):
                self.check('from collections import deque\nq=deque(range(33))\nphase=1\nx=q.popleft()\n',
                           expect_vm_error=True,c_helpers='static unsigned corrupted;',after_slice='''
if(!corrupted && PyZ80Target_LoadField(&objects,&modules[0],@phase@,&value) && value.payload==1) {
    PyZ80TargetNode *q,*head;
    CHECK(PyZ80Target_LoadField(&objects,&modules[0],@q@,&value));
    q=PyZ80Target_Node(&objects,&value);CHECK(q);
    head=PyZ80Target_Node(&objects,&q->current);CHECK(head);
'''+corruption+'''
    corrupted=1;
}''',after='CHECK(corrupted && vm.error==PYZ80_VM_E_HEAP_ROOTS);')


class CollectionsProviderTests(unittest.TestCase):
    def test_pinned_source_identity_and_changed_bytes(self):
        from pyz80_compiler.collections_provider import is_provider_source,bootstrap
        source=LIBRARY.read_text(encoding='utf-8')
        self.assertTrue(is_provider_source('collections',LIBRARY,source))
        self.assertFalse(is_provider_source('app',LIBRARY,source))
        self.assertFalse(is_provider_source('collections',Path('collections.py'),source))
        with self.assertRaisesRegex(ValueError,'source changed'):
            is_provider_source('collections',LIBRARY,source+'\n')
        self.assertEqual(ast.get_docstring(ast.parse(bootstrap(source)),clean=False),
                         ast.get_docstring(ast.parse(source),clean=False))

    def test_provider_contract_reports_partial_exports(self):
        from pyz80_compiler.collections_provider import CONTRACT,source_path
        from pyz80_compiler.module_imports import pinned_stdlib_sources
        self.assertEqual(CONTRACT['exports'],['deque','defaultdict'])
        self.assertIn('other collections exports',CONTRACT['pending'])
        self.assertEqual(pinned_stdlib_sources()['collections'],source_path())


if __name__ == '__main__':
    unittest.main()
