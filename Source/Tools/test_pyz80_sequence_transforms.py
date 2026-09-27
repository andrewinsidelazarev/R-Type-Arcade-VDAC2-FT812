"""Повторение и срезы исходных последовательностей в C VM, с CPython-оракулом."""
import ast
from pathlib import Path
import unittest

from test_pyz80_callable_runtime import PRELUDE,TCC,compile_run
from test_pyz80_import_runtime import import_check


@unittest.skipUnless(TCC,'нужен локальный C-компилятор')
class SequenceTransformTests(unittest.TestCase):
    def check(self,source,**options):
        for banked in (False,True):
            with self.subTest(banked=banked):
                import_check({'app':source},generators=True,sequences=True,banked=banked,**options)

    def test_repeat_list_and_tuple(self):
        self.check('''a=[7,8]*3
b=3*(9,10)
x=a[0]
y=a[-1]
z=b[3]
n=len(a)
m=len(b)
a[1]=11
changed=a[1]
unchanged=a[3]
''')

    def test_slice_list_and_tuple(self):
        self.check('''a=[0,1,2,3,4,5]
b=a[1:5:2]
c=(0,1,2,3,4,5)[::-1]
x=b[0]
y=b[1]
first=c[0]
last=c[-1]
different=a[:] is not a
''')

    def test_unchanged_resource_manager_constructs(self):
        path=Path(__file__).resolve().parents[1]/'Python/rtype_port/enemies.py'
        tree=ast.parse(path.read_text(encoding='utf-8-sig'))
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='M72ResourceManager')
        self.check(ast.unparse(cls)+'''
pool=M72ResourceManager(False)
slot=pool.acquire(3)
refs=pool.refs[slot]
pool.release(slot)
released=pool.refs[slot]
kind=pool.types[slot]
''',classes=True)

    def test_shallow_repetition_and_cycles(self):
        self.check('''child=[1]
a=[child]*4
child[0]=7
same=a[0] is a[3]
value=a[2][0]
cycle=[]
cycle.append(cycle)
copy=cycle*3
cycle_size=len(cycle)
copy_size=len(copy)
identity=copy[2] is cycle
cycle*=3
still_self=cycle[2] is cycle
''')

    def test_inplace_aliases_iterators_and_numeric_left_operand(self):
        self.check('''a=[1,2,3]
alias=a
it=iter(a)
reverse=reversed(a)
first=next(it)
a*=3
same=a is alias
n=len(alias)
second=next(it)
back=next(reverse)
alias[0]=7
not_deep=a[3]
left=2
left*=a
new=left is not a
left_size=len(left)
original_size=len(a)
empty=0
empty*=a
empty_size=len(empty)
unchanged_size=len(a)
''')

    def test_repeat_zero_negative_bool_and_extreme_counts(self):
        self.check('''a=[1,2]
alias=a
a*=True
identity=a is alias
a*=False
empty=len(alias)
a.append(7)
a*=-2147483648
empty_again=len(alias)
b=[]*2147483647
c=()*2147483647
d=[1]*-2147483648
e=[2]*False
f=True*[3]
lengths=len(b)+len(c)+len(d)+len(e)
value=f[0]
''')

    def test_tuple_noop_keeps_identity_list_noop_copies(self):
        self.check('''t=(1,2,3)
a=t*1 is t
b=1*t is t
c=t[:] is t
d=t[-99:99:1] is t
old=t
t*=1
e=t is old
l=[1,2]
f=l*1 is not l
g=l[:] is not l
''')

    def test_slice_boundaries_and_negative_step_against_full_oracle(self):
        # Полное декартово произведение включает None, явный -1 и MIN/MAX_I32.
        bounds=(None,-2147483648,-9,-1,0,1,5,9,2147483647)
        steps=(None,-2147483648,-3,-1,1,2,2147483647)
        cases=[(a,b,c) for a in bounds for b in bounds for c in steps]
        rows=[]
        for a,b,c in cases:
            part=list(range(6))[slice(a,b,c)]
            rows.append([len(part),*part,*([0]*(6-len(part)))])
        table='static const uint16_t expected[][7]={'+','.join(
            '{'+','.join(map(str,row))+'}' for row in rows)+'};\nstatic unsigned checked_cases;'
        source='a=[0,1,2,3,4,5]\ncase_ready=0\n'
        source+=f'bounds={bounds!r}\nsteps={steps!r}\n'
        source+='''for lower in bounds:
    for upper in bounds:
        for step in steps:
            result=a[lower:upper:step]
            case_ready+=1
'''
        self.check(source,max_slices=200000,heap_scale=4,c_helpers=table,after_slice='''
if(PyZ80Target_LoadField(&objects,&modules[0],@case_ready@,&value) && value.payload!=checked_cases) {
    unsigned n=(unsigned)value.payload,index;PyZ80TargetNode *node;
    CHECK(n==checked_cases+1 && n<=567);
    CHECK(PyZ80Target_LoadField(&objects,&modules[0],@result@,&value));
    node=PyZ80Target_Node(&objects,&value);CHECK(node && node->kind==PYZ80_TARGET_NODE_LIST);
    CHECK(node->item_count==expected[n-1][0]);
    for(index=0;index<node->item_count;++index)CHECK(items[node->item_start+index].payload==expected[n-1][index+1]);
    checked_cases=n;
}''',after='CHECK(checked_cases==567);')

    def test_slice_evaluates_source_lower_upper_step_once_in_order(self):
        self.check('''events=0
def source():
    global events
    events=events*10+1
    return [0,1,2,3,4]
def arg(mark,value):
    global events
    events=events*10+mark
    return value
copy=source()[arg(2,4):arg(3,None):arg(4,-2)]
x=copy[0]
y=copy[1]
z=copy[2]
''')

    def test_slice_of_empty_and_boolean_boundaries(self):
        self.check('''a=[][::-1]
b=()[::-2147483648]
c=[0,1,2][False:True:True]
d=[0,1,2][True:False:-1]
n=len(a)+len(b)
x=c[0]
y=d[0]
''')

    def test_repeated_transform_in_generators_defaults_and_sort_keys(self):
        self.check('''def values():
    yield [1,2]*2
    yield (3,4,5)[::-1]
def identity(value=[6]*3):
    return value
def key(value):
    return (value,value)[::-1][0]
a=list(values())
b=identity()
c=sorted([3,1,2],key=key)
x=a[0][-1]
y=a[1][0]
z=b[2]
first=c[0]
last=c[-1]
''',sorting=True)

    def test_invalid_calls_and_mutating_slices_fail_closed(self):
        for expression in ('[1]*1.5','[1]*None','[1]*[2]', '[1]*1024',
                           '[1,2][::0]','[1,2][::False]','[1,2]["a":]',
                           'range(5)[1:]','"abc"[1:]'):
            with self.subTest(expression=expression):
                self.check('a='+expression,expect_vm_error=True)
        for statement in ('a[1:]=[3]','del a[1:]'):
            self.check('a=[1,2]\n'+statement,expect_vm_error=True)

    def test_capacity_failure_preserves_inplace_list_and_cleans_roots(self):
        for banked in (False,True):
            # CPython получает небольшой допустимый вход. Только C-стенду
            # подаётся 2**30: проверяем защиту 4*N до переполнения uint32,
            # не заставляя host-оракул выделять несколько гигабайт памяти.
            import_check({'app':'import saved\nsaved.a*=saved.multiplier','saved':'a=[1,2,3,4]\nmultiplier=2'},
                generators=True,sequences=True,banked=banked,expect_vm_error=True,
                c_helpers='static unsigned changed;',after_slice='''
if(!changed && PyZ80Target_LoadField(&objects,&modules[$saved$],@multiplier@,&value)) {
    value.payload=1073741824UL;
    CHECK(PyZ80Target_StoreField(&objects,&modules[$saved$],@multiplier@,&value));changed=1;
}''',after='''CHECK(changed);
CHECK(PyZ80Target_LoadField(&objects,&modules[$saved$],@a@,&value));
{PyZ80TargetNode *node=PyZ80Target_Node(&objects,&value);
 CHECK(node && node->item_count==4);
 for(j=0;j<4;++j)CHECK(items[node->item_start+j].payload==j+1);}
for(j=0;j<DEPTH;++j)CHECK(!sequence_frames[j].mode);
for(j=0;j<2*DEPTH;++j)CHECK(sequence_roots[j].kind==PYZ80_VM_VALUE_NONE);''')

    def test_one_copy_per_step_and_atomic_inplace_publication(self):
        self.check('a=[1,2]\na*=48\nsize=len(a)',c_helpers='static unsigned previous_size;',after_slice='''
if(PyZ80Target_LoadField(&objects,&modules[0],@a@,&value)) {
    PyZ80TargetNode *node=PyZ80Target_Node(&objects,&value);
    CHECK(node && (node->item_count==2 || node->item_count==96));
}
for(j=0;j<DEPTH;++j)if(sequence_frames[j].mode) {
    CHECK(sequence_frames[j].produced>=previous_size && sequence_frames[j].produced<=previous_size+1);
    previous_size=sequence_frames[j].produced;
}''',after='CHECK(previous_size==96);')

    def test_inplace_noop_and_clear_need_no_result_buffer(self):
        for factor in (1,0,-2147483648):
            for banked in (False,True):
                import_check({'app':'import saved\nsaved.a*=saved.factor\nsize=len(saved.a)',
                              'saved':f'a=[1,2]\nfactor={factor}'},
                    generators=True,sequences=True,banked=banked,
                    c_helpers='static unsigned limited;',after_slice='''
if(!limited && states[$saved$]==PYZ80_MODULE_READY) {
    objects.item_capacity=objects.item_used;limited=1;
}''',after='CHECK(limited);')

    def test_gc_rejects_corrupt_slice_before_result_publication(self):
        for banked in (False,True):
            import_check({'app':'import saved\nsaved.result=saved.a[1:3]','saved':'a=[1,2,3]\nresult=99'},
                generators=True,sequences=True,banked=banked,expect_vm_error=True,
                c_helpers='static unsigned corrupted;',after_slice='''
if(!corrupted)for(j=0;j<objects.node_used;++j)if(nodes[j].kind==PYZ80_TARGET_NODE_SLICE) {
    nodes[j].item_count=2;corrupted=1;break;
}''',after='''CHECK(corrupted);
CHECK(PyZ80Target_LoadField(&objects,&modules[$saved$],@result@,&value));
CHECK(value.kind==PYZ80_VM_VALUE_I32 && value.payload==99);
for(j=0;j<DEPTH;++j)CHECK(!sequence_frames[j].mode);
for(j=0;j<2*DEPTH;++j)CHECK(sequence_roots[j].kind==PYZ80_VM_VALUE_NONE);''')

    def test_tail_append_never_moves_existing_items(self):
        compile_run(PRELUDE+'''
int main(void) {
    PyZ80TargetContext c;PyZ80TargetNode nodes[8];PyZ80TargetField fields[4];
    PyZ80VMValue items[128],list,value;PyZ80TargetNode *node;unsigned i;
    PyZ80Target_Init(&c,nodes,8,fields,4,items,128,0,0,0,0,0,0);
    CHECK(PyZ80Target_EmptyList(&c,&list));node=PyZ80Target_Node(&c,&list);
    for(i=0;i<128;++i) {
        value=integer(i);CHECK(PyZ80Target_ListAppend(&c,&list,&value));
        CHECK(node->item_start==0 && node->item_count==i+1 && c.item_used==i+1);
    }
    CHECK(!PyZ80Target_ListAppend(&c,&list,&value));
    for(i=0;i<128;++i)CHECK(items[i].payload==i);
    return 0;
}
''')

    def test_attach_rejects_overlap_and_insufficient_frame_count(self):
        self.check('answer=1',before_sequences='''
CHECK(!PyZ80Target_AttachSequences(&sequences,&scopes,sequence_frames,sequence_roots,0,sequence_routes));
CHECK(!PyZ80Target_AttachSequences(&sequences,&scopes,sequence_frames,(PyZ80VMValue *)sequence_frames,DEPTH,sequence_routes));
CHECK(!PyZ80Target_AttachSequences(&sequences,&scopes,sequence_frames,sequence_roots,DEPTH,(uint16_t *)generator_roots));
''')

    def test_unchanged_resource_manager_state_after_every_operation(self):
        path=Path(__file__).resolve().parents[1]/'Python/rtype_port/enemies.py'
        tree=ast.parse(path.read_text(encoding='utf-8-sig'))
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='M72ResourceManager')
        # Класс, включая __init__/acquire/release, целиком из активного исходника.
        prefix=ast.unparse(cls)+'''
def actions():
    for value in range(20):
        yield (0,value)
    for unused in range(260):
        yield (0,2)
    for unused in range(270):
        yield (1,2)
    for value in (-1,16,255):
        yield (1,value)
    for value in (0x101,0xFF,0x124):
        yield (0,value)
'''
        oracle={}
        exec(compile(prefix,str(path)+'#resource-manager-oracle','exec',dont_inherit=True),oracle)
        expected=[]
        for checkpoint in (False,True):
            pool=oracle['M72ResourceManager'](checkpoint)
            expected.append([256,*pool.types,*pool.refs])
            for command,operand in oracle['actions']():
                value=pool.acquire(operand) if command==0 else pool.release(operand)
                expected.append([256 if value is None else value,*pool.types,*pool.refs])
        table='static const uint16_t expected[][33]={'+','.join(
            '{'+','.join(map(str,row))+'}' for row in expected)+'};\nstatic unsigned checked_steps;'
        source=prefix+'''step_ready=0
for checkpoint in (False,True):
    pool=M72ResourceManager(checkpoint)
    result=None
    step_ready+=1
    for command,operand in actions():
        if command==0:
            result=pool.acquire(operand)
        else:
            result=pool.release(operand)
        step_ready+=1
'''
        self.check(source,classes=True,c_helpers=table,max_slices=1000000,after_slice='''
if(PyZ80Target_LoadField(&objects,&modules[0],@step_ready@,&value) && value.payload!=checked_steps) {
    unsigned n=(unsigned)value.payload,index;PyZ80VMValue pool;PyZ80TargetNode *node;
    CHECK(n==checked_steps+1 && n<=1114);
    CHECK(PyZ80Target_LoadField(&objects,&modules[0],@result@,&value));
    CHECK(expected[n-1][0]==256 ? value.kind==PYZ80_VM_VALUE_NONE :
        value.kind==PYZ80_VM_VALUE_I32 && value.payload==expected[n-1][0]);
    CHECK(PyZ80Target_LoadField(&objects,&modules[0],@pool@,&pool));
    CHECK(PyZ80Target_LoadField(&objects,&pool,@types@,&value));
    node=PyZ80Target_Node(&objects,&value);CHECK(node && node->item_count==16);
    for(index=0;index<16;++index)CHECK(items[node->item_start+index].payload==expected[n-1][1+index]);
    CHECK(PyZ80Target_LoadField(&objects,&pool,@refs@,&value));
    node=PyZ80Target_Node(&objects,&value);CHECK(node && node->item_count==16);
    for(index=0;index<16;++index)CHECK(items[node->item_start+index].payload==expected[n-1][17+index]);
    checked_steps=n;
}''',after=f'CHECK(checked_steps=={len(expected)});')


if __name__=='__main__':
    unittest.main()
