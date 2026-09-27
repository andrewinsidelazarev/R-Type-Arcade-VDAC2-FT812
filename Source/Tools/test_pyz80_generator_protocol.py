"""Python-фабрики и потребители генераторов через настоящие таблицы и C VM."""
import ast
from pathlib import Path
import unittest

from test_pyz80_callable_runtime import TCC
from test_pyz80_import_runtime import import_check
from pyz80_compiler.module_imports import pinned_stdlib_sources


@unittest.skipUnless(TCC, 'host C compiler unavailable')
class GeneratorProtocolTests(unittest.TestCase):
    def test_attach_rejects_overlapping_roots_routes_and_bank_storage(self):
        import_check({'app':'answer=7'},generators=True,banked=True,
            after_attach='''CHECK(!PyZ80Target_AttachGenerators(&generators,&scopes,generator_frames,
    (PyZ80VMValue *)generator_frames,DEPTH,generator_routes));
CHECK(!PyZ80Target_AttachGenerators(&generators,&scopes,generator_frames,
    generator_roots,DEPTH,(uint16_t *)imports.hooks.routes));
CHECK(!PyZ80Target_AttachGenerators((PyZ80TargetGenerators *)&bank_tables,&scopes,
    generator_frames,generator_roots,DEPTH,generator_routes));
CHECK(!PyZ80Target_AttachGenerators(&generators,&scopes,generator_frames,
    generator_roots,0,generator_routes));''')

    def test_gc_rejects_wrong_owner_kind_before_mutating_live_heap(self):
        import_check({'app':'def values():\n    yield [7]\ng=values()\nanswer=1'},
            generators=True,banked=True,after='''{
    PyZ80VMValue owner=vm.generators[0].owner;
    PyZ80TargetNode saved_nodes[HEAP_NODES];PyZ80TargetField saved_fields[HEAP_FIELDS];
    PyZ80VMValue saved_items[HEAP_ITEMS];
    memcpy(saved_nodes,nodes,sizeof(nodes));memcpy(saved_fields,fields,sizeof(fields));
    memcpy(saved_items,items,sizeof(items));
    vm.generators[0].owner.kind=PYZ80_VM_VALUE_CELL;
    CHECK(!PyZ80Target_Collect(&objects,&vm,&scopes,modules,MODULES,&gc));
    CHECK(!memcmp(saved_nodes,nodes,sizeof(nodes)) && !memcmp(saved_fields,fields,sizeof(fields)) &&
          !memcmp(saved_items,items,sizeof(items)) && vm.generators[0].in_use);
    vm.generators[0].owner=owner;
    CHECK(PyZ80Target_Collect(&objects,&vm,&scopes,modules,MODULES,&gc));
}''')

    def test_native_consumers_advance_at_most_one_item_per_slice(self):
        for expression in ('any(it)','len(tuple(it))'):
            with self.subTest(expression=expression):
                import_check({'app':'it=iter([0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0])\nanswer='+expression},
                    generators=True,banked=True,budget=1,c_helpers='static unsigned previous_cursor;',
                    after_slice='''if(PyZ80Target_LoadField(&objects,&modules[0],@it@,&value)) {
    PyZ80TargetNode *node=PyZ80Target_Node(&objects,&value);
    CHECK(node && node->kind==PYZ80_TARGET_NODE_ITERATOR);
    CHECK(node->cursor>=previous_cursor && node->cursor<=previous_cursor+1);
    previous_cursor=node->cursor;
}''',after='CHECK(previous_cursor==16);')

    def test_not_uses_python_truth_for_all_supported_value_kinds(self):
        import_check({'app':'''a=not None
b=not []
c=not [0]
d=not ()
e=not (0,)
f=not {}
g=not {1:0}
h=not set()
i=not {0}
j=not ""
k=not "0"
l=not range(0)
m=not range(1)
n=not (x for x in [])
o=not next
p=not False
q=not -1
'''.strip()},generators=True,banked=True)

    def test_actual_force_and_beam_expressions(self):
        path=Path(__file__).resolve().parents[1]/'Python/rtype_port/force.py'
        tree=ast.parse(path.read_text(encoding='utf-8'))
        collision=next(n.value for n in ast.walk(tree) if isinstance(n,ast.Assign)
            and any(isinstance(t,ast.Name) and t.id=='adjacent_collision' for t in n.targets)
            and isinstance(n.value,ast.Call))
        descriptors=next(n.value for n in ast.walk(tree) if isinstance(n,ast.Assign)
            and any(isinstance(t,ast.Attribute) and t.attr=='descriptors' for t in n.targets)
            and isinstance(n.value,ast.Call) and isinstance(n.value.args[0],ast.GeneratorExp))
        source=('def collision(adjacent):\n    return '+ast.unparse(collision)+'\n'
                'def descriptors(base):\n    return '+ast.unparse(descriptors)+'\n'
                'a=collision([0x0DFC,0x0DFD])\nb=collision([0x0DFC,0x0DFB])\n'
                'c=collision([])\nd=collision([0,0x0FFF])\n'
                'parts=descriptors(0x2400)\np0=parts[0]\np1=parts[1]\np2=parts[2]\np3=parts[3]\n')
        import_check({'app':source},generators=True,banked=True)

    def test_actual_checkpoint_selection_function(self):
        path=Path(__file__).resolve().parents[1]/'Python/rtype_port/player_lifecycle.py'
        tree=ast.parse(path.read_text(encoding='utf-8'))
        function=next(n for n in tree.body if isinstance(n,ast.FunctionDef)
                      and n.name=='checkpoint_for_progression')
        source='''class Checkpoint:
    def __init__(self,stage,progression,index):
        self.stage=stage
        self.progression=progression
        self.index=index
CHECKPOINTS=(Checkpoint(1,0,0),Checkpoint(1,10,1),Checkpoint(2,20,2))
'''+ast.unparse(function)+'''
a=checkpoint_for_progression(1,0).index
b=checkpoint_for_progression(1,9).index
c=checkpoint_for_progression(1,10).index
d=checkpoint_for_progression(1,65536).index
e=checkpoint_for_progression(2,0).index
f=checkpoint_for_progression(2,20).index
'''
        future=pinned_stdlib_sources()['__future__'].read_text(encoding='utf-8')
        import_check({'app':'from __future__ import annotations\n'+source,'__future__':future},
                     generators=True,classes=True,banked=True)

    def test_actual_boss_flash_method(self):
        path=Path(__file__).resolve().parents[1]/'Python/rtype_port/game.py'
        tree=ast.parse(path.read_text(encoding='utf-8'))
        method=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef)
                    and n.name=='_sync_boss_hit_flash')
        source='''class State:
    pass
class Enemy:
    def __init__(self,kind,flash):
        self.kind=kind
        self.flash_visible=flash
'''+ast.unparse(method)+'''
game=State()
game.stage=State()
game.enemy_world=State()
game.enemy_world.enemies=[Enemy("other",True),Enemy("dobkeratops_body",False)]
_sync_boss_hit_flash(game)
a=game.stage.boss_palette_active
b=game.stage.boss_hit_flash
game.enemy_world.enemies[1].flash_visible=True
_sync_boss_hit_flash(game)
c=game.stage.boss_hit_flash
game.enemy_world.enemies=[]
_sync_boss_hit_flash(game)
d=game.stage.boss_palette_active
e=game.stage.boss_hit_flash
'''
        import_check({'app':source},generators=True,classes=True,banked=True)

    def test_nested_shadowing_and_global_lookup_do_not_create_false_captures(self):
        import_check({'app':'''x=50
def make(seed):
    return [[(x+seed for z in [0]) for x in [1,2]] for x in [8,9]]
groups=make(10)
a=next(groups[0][0])
b=next(groups[1][1])
class A:
    x=99
    rows=[(x for y in [0]) for k in [1,2]]
c=next(A.rows[0])
x=60
d=next(A.rows[1])
'''.strip()},generators=True,classes=True,generator_slots=8,banked=True)

    def test_reentrant_generator_and_live_slot_exhaustion_fail_closed(self):
        for source,slots in (('''def values():
    yield next(g)
g=values()
x=next(g)
''',2),('''def values():
    yield 1
a=values()
b=values()
''',1)):
            with self.subTest(slots=slots):
                import_check({'app':source},generators=True,generator_slots=slots,
                             expect_vm_error=True,banked=True)

    def test_consumer_step_budget_and_finished_slot_reuse(self):
        import_check({'app':'''def values():
    yield 0
g=values()
a=next(g)
end=next(g,77)
h=values()
b=next(h)
c=next(g,88)
d=next(h,99)
answer=any(x==99 for x in range(100))
'''.strip()},generators=True,generator_slots=1,banked=True,budget=1,
            before_slice='CHECK(vm.call_depth<=DEPTH);',max_slices=40000)

    def test_generator_expressions_evaluate_outer_iterator_once_and_body_lazily(self):
        import_check({'app':'''seen=0
def source():
    global seen
    seen=seen+1
    return [1,2,3]
def produce(x):
    global seen
    seen=seen+10
    return x*2
g=(produce(x) for x in source() if x>1)
before=seen
a=next(g)
middle=seen
b=next(g)
end=next(g,99)
after=seen
'''.strip()},generators=True,banked=True)

    def test_nested_scopes_capture_cells_not_values(self):
        import_check({'app':'''def make(seed):
    items=[(seed+x for x in [1,2]) for k in [0,1]]
    seed=seed+10
    return items
items=make(7)
a=next(items[0])
b=next(items[1])
rows={power:tuple(power*10+phase for phase in range(2)) for power in [1,2,3]}
c=rows[2][1]
d=rows[3][0]
groups=[(x for y in [0]) for x in [1,2,3]]
late=next(groups[0])
'''.strip()},generators=True,generator_slots=8,banked=True,max_depth=10)

    def test_generator_expression_survives_creator_return_and_short_circuit(self):
        import_check({'app':'''def make(seed):
    return (x+seed for x in [0,1,2] if x!=1)
g=make(10)
a=next(g)
b=next(g)
c=next(g,77)
answer=any(x==3 for x in range(100))
flat=tuple(x*10+y for x in [1,2] for y in [3,4] if y>x)
d=flat[3]
'''.strip()},generators=True,banked=True)

    def test_lazy_calls_defaults_aliases_and_sticky_exhaustion(self):
        source = '''seen=0
def values(seed=7,*,step=2):
    global seen
    seen=seen+1
    yield seed
    seen=seen+10
    yield seed+step
    return 999
alias=values
g=alias(step=3)
before=seen
n=next
a=n(g)
middle=seen
b=n(g)
c=n(g,77)
d=n(g,88)
same=iter(g) is g
after=seen
'''
        for banked in (False,True):
            with self.subTest(banked=banked):
                import_check({'app':source},generators=True,banked=banked)

    def test_for_loops_nested_generators_and_comprehensions(self):
        source = '''def inner(seed):
    for x in [1,2,3]:
        yield seed+x
def outer(seed):
    for x in inner(seed):
        yield x*2
g=outer(7)
items=[x for x in g if x!=18]
answer=items[0]+items[1]
empty=next(g,99)
'''
        import_check({'app':source},generators=True,banked=True)

    def test_any_short_circuits_and_tuple_consumes_remaining_values(self):
        source = '''seen=0
def values():
    global seen
    for x in [0,0,7,8,9]:
        seen=seen+1
        yield x
g=values()
truth=any(g)
partial=seen
tail=tuple(g)
a=tail[0]
b=tail[1]
after=seen
empty=any(g)
zero=tuple()
same=tuple(tail) is tail
length=len(zero)
'''
        import_check({'app':source},generators=True,banked=True)

    def test_native_iterator_consumers_share_protocol(self):
        import_check({'app':'''it=iter([1,2,3])
a=next(it)
b=next(it,99)
tail=tuple(it)
c=tail[0]
d=next(it,77)
yes=any([0,0,3,0])
no=any([])
r=tuple(range(3))
answer=r[2]
'''},generators=True)

    def test_bound_generator_methods_and_captured_mutation(self):
        source = '''class A:
    def __init__(self,seed):
        self.seed=seed
    def values(self,step=1):
        yield self.seed
        self.seed=self.seed+step
        yield self.seed
a=A(10)
method=a.values
g=method(step=3)
before=a.seed
x=next(g)
y=next(g)
after=a.seed
end=next(g,77)
'''
        import_check({'app':source},classes=True,generators=True,banked=True)

    def test_unreachable_generators_release_slots_including_cycles(self):
        source = '''def values(holder):
    yield holder
def make():
    holder=[None]
    g=values(holder)
    holder[0]=g
    return 0
total=0
for i in range(80):
    total=total+make()
answer=i
'''
        import_check({'app':source},generators=True,generator_slots=1,banked=True,max_slices=40000)

    def test_invalid_calls_fail_before_running_body(self):
        for call in ('values(1,2)', 'values(bad=1)', 'next(values())', 'next(values(),bad=3)'):
            source='def values():\n    if False:\n        yield 7\n'+call+'\n'
            with self.subTest(call=call):
                import_check({'app':source},generators=True,expect_vm_error=True)


if __name__ == '__main__':
    unittest.main()
