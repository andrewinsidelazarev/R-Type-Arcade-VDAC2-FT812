"""Методы контейнеров: исходный Python против C-исполнения, с GC на каждом шаге."""
import ast
from pathlib import Path
import textwrap
import unittest

from pyz80_compiler.module_imports import pinned_stdlib_sources
from test_pyz80_callable_runtime import PRELUDE, TCC, compile_run
from test_pyz80_import_runtime import import_check


@unittest.skipUnless(TCC, 'нужен локальный C-компилятор')
class ContainerMethodTests(unittest.TestCase):
    def check(self, source, **options):
        for banked in (False, True):
            with self.subTest(banked=banked):
                import_check({'app':source}, banked=banked, generators=True, **options)

    def test_list_append_bound_alias_and_clear(self):
        self.check('''a=[1,2]
alias=a
add=a.append
first=add(3)
last=a[-1]
same=alias is a
size=len(alias)
empty=a.clear()
cleared=len(alias)
add(9)
answer=alias[0]
''')

    def test_generated_plan_records_receiver_dispatch_and_remaining_limits(self):
        from generate_pzvt_target_adapters import build_adapter_specs
        from test_pyz80_scope_runtime import source_artifact
        artifact=source_artifact('def f(a,d,s):\n    a.clear()\n    d.clear()\n    s.clear()\n    return (a.pop(),d.pop(1))\n')
        plan=build_adapter_specs(artifact.adapter_table,artifact.compact_document['constants'],
                                artifact.target_coverage['function_id_table'],artifact.target_coverage['function_call_signatures'])
        methods=plan['container_protocol']['registered_methods']
        self.assertEqual({row['receiver'] for row in methods if row['name']=='clear'}, {'list','dict','set','deque','defaultdict'})
        self.assertEqual({row['receiver'] for row in methods if row['name']=='pop'}, {'list','dict','defaultdict'})
        self.assertFalse(plan['container_protocol']['dynamic_call_sites_proved'])
        self.assertIn('same-size replacement',plan['container_protocol']['dict_iteration_key_mutation'])

    def test_list_pop_and_delete_with_negative_and_boolean_indices(self):
        self.check('''a=[10,20,30,40,50,60]
last=a.pop()
middle=a.pop(-3)
second=a.pop(True)
first=a[False]
a[True]=70
del a[False]
del a[-1]
answer=a[0]
size=len(a)
''')

    def test_list_iterator_tracks_mutations_and_stays_exhausted(self):
        self.check('''a=[1,2,3]
it=iter(a)
first=next(it)
removed=a.pop(0)
second=next(it)
a.append(4)
third=next(it)
end=next(it,99)
a.append(5)
still_end=next(it,88)
it2=iter(a)
a.clear()
a.append(7)
after_clear=next(it2)
''')

    def test_methods_keep_their_original_owner_through_gc(self):
        self.check('''def factory():
    a=[]
    return (a.append,a.pop,a.clear)
methods=factory()
add=methods[0]
pop=methods[1]
clear=methods[2]
answer=0
for i in range(100):
    add(i)
    garbage=[i,i+1]
    answer=answer+pop()
add(8)
clear()
add(9)
last=pop()
''', max_slices=40000)

    def test_dict_pop_delete_reinsert_order_and_defaults(self):
        self.check('''d={'a':1,'b':2,'c':3}
alias=d
first=d.pop('a')
del d['b']
d['a']=4
d[True]=5
existing=d.pop(1,99)
missing=d.pop(0,17)
none=d.pop(None,None)
keys=tuple(d)
key0=keys[0]
key1=keys[1]
size=len(alias)
clear=d.clear()
empty=len(alias)
d[None]=d
cycle=d.pop(None) is d
''')

    def test_defaults_evaluated_even_for_present_keys(self):
        self.check('''events=0
def default():
    global events
    events=events+1
    return 99
d={1:7}
first=d.pop(1,default())
second=d.pop(1,default())
''')

    def test_views_are_dynamic_and_iterate_in_insertion_order(self):
        self.check('''d={'a':1,'b':2}
keys=d.keys()
values=d.values()
items=d.items()
before=len(items)
d['a']=11
d[3]=33
after=len(keys)
ks=tuple(keys)
vs=tuple(values)
ps=tuple(items)
k0=ks[0]
k1=ks[1]
k2=ks[2]
v0=vs[0]
v1=vs[1]
v2=vs[2]
p0k=ps[0][0]
p0v=ps[0][1]
p2k=ps[2][0]
p2v=ps[2][1]
truth=bool(values)
d.clear()
empty_size=len(items)
empty_truth=bool(keys)
empty_not=not values
d[7]=8
new_pair=tuple(items)
new_key=new_pair[0][0]
new_value=new_pair[0][1]
snapshot_value=ps[0][1]
''')

    def test_items_unpack_snapshot_then_delete_source(self):
        self.check('''d={1:10,2:20,3:30}
snapshot=tuple(d.items())
answer=0
for key,value in snapshot:
    answer=answer+key*value
    del d[key]
size=len(d)
first_value=snapshot[0][1]
''')

    def test_views_keep_owner_and_values_live_after_gc(self):
        self.check('''class Item:
    def __init__(self,value):
        self.value=value
def factory():
    d={'a':Item(7),'b':Item(9)}
    return d.items()
view=factory()
answer=0
for i in range(60):
    garbage=[i,i+1]
    for key,value in view:
        answer=answer+value.value
''', classes=True, max_slices=40000)

    def test_view_iterators_independent_and_read_current_values(self):
        self.check('''d={1:10,2:20}
view=d.items()
a=iter(view)
b=iter(view)
different=a is not b
first=next(a)
d[2]=99
second=next(a)
other=next(b)
first_value=first[1]
second_value=second[1]
other_value=other[1]
end=next(a,None)
d[3]=30
still_end=next(a,None)
''')

    def test_view_mutation_size_changes_fail_closed(self):
        for view in ('keys','values','items'):
            for mutation in ('d.clear()', 'd.pop(1)', 'd[3]=30'):
                with self.subTest(view=view, mutation=mutation):
                    self.check(f'd={{1:10,2:20}}\nit=iter(d.{view}())\nnext(it)\n{mutation}\nnext(it)\n', expect_vm_error=True)

    def test_same_size_key_replacement_is_explicitly_unsupported(self):
        # CPython допускает некоторые такие обходы; пока требуем явный отказ,
        # а не выдачу другого порядка ключей из уплотнённого хранилища C.
        self.check('d={1:10,2:20}\nit=iter(d.items())\nnext(it)\ndel d[2]\nd[3]=30\nnext(it)\n', expect_vm_error=True)

    def test_methods_dispatch_by_actual_receiver_not_name(self):
        self.check('''class Custom:
    def clear(self):
        return 7
    def pop(self,index):
        return index+100
a=[1,2]
d={1:9}
s={1,2}
c=Custom()
av=a.pop()
dv=d.pop(1)
cv=c.pop(3)
cc=c.clear()
a.clear()
d.clear()
s.clear()
total=len(a)+len(d)+len(s)
''', classes=True)

    def test_invalid_calls_do_not_fall_through_to_external_provider(self):
        for expression in ('a.append()', 'a.append(1,2)', 'a.append(object=1)',
                           'a.clear(1)', 'a.pop(99)', 'a.pop(-99)', 'a.pop(0,1)', 'a.pop(index=0)',
                           'a.pop(None)', 'd.pop()', 'd.pop(99)', 'd.pop([],None)', 'd.pop(1,2,3)',
                           'd.clear(1)', 'd.keys(1)', 'd.items(x=1)', 'd.values(1)',
                           'del a[99]', 'del a[()]', 'del d[99]', 'del t[0]', 't.append(1)'):
            with self.subTest(expression=expression):
                self.check('a=[1]\nd={1:2}\nt=(1,)\n'+expression+'\n', expect_vm_error=True)
        for name in ('append', 'clear', 'pop', 'keys', 'values', 'items'):
            with self.subTest(global_name=name):
                self.check(f'a=[1]\nd={{1:2}}\n{name}(1)\n', expect_vm_error=True, expected_external=1)

    def test_empty_pop_and_empty_clear(self):
        self.check('a=[]\nx=a.clear()\nd={}\ny=d.clear()\nxsize=len(a)\nysize=len(d)\n')
        self.check('a=[]\na.pop()\n', expect_vm_error=True)

    def test_actual_sound_queue_drain_and_force_resource_release(self):
        root=Path(__file__).resolve().parents[1]/'Python/rtype_port'
        names={'enemies.py': ('take_sound_commands',),
               'force.py': ('_release_ray','_release_grid','_release_beam','_release_dart')}
        methods=[]
        for filename, wanted in names.items():
            text=(root/filename).read_text(encoding='utf-8')
            for name in wanted:
                matches=[n for n in ast.walk(ast.parse(text)) if isinstance(n,ast.FunctionDef) and n.name==name]
                self.assertEqual(len(matches),1)
                node=matches[0]
                methods.append(textwrap.dedent('\n'.join(text.splitlines()[node.lineno-1:node.end_lineno])))
        source='from __future__ import annotations\n'+'\n'.join(methods)+'''
class State:
    pass
class Segment:
    def __init__(self,slot):
        self.resource_slot=slot
state=State()
state.sound_commands=[0x30,0x37]
queue_alias=state.sound_commands
commands=take_sound_commands(state)
empty_commands=take_sound_commands(state)
queue_alias.append(0x38)
later_commands=take_sound_commands(state)
cmd0=commands[0]
cmd1=commands[1]
later=later_commands[0]
empty_count=len(empty_commands)
queue_count=len(queue_alias)
released=[]
def release(slot):
    released.append(slot)
state.ray_segments={1:Segment(11),2:Segment(12)}
state.grid_segments={1:Segment(21)}
state.beams={1:Segment(31)}
state.darts={1:Segment(41)}
_release_ray(state,1,release)
_release_ray(state,1,release)
_release_grid(state,1,release)
_release_beam(state,1,release)
_release_dart(state,1,release)
count=len(released)
r0=released[0]
r1=released[1]
r2=released[2]
r3=released[3]
remaining=state.ray_segments[2].resource_slot
'''
        future=pinned_stdlib_sources()['__future__'].read_text(encoding='utf-8')
        for banked in (False,True):
            import_check({'app':source,'__future__':future}, classes=True, generators=True, banked=banked)

    def test_iteration_allocation_and_version_failures_are_atomic(self):
        compile_run(PRELUDE+r'''
int main(void) {
    PyZ80TargetContext c;PyZ80TargetNode nodes[16],saved,iterator_saved;
    PyZ80TargetField fields[8];PyZ80VMValue items[64],d,k,v,out,view,it,list,bad;
    uint16_t used;
    PyZ80Target_Init(&c,nodes,16,fields,8,items,64,0,0,0,0,0,0);
    CHECK(PyZ80Target_AllocateNode(&c,PYZ80_TARGET_NODE_DICT,65535,&d));
    k=integer(1);v=integer(10);
    CHECK(PyZ80Target_DictStore(&c,&d,&k,&v));
    CHECK(PyZ80Target_DictView(&c,&d,2,&view));
    CHECK(PyZ80Target_GetIterator(&c,&view,&it));
    saved=*PyZ80Target_Node(&c,&d);iterator_saved=*PyZ80Target_Node(&c,&it);
    used=c.item_used;c.item_capacity=used;
    CHECK(!PyZ80Target_IterNext(&c,&it,&out));
    CHECK(!memcmp(&iterator_saved,PyZ80Target_Node(&c,&it),sizeof(saved)) && c.item_used==used);
    CHECK(!memcmp(&saved,PyZ80Target_Node(&c,&d),sizeof(saved)));
    c.item_capacity=64;
    CHECK(PyZ80Target_IterNext(&c,&it,&out));
    CHECK(PyZ80Target_Node(&c,&it)->cursor==1);
    PyZ80Target_Node(&c,&d)->current.payload=0xffffffffUL;
    saved=*PyZ80Target_Node(&c,&d);
    CHECK(!PyZ80Target_DictRemove(&c,&d,&k,&out));
    CHECK(!PyZ80Target_DictClear(&c,&d));
    k=integer(2);CHECK(!PyZ80Target_DictStore(&c,&d,&k,&v));
    CHECK(!memcmp(&saved,PyZ80Target_Node(&c,&d),sizeof(saved)));
    k=integer(1);CHECK(PyZ80Target_DictStore(&c,&d,&k,&v));
    CHECK(PyZ80Target_EmptyList(&c,&list));CHECK(PyZ80Target_ListAppend(&c,&list,&v));
    saved=*PyZ80Target_Node(&c,&list);bad=integer(0x80000000UL);
    CHECK(!PyZ80Target_ListPop(&c,&list,&bad,&out));
    CHECK(!memcmp(&saved,PyZ80Target_Node(&c,&list),sizeof(saved)));
    return 0;
}
''')

    def test_view_consumer_yields_between_items(self):
        import_check({'app':'''d={x:x+1 for x in range(20)}
it=iter(d.items())
snapshot=tuple(it)
answer=snapshot[19][1]
'''}, generators=True, banked=True, budget=1, c_helpers='static unsigned previous_cursor;',
            after_slice='''if(PyZ80Target_LoadField(&objects,&modules[0],@it@,&value)) {
    PyZ80TargetNode *node=PyZ80Target_Node(&objects,&value);
    CHECK(node && node->kind==PYZ80_TARGET_NODE_ITERATOR);
    CHECK(node->cursor>=previous_cursor && node->cursor<=previous_cursor+1);
    previous_cursor=node->cursor;
}''', after='CHECK(previous_cursor==20);')

    def test_gc_rejects_corrupt_view_before_changing_heap(self):
        import_check({'app':'d={1:2}\nview=d.items()\nanswer=7'}, generators=True, banked=True,
            after='''{
    PyZ80TargetNode *view;PyZ80VMValue owner;
    PyZ80TargetNode saved_nodes[HEAP_NODES];PyZ80TargetField saved_fields[HEAP_FIELDS];
    PyZ80VMValue saved_items[HEAP_ITEMS];
    CHECK(PyZ80Target_LoadField(&objects,&modules[0],@view@,&value));
    view=PyZ80Target_Node(&objects,&value);CHECK(view && view->kind==PYZ80_TARGET_NODE_DICT_VIEW);
    owner=view->current;view->current=integer(7);
    memcpy(saved_nodes,nodes,sizeof(nodes));memcpy(saved_fields,fields,sizeof(fields));memcpy(saved_items,items,sizeof(items));
    CHECK(!PyZ80Target_Collect(&objects,&vm,&scopes,modules,MODULES,&gc));
    CHECK(!memcmp(saved_nodes,nodes,sizeof(nodes)) && !memcmp(saved_fields,fields,sizeof(fields)) && !memcmp(saved_items,items,sizeof(items)));
    view->current=owner;
    CHECK(PyZ80Target_Collect(&objects,&vm,&scopes,modules,MODULES,&gc));
}''')


if __name__ == '__main__':
    unittest.main()
