"""Копирование list и обратный обход: CPython против C VM с GC после каждого шага."""
import ast
from pathlib import Path
import textwrap
import unittest

from test_pyz80_callable_runtime import TCC
from test_pyz80_import_runtime import import_check


@unittest.skipUnless(TCC, 'нужен локальный C-компилятор')
class SequenceConstructorTests(unittest.TestCase):
    def check(self, source, **options):
        for banked in (False, True):
            with self.subTest(banked=banked):
                import_check({'app': source}, generators=True, banked=banked, **options)

    def test_list_is_a_new_shallow_mutable_copy(self):
        self.check('''child=[7]
original=[child,3]
copy=list(original)
different=copy is not original
shared=copy[0] is child
copy[1]=9
child[0]=8
unchanged=original[1]
changed=copy[0][0]
copy.append(10)
original_size=len(original)
copy_size=len(copy)
empty=list()
empty.append(4)
empty_value=empty[0]
a=list(())
b=list(())
empty_identity=a is not b
''')

    def test_reverse_sequence_and_iterator_identity(self):
        self.check('''a=[1,2,3]
it=reversed(a)
same=iter(it) is it
first=next(it)
a[1]=8
a.append(9)
second=next(it)
third=next(it)
end=next(it,99)
a.append(10)
still_end=next(it,98)
t=tuple(reversed((4,5,6)))
x=t[0]
y=t[1]
z=t[2]
''')

    def test_list_sources_and_consumed_iterator_position(self):
        self.check('''a=list((4,5))
it=iter([6,7,8])
skipped=next(it)
b=list(it)
end=next(it,99)
c=list(range(5,-2,-2))
d=list({9:90,10:100})
e=list({9:90,10:100}.values())
f=list({9:90,10:100}.items())
g=list(enumerate((11,12),-3))
answer=a[0]+a[1]+b[0]+b[1]+c[0]+c[-1]+d[1]+e[0]+f[1][1]+g[0][0]+g[1][1]
sizes=len(a)+len(b)+len(c)+len(d)+len(e)+len(f)+len(g)
''')

    def test_list_nested_generators_retains_items_and_clears_continuations(self):
        self.check('''source=[1,2]
events=0
def inner():
    yield [7]
    yield [8]
def outer():
    global events
    yield source
    events=events*10+1
    source[0]=9
    yield list(inner())
    events=events*10+2
    yield list(x+1 for x in range(6))
g=outer()
a=list(g)
same=a[0] is source
x=a[0][0]
y=a[1][1][0]
z=a[2][-1]
end=next(g,99)
''', after='''for(j=0;j<DEPTH;++j)CHECK(!generator_frames[j].state);
for(j=0;j<DEPTH*3;++j)CHECK(generator_roots[j].kind==PYZ80_VM_VALUE_NONE);''')

    def test_list_cycles_are_shallow(self):
        self.check('''a=[]
a.append(a)
b=list(a)
different=b is not a
still_original=b[0] is a
a.append(b)
b_size=len(b)
nested=b[0][1] is b
''')

    def test_reverse_shrink_clear_growth_and_sticky_exhaustion(self):
        self.check('''a=[1,2,3,4]
it=reversed(a)
first=next(it)
removed=a.pop()
second=next(it)
del a[0]
third=next(it)
a.clear()
end=next(it,99)
a.extend([7,8,9,10])
still_end=next(it,98)
b=[1,2,3]
too_short=reversed(b)
b.pop()
short_end=next(too_short,97)
b.append(4)
short_stays_end=next(too_short,96)
empty=[]
empty_it=reversed(empty)
empty.append(8)
empty_end=next(empty_it,95)
last_it=reversed([5])
last=next(last_it)
last_end=next(last_it,94)
''')

    def test_reversed_ranges_crossing_int32_boundaries(self):
        self.check('''a=list(reversed(range(5,-3,-2)))
b=list(reversed(range(-7,8,3)))
c=list(reversed(range(-2147483648,2147483647,2147483647)))
d=list(reversed(range(2147483647,-2147483648,-2147483648)))
e=list(reversed(range(0)))
x0=a[0]
x1=a[1]
x2=a[2]
x3=a[3]
y0=b[0]
y4=b[4]
z0=c[0]
z1=c[1]
z2=c[2]
w0=d[0]
w1=d[1]
empty=len(e)
''')

    def test_reversed_range_max_extent_allocates_no_item_vector(self):
        self.check('''r=range(65535)
it=reversed(r)
first=next(it)
second=next(it)
''', after='''{
    uint16_t used=objects.item_used;
    CHECK(PyZ80Target_LoadField(&objects,&modules[0],@r@,&value));
    CHECK(PyZ80Target_Reversed(&objects,&value,&result));
    CHECK(objects.item_used==used);
    CHECK(PyZ80Target_Node(&objects,&result)->cursor==65535u);
}''')

    def test_reversed_loop_does_not_require_generator_storage(self):
        for banked in (False,True):
            import_check({'app': 'answer=0\nfor x in reversed([1,2,3]):\n    answer=answer*10+x'},
                         banked=banked)

    def test_bad_reverse_metadata_is_rejected_before_collection_mutates_heap(self):
        self.check('a=[1,2]\nit=reversed(a)',after='''{
    PyZ80TargetNode *node,saved,snapshot[HEAP_NODES];
    CHECK(PyZ80Target_LoadField(&objects,&modules[0],@it@,&value));
    node=PyZ80Target_Node(&objects,&value);CHECK(node);saved=*node;
    for(j=0;j<4;++j) {
        *node=saved;
        if(j==0)node->item_start=0x0180u;
        if(j==1)node->item_start=PYZ80_TARGET_ITER_REVERSE|1u;
        if(j==2)node->cursor=3u;
        if(j==3)node->reserved=2u;
        memcpy(snapshot,nodes,sizeof(nodes));
        CHECK(!PyZ80Target_IterNext(&objects,&value,&result));
        CHECK(!PyZ80Target_Collect(&objects,&vm,&scopes,modules,MODULES,&gc));
        CHECK(!memcmp(snapshot,nodes,sizeof(nodes)));
    }
    *node=saved;
    CHECK(PyZ80Target_Collect(&objects,&vm,&scopes,modules,MODULES,&gc));
}''')

    def test_reversed_dictionary_views_are_live_and_ordered(self):
        self.check('''d={1:10,2:20,3:30}
keys=reversed(d)
values=reversed(d.values())
pairs=reversed(d.items())
d[3]=31
k=next(keys)
v=next(values)
p=next(pairs)
pk=p[0]
pv=p[1]
d[2]=21
v2=next(values)
p2=next(pairs)[1]
tail=list(keys)
tk=tail[0]
te=tail[1]
names={"a":4,"b":5,"c":6}
name_keys=list(reversed(names.keys()))
name_values=list(reversed(names.values()))
name_pairs=list(reversed(names.items()))
first_name=name_keys[0]
last_name=name_keys[2]
first_value=name_values[0]
last_value=name_values[2]
pair_name=name_pairs[1][0]
pair_value=name_pairs[1][1]
''')

    def test_reversed_dict_key_mutation_is_not_silently_wrong(self):
        for mutation in ('d[3]=30', 'del d[1]', 'del d[1]\nd[3]=30'):
            with self.subTest(mutation=mutation):
                self.check('d={1:10,2:20}\nit=reversed(d)\nfirst=next(it)\n'+mutation+
                           '\nsecond=next(it)', expect_vm_error=True)
        self.check('''d={1:10}
it=reversed(d)
first=next(it)
end=next(it,99)
d[2]=20
still_end=next(it,98)
''')

    def test_reverse_retains_owner_through_gc_and_composes_with_consumers(self):
        self.check('''a=[[1],[2],[3]]
it=reversed(a)
a=None
first=next(it)[0]
tail=list(it)
second=tail[0][0]
third=tail[1][0]
pairs=list(enumerate(reversed((5,6,7)),-2))
index=pairs[0][0]
value=pairs[0][1]
last=pairs[2][1]
out=[]
out.extend(reversed((8,9)))
extended=out[0]
selected=max(reversed((2,7,4)))
ordered=sorted(reversed((3,1,2)))
smallest=ordered[0]
largest=ordered[-1]
''', sorting=True)

    def test_rebinding_builtins_is_respected(self):
        self.check('''make=list
backwards=reversed
def list(value):
    return value+7
def reversed(value):
    return value+9
a=list(3)
b=reversed(4)
c=make(backwards((5,6)))
first=c[0]
last=c[1]
''')

    def test_source_class_same_names_are_not_native_calls(self):
        self.check('''class Source:
    def list(self,value):
        return value+2
    def reversed(self,value):
        return value+3
s=Source()
a=s.list(5)
b=s.reversed(7)
copy=list([s])
same=copy[0] is s
is_list=isinstance(copy,list)
is_tuple=isinstance(copy,tuple)
''', classes=True)

    def test_invalid_or_unsupported_calls_never_use_external_fallback(self):
        for call in ('list([],[])', 'list(iterable=[])', 'list(None)', 'list(7)', 'list("ab")',
                     'list({1,2})', 'reversed()', 'reversed([],[])', 'reversed(sequence=[])',
                     'reversed(iter([]))', 'reversed(enumerate([]))', 'reversed(x for x in [])',
                     'reversed(None)', 'reversed("ab")', 'reversed({1,2})'):
            with self.subTest(call=call):
                self.check('a='+call, expect_vm_error=True)

    def test_list_advances_and_copies_one_element_per_vm_step(self):
        self.check('it=iter(range(96))\na=list(it)\nsize=len(a)',
            c_helpers='static unsigned previous_cursor;', after_slice='''
if(PyZ80Target_LoadField(&objects,&modules[0],@it@,&value)) {
    PyZ80TargetNode *node=PyZ80Target_Node(&objects,&value);
    CHECK(node && node->kind==PYZ80_TARGET_NODE_ITERATOR);
    CHECK(node->cursor>=previous_cursor && node->cursor<=previous_cursor+1);
    previous_cursor=node->cursor;
}
for(j=0;j<DEPTH;++j)if(generator_frames[j].state) {
    PyZ80TargetNode *node=PyZ80Target_Node(&objects,&generator_roots[j*3+1]);
    CHECK(node && node->kind==PYZ80_TARGET_NODE_LIST && node->item_count==previous_cursor);
}''', after='CHECK(previous_cursor==96);')

    def test_generator_failure_does_not_publish_partial_list(self):
        for banked in (False, True):
            import_check({'app': '''import saved
def values():
    saved.events.append(1)
    yield [7]
    saved.events.append(2)
    yield {}["missing"]
saved.result=list(values())
''', 'saved': 'result=99\nevents=[]'}, generators=True, banked=banked,
                expect_vm_error=True, after='''
CHECK(PyZ80Target_LoadField(&objects,&modules[$saved$],@result@,&value));
CHECK(value.kind==PYZ80_VM_VALUE_I32 && value.payload==99);
CHECK(PyZ80Target_LoadField(&objects,&modules[$saved$],@events@,&value));
{ PyZ80TargetNode *node=PyZ80Target_Node(&objects,&value);
  CHECK(node && node->item_count==2);
  CHECK(items[node->item_start].payload==1 && items[node->item_start+1].payload==2); }
for(j=0;j<DEPTH;++j)CHECK(!generator_frames[j].state);
for(j=0;j<DEPTH*3;++j)CHECK(generator_roots[j].kind==PYZ80_VM_VALUE_NONE);''')

    def test_unchanged_score_reveal_method(self):
        path=Path(__file__).resolve().parents[1]/'Python/rtype_port/enemies.py'
        tree=ast.parse(path.read_text(encoding='utf-8-sig'))
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='StageTransitionF1BF')
        method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='_begin_score_reveal')
        # Метод целиком взят из исходника. Оболочки классов — только тестовые входы.
        source='class Reveal:\n'+textwrap.indent(ast.unparse(method),'    ')+'\nclass World: pass\n'
        source+='r=Reveal()\nw=World()\nresults=[]\n'
        source+='''for score in ((0,0,0,0),(1,0,0,0),(0,0,0,1),(0x78,0x56,0x34,0x12)):
    w.stage_score_bcd=score
    r._begin_score_reveal(w)
    results.append((r.result_digits,r.display_digits))
timer=r.timer
state=r.state
'''
        # Проверяем каждый разряд, не только контрольную сумму или последний вызов.
        for case in range(4):
            source+=f'distinct_{case}=results[{case}][0] is not results[{case}][1]\n'
            for field in range(2):
                for digit in range(8):
                    source+=f'digit_{case}_{field}_{digit}=results[{case}][{field}][{digit}]\n'
        self.check(source, classes=True, max_slices=40000)

    def test_unchanged_latest_shot_selection(self):
        path=Path(__file__).resolve().parents[1]/'Python/rtype_port/game.py'
        tree=ast.parse(path.read_text(encoding='utf-8-sig'))
        assign=next(n for n in ast.walk(tree) if isinstance(n,ast.Assign) and
                    any(isinstance(t,ast.Name) and t.id=='latest_shot' for t in n.targets))
        source='class Game:\n    def select(self,queued_shot):\n'+textwrap.indent(ast.unparse(assign),'        ')
        source+='\n        return latest_shot\n'
        source+='''class Shot:
    def __init__(self,state):
        self.state=state
g=Game()
first=Shot("flight")
second=Shot("spent")
third=Shot("other")
g.shots=[first,second,third]
a=g.select(None) is second
b=g.select(first) is first
second.state="other"
c=g.select(None) is first
first.state="other"
d=g.select(None) is None
g.shots=[]
e=g.select(None) is None
'''
        self.check(source, classes=True)

    def test_score_reveal_state_matches_python_after_each_of_224_updates(self):
        path=Path(__file__).resolve().parents[1]/'Python/rtype_port/enemies.py'
        tree=ast.parse(path.read_text(encoding='utf-8-sig'))
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='StageTransitionF1BF')
        rng=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='M72Rng')
        wrap=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_u16')
        # Оба метода анимации, арифметическая обёртка и reset/next RNG — исходные AST.
        # Конструкторы/полный world сюда не входят; входное окружение задаёт стенд.
        prefix=ast.unparse(wrap)+'\nclass Reveal:\n'
        for method in cls.body:
            if isinstance(method,ast.FunctionDef) and method.name in ('_begin_score_reveal','_update_score_reveal'):
                prefix+=textwrap.indent(ast.unparse(method),'    ')+'\n'
        prefix+='class M72Rng:\n'
        for method in rng.body:
            if isinstance(method,ast.FunctionDef) and method.name in ('reset','next'):
                prefix+=textwrap.indent(ast.unparse(method),'    ')+'\n'
        prefix+='''class World: pass
r=Reveal()
w=World()
w.stage_score_bcd=(0x78,0x56,0x34,0)
w.rng=M72Rng()
w.rng.reset()
w.sound_commands=[]
r._begin_score_reveal(w)
'''
        oracle={}
        exec(compile(prefix,str(path)+'#score-reveal-oracle','exec',dont_inherit=True),oracle)
        expected=[]
        for tick in range(1,225):
            world=oracle['w']; reveal=oracle['r']
            world.frame_counter=tick
            reveal._update_score_reveal(world)
            expected.append([reveal.timer,*reveal.result_digits,*reveal.display_digits,
                             len(world.sound_commands),world.rng.a,world.rng.b,world.rng.c])
        self.assertEqual(oracle['r'].state,'f34d')
        self.assertTrue(oracle['w'].sound_commands)
        self.assertEqual(set(oracle['w'].sound_commands),{0x55})
        table='static const uint16_t expected[224][21]={'+','.join(
            '{'+','.join(map(str,row))+'}' for row in expected)+'};\nstatic unsigned observed_frame;'
        source=prefix+'''frame_ready=0
for tick in range(1,225):
    w.frame_counter=tick
    r._update_score_reveal(w)
    frame_ready=tick
final_state=r.state
'''
        self.check(source,classes=True,max_slices=400000,c_helpers=table,after_slice='''
if(PyZ80Target_LoadField(&objects,&modules[0],@frame_ready@,&value) && value.payload!=observed_frame) {
    unsigned n=(unsigned)value.payload,index;
    PyZ80VMValue reveal,world,rng;PyZ80TargetNode *node;
    CHECK(n==observed_frame+1 && n<=224);
    CHECK(PyZ80Target_LoadField(&objects,&modules[0],@r@,&reveal));
    CHECK(PyZ80Target_LoadField(&objects,&modules[0],@w@,&world));
    CHECK(PyZ80Target_LoadField(&objects,&reveal,@timer@,&value));
    CHECK(value.payload==expected[n-1][0]);
    CHECK(PyZ80Target_LoadField(&objects,&reveal,@result_digits@,&value));
    node=PyZ80Target_Node(&objects,&value);CHECK(node && node->item_count==8);
    for(index=0;index<8;++index)CHECK(items[node->item_start+index].payload==expected[n-1][1+index]);
    CHECK(PyZ80Target_LoadField(&objects,&reveal,@display_digits@,&value));
    node=PyZ80Target_Node(&objects,&value);CHECK(node && node->item_count==8);
    for(index=0;index<8;++index)CHECK(items[node->item_start+index].payload==expected[n-1][9+index]);
    CHECK(PyZ80Target_LoadField(&objects,&world,@sound_commands@,&value));
    node=PyZ80Target_Node(&objects,&value);CHECK(node && node->item_count==expected[n-1][17]);
    for(index=0;index<node->item_count;++index)CHECK(items[node->item_start+index].payload==0x55);
    CHECK(PyZ80Target_LoadField(&objects,&world,@rng@,&rng));
    CHECK(PyZ80Target_LoadField(&objects,&rng,@a@,&value));CHECK(value.payload==expected[n-1][18]);
    CHECK(PyZ80Target_LoadField(&objects,&rng,@b@,&value));CHECK(value.payload==expected[n-1][19]);
    CHECK(PyZ80Target_LoadField(&objects,&rng,@c@,&value));CHECK(value.payload==expected[n-1][20]);
    CHECK(PyZ80Target_LoadField(&objects,&reveal,@state@,&value));
    CHECK(value.kind==PYZ80_VM_VALUE_SYMBOL && value.symbol==(n==224 ? @f34d@ : @f260@));
    observed_frame=n;
}''', after='CHECK(observed_frame==224);')


if __name__ == '__main__':
    unittest.main()
