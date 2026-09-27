"""Стабильная сортировка и исходные key-функции через C VM и банковую память."""
import ast
from pathlib import Path
import textwrap
import random
import unittest

from test_pyz80_callable_runtime import PRELUDE, TCC, compile_run
from test_pyz80_import_runtime import import_check
from pyz80_compiler.module_imports import pinned_stdlib_sources


@unittest.skipUnless(TCC, 'нужен локальный C-компилятор')
class SortRuntimeTests(unittest.TestCase):
    def check(self, source, **options):
        for banked in (False,True):
            with self.subTest(banked=banked):
                import_check({'app':source},generators=True,sorting=True,banked=banked,**options)

    def test_scheduler_key_and_equal_key_stability(self):
        source='''def key(item):
    return (item[1][0],-item[1][1],item[0])
enemies=[(0x8010,1),(0x10,5),(0x1000,1),(0x8010,2),(0x8010,1)]
ordered=sorted(enumerate(tuple(enemies)),key=key)
a=ordered[0][0]
b=ordered[1][0]
c=ordered[2][0]
d=ordered[3][0]
e=ordered[4][0]
'''
        self.check(source)

    def test_scalar_sort_reverse_and_bool_identity(self):
        self.check('''a=[4,-2147483648,True,1,0,2147483647,-2]
b=sorted(a)
c=sorted(a,reverse=True)
b0=b[0]
b1=b[1]
b2=b[2]
b3_is_bool=b[3] is True
b4_is_bool=b[4] is True
b6=b[6]
c0=c[0]
c2_is_bool=c[2] is True
c3_is_bool=c[3] is True
unchanged=a[0]
different=a is not b
empty=len(sorted([],key=7))
single=sorted([9],key=None)[0]
''')

    def test_stability_with_constant_keys_in_both_directions(self):
        self.check('''a=[7,2,8,1,3,9,4]
def key(value):
    return value%2
b=sorted(a,key=key)
c=sorted(a,reverse=-1,key=key)
bt=0
ct=0
for x in b:
    bt=bt*10+x
for x in c:
    ct=ct*10+x
''')

    def test_iterable_is_consumed_before_key_and_key_called_once(self):
        self.check('''source=[3,1,2]
calls=0
order=0
def key(value):
    global calls,order
    calls=calls+1
    order=order*10+value
    source.append(99)
    return value
result=sorted(source,key=key)
a=result[0]
b=result[1]
c=result[2]
source_size=len(source)
result_size=len(result)
''')

    def test_key_defaults_closures_and_bound_receiver_survive_gc(self):
        self.check('''class Key:
    def __init__(self,offset):
        self.offset=offset
    def evaluate(self,x,scale=-1,*,bias=7):
        return x*scale+self.offset+bias
def factory(offset):
    key=Key(offset)
    return key.evaluate
saved=factory(11)
result=sorted([2,7,1,3],key=saved)
a=result[0]
b=result[1]
c=result[2]
d=result[3]
def outer(seed):
    def key(x,offset=seed):
        return x+offset+seed
    return key
result2=sorted([3,1,2],key=outer(9))
e=result2[0]
''',classes=True)

    def test_nested_sorted_in_key_and_generator_callback_composition(self):
        self.check('''def stream(x):
    yield x
    yield 9-x
def key(x):
    pair=tuple(stream(x))
    return sorted(pair)[0]
a=sorted([7,3,1,8],key=key)
r0=a[0]
r1=a[1]
r2=a[2]
r3=a[3]
''')

    def test_source_lambda_sort_key(self):
        self.check('''a=sorted([(3,9),(1,8),(3,7),(1,6)],key=lambda x:(x[0],-x[1]))
first=a[0][1]
second=a[1][1]
third=a[2][1]
fourth=a[3][1]
''')

    def test_enumerate_keywords_nested_mutations_and_limits(self):
        self.check('''source=[7,8]
e=enumerate(start=-2,iterable=source)
same=iter(e) is e
first=next(e)
source.append(9)
tail=tuple(e)
a=first[0]
b=first[1]
c=tail[1][0]
d=tail[1][1]
end=next(e,99)
source.append(10)
still_end=next(e,88)
nested=tuple(enumerate(enumerate([4,5],start=True),start=7))
n0=nested[0][0]
n1=nested[0][1][0]
n2=nested[1][1][1]
edge=enumerate([9],2147483647)
last=next(edge)
max_index=last[0]
after_max=next(edge,77)
''')

    def test_enumerate_over_dict_view_and_for_loop(self):
        self.check('''d={3:30,1:10,2:20}
total=0
for index,(key,value) in enumerate(d.items(),start=1):
    total=total+index*key+value
indices=tuple(enumerate(range(3)))
answer=indices[2][1]
''')

    def test_invalid_sort_and_enumerate_calls_fail_closed(self):
        for call in ('sorted()', 'sorted([1],None)', 'sorted([1],bad=1)', 'sorted(iterable=[1])',
                     'sorted([1],reverse=[])', 'sorted([1],key=7)', 'sorted([1,2],key=lambda x:[])',
                     'sorted([1,2],key=lambda x:None)', 'sorted([1.5,2.5])',
                     'enumerate()', 'enumerate([1],start=1.5)', 'enumerate([1],iterable=[2])',
                     'enumerate([1],0,start=2)', 'enumerate([1],bad=1)', 'enumerate(7)',
                     'tuple(enumerate([1,2],2147483647))'):
            with self.subTest(call=call):
                self.check(call,expect_vm_error=True,after='''{
    unsigned k;for(k=0;k<DEPTH;++k)CHECK(sort_frames[k].state==0);
    for(k=0;k<7*DEPTH;++k)CHECK(sort_roots[k].kind==PYZ80_VM_VALUE_NONE);
}''')

    def test_actual_scheduler_expression_and_damage_scan(self):
        path=Path(__file__).resolve().parents[1]/'Python/rtype_port/enemies.py'
        text=path.read_text(encoding='utf-8')
        tree=ast.parse(text)
        method=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='damage_shot_native')
        update=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='update' and
                    any(isinstance(c,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='scheduled' for t in c.targets) for c in n.body))
        scheduled=next(n for n in update.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='scheduled' for t in n.targets))
        body=textwrap.dedent('\n'.join(text.splitlines()[method.lineno-1:method.end_lineno]))
        expression=ast.get_source_segment(text,scheduled.value)
        source='from __future__ import annotations\n'+body+'\ndef schedule(self):\n    return '+expression+'''
class Enemy:
    def __init__(self,priority,serial,x,left,right):
        self.scheduler_priority=priority
        self.scheduler_serial=serial
        self.x=x
        self.alive=True
        self.shootable=True
        self.weapon_vulnerable=True
        self.bounds=(left,right,10,20)
    def native_hitbox(self,rom):
        return self.bounds
class World:
    def __init__(self):
        self.enemies=[]
        self.rom=None
        self.hits=[]
    def _damage_with_scheduler_cursor(self,enemy,damage):
        self.hits.append((enemy.scheduler_serial,damage))
world=World()
world.enemies=[Enemy(0x8010,1,100,10,20),Enemy(0x10,2,100,10,20),
               Enemy(0x1000,3,100,10,20),Enemy(0x10,4,100,10,20),Enemy(0x10,5,0x2b4,10,20)]
scheduled=schedule(world)
first_index=scheduled[0][0]
second_index=scheduled[1][0]
third_index=scheduled[2][0]
fourth_index=scheduled[3][0]
fifth_index=scheduled[4][0]
hit=damage_shot_native(world,(20,21,20,21),3)
first_serial=world.hits[0][0]
first_damage=world.hits[0][1]
world.enemies[3].alive=False
hit2=damage_shot_native(world,(20,21,20,21),2)
second_serial=world.hits[1][0]
miss=damage_shot_native(world,(9,10,10,20),5)
count=len(world.hits)
'''
        future=pinned_stdlib_sources()['__future__'].read_text(encoding='utf-8')
        for banked in (False,True):
            import_check({'app':source,'__future__':future},classes=True,generators=True,sorting=True,banked=banked)

    def test_deterministic_odd_lengths_and_sorted_runs(self):
        rng=random.Random(812)
        cases=[[],[1],[1,0],[0,1],list(range(33)),list(range(33,-1,-1)),[3]*31]
        cases += [[rng.randrange(-12,13) for _ in range(n)] for n in (3,5,7,9,15,17,31,32,33,65)]
        for case in cases:
            source='values='+repr(case)+'''
checks=[]
for reverse in (False,True):
    ordered=sorted(values,reverse=reverse)
    checksum=0
    for value in ordered:
        checksum=(checksum*31+value)%10007
    checks.append(checksum)
ascending=checks[0]
descending=checks[1]
'''
            with self.subTest(size=len(case),case=case):
                self.check(source,heap_scale=2,max_args=96,max_slices=30000)

    def test_merge_moves_at_most_one_element_per_slice(self):
        import_check({'app':'answer=sorted([x%7 for x in range(65)],reverse=True)\nsize=len(answer)'},
            generators=True,sorting=True,banked=True,heap_scale=2,max_slices=30000,
            c_helpers='static unsigned old_state,old_width,old_out,moves;',
            after_slice='''{
    PyZ80TargetSortRequest *f=&sort_frames[1];
    if(old_state==6 && f->state==6) {
        CHECK((f->width==old_width && f->out==old_out+1) || (f->width==old_width*2 && f->out==1));
        ++moves;
    }
    old_state=f->state;old_width=f->width;old_out=f->out;
}''',after='CHECK(moves==65*7);')

    def test_attach_rejects_aliases_and_undersized_storage(self):
        import_check({'app':'answer=7'},generators=True,sorting=True,banked=True,
            after_sort='''CHECK(!PyZ80Target_AttachSort(&sorter,&scopes,sort_frames,sort_roots,DEPTH,sort_routes));
CHECK(!PyZ80Target_AttachSort(&sorter,&scopes,sort_frames,(PyZ80VMValue *)sort_frames,DEPTH,sort_routes));
CHECK(!PyZ80Target_AttachSort(&sorter,&scopes,sort_frames,sort_roots,0,sort_routes));
CHECK(!PyZ80Target_AttachSort((PyZ80TargetSort *)&bank_tables,&scopes,sort_frames,sort_roots,DEPTH,sort_routes));''')

    def test_callback_failure_cleans_roots_without_replaying_key(self):
        self.check('''calls=0
def key(x):
    global calls
    calls=calls+1
    return missing_name
answer=sorted([3,1,2],key=key)
''',expect_vm_error=True,expected_external=1,after='''{
    unsigned k;
    for(k=0;k<DEPTH;++k)CHECK(!sort_frames[k].state);
    for(k=0;k<7*DEPTH;++k)CHECK(sort_roots[k].kind==PYZ80_VM_VALUE_NONE);
}''')

    def test_unsupported_iterators_and_comparisons_stay_explicit(self):
        for source in ('e=enumerate(x for x in [1,2])', 'a=sorted(x for x in [1,2])',
                       'a=sorted([((1,),),((2,),)])', 'a=sorted(["b","a"])'):
            with self.subTest(source=source):
                self.check(source,expect_vm_error=True)

    def test_builtin_shadowing_keeps_source_function_semantics(self):
        self.check('''def sorted(value,*,key=None):
    return value+7
def enumerate(value,start=0):
    return value*10+start
answer=sorted(3,key=99)+enumerate(4,start=2)
''')

    def test_sort_allocation_failure_does_not_mutate_source(self):
        self.check('source=[9,1,3]\nresult=sorted(source)', expect_vm_error=True,
            before_slice='objects.item_capacity=10;',
            c_helpers='static PyZ80VMValue source_handle;',
            after_slice='''if(PyZ80Target_LoadField(&objects,&modules[0],@source@,&value))source_handle=value;''',
            after='''{
    PyZ80TargetNode *source=PyZ80Target_Node(&objects,&source_handle);
    unsigned k;CHECK(source && source->item_count==3);
    CHECK(objects.items[source->item_start].payload==9);
    CHECK(objects.items[source->item_start+1].payload==1);
    CHECK(objects.items[source->item_start+2].payload==3);
    for(k=0;k<DEPTH;++k)CHECK(!sort_frames[k].state);
    for(k=0;k<7*DEPTH;++k)CHECK(sort_roots[k].kind==PYZ80_VM_VALUE_NONE);
}''')

    def test_missing_result_handler_and_stack_limit_fail_closed(self):
        self.check('answer=sorted([2,1],key=lambda x:x)', expect_vm_error=True,
                   after_sort='sorter.hooks.call_result=0;')
        self.check('''def key(x):
    if x:
        return key(x-1)
    return 7
answer=sorted([4,3],key=key)
''',max_depth=3,expect_vm_error=True)

    def test_enumerate_cycle_guard_at_maximum_node_count(self):
        compile_run(PRELUDE+r'''
static PyZ80TargetNode nodes[65535];
int main(void) {
    PyZ80TargetContext c;PyZ80TargetField fields[8];PyZ80VMValue items[32],list,e,out,value;
    PyZ80TargetNode saved;
    PyZ80Target_Init(&c,nodes,65535,fields,8,items,32,0,0,0,0,0,0);
    CHECK(PyZ80Target_EmptyList(&c,&list));value=integer(7);CHECK(PyZ80Target_ListAppend(&c,&list,&value));
    CHECK(PyZ80Target_Enumerate(&c,&list,0,&e));
    PyZ80Target_Node(&c,&e)->source_link=(uint16_t)e.payload;
    PyZ80Target_Node(&c,&e)->source_generation=(uint16_t)(e.payload>>16);
    c.node_used=65535;saved=*PyZ80Target_Node(&c,&e);
    CHECK(!PyZ80Target_IterNext(&c,&e,&out));
    CHECK(!memcmp(&saved,PyZ80Target_Node(&c,&e),sizeof(saved)));
    return 0;
}
''')


if __name__=='__main__':
    unittest.main()
