"""Множества: исходный AST -> PZVT -> C с покомандной сборкой мусора."""
import ast
from pathlib import Path
import unittest

from test_pyz80_callable_runtime import PRELUDE, TCC, compile_run
from test_pyz80_import_runtime import import_check


@unittest.skipUnless(TCC, 'нужен локальный C-компилятор')
class SetRuntimeTests(unittest.TestCase):
    def check(self, source, **options):
        for banked in (False, True):
            with self.subTest(banked=banked):
                import_check({'app':source},banked=banked,**options)

    def test_scalar_keys_and_eager_constructor(self):
        self.check('''a={1,True,False,0,None,'key',-2147483648,2147483647}
size=len(a)
yes=True in a
no=2 not in a
empty=bool(set())
truth=bool(a)
b=frozenset(a)
same=frozenset(b) is b
copy=set(a)
distinct=copy is not a
equal=copy==a
frozen_equal=a==b
different_none=a==None
different_list=a==[]
different_tuple=()!=a
different_dict={}==a
r=set(range(-3,4,2))
range_equal=r=={-3,-1,1,3}
negative=set(range(7,-3,-3))=={7,4,1,-2}
d=set({'a':1,'b':2})
dict_keys=d=={'a','b'}
''')

    def test_mutations_return_none_preserve_aliases_and_bound_owner(self):
        self.check('''a=set()
alias=a
add=a.add
remove=a.remove
discard=a.discard
clear=a.clear
added=add(1) is None
a=set([9])
add(True)
size=len(alias)
removed=remove(1) is None
discarded=discard(1) is None
after=len(alias)
add(None)
cleared=clear() is None
final=len(alias)
untouched=9 in a
''')

    def test_binary_operations_and_augmented_assignment(self):
        self.check('''a={1,2,3}
b=frozenset([3,4])
union=(a|b)=={1,2,3,4}
intersection=(a&b)=={3}
difference=(a-b)=={1,2}
symmetric=(a^b)=={1,2,4}
subset={1,2}<a
subset_equal=a<=a
superset=a>{2}
superset_equal=a>=a
disjoint_order=({1}<{2}) is False
unequal=a!=b
alias=a
a|=b
alias_kept=a is alias
union_alias=alias=={1,2,3,4}
a&={2,3,5}
intersection_alias=alias=={2,3}
a^={3,4}
xor_alias=alias=={2,4}
a-={4}
diff_alias=alias=={2}
f=frozenset([1,2])
old=f
f|={3}
frozen_rebound=f is not old
frozen_type=frozenset(f) is f
old_unchanged=old=={1,2}
''')

    def test_comprehension_filters_scope_and_side_effects(self):
        self.check('''events=0
x=99
def produce(x):
    global events
    events=events*10+x
    return x
def make(seed):
    return {produce(x)+seed for x in [1,2,1,0] if x}
s=make(10)
answer=s=={11,12}
unchanged=x
nested={x*10+y for x in [1,2] for y in [2,3] if y==2}
nested_ok=nested=={12,22}
set=37
empty={x for x in []}
empty_ok=len(empty)
''')

    def test_literal_and_constructor_side_effect_order(self):
        self.check('''events=0
def step(n):
    global events
    events=events*10+n
    return n
s={step(1),step(2),step(1)}
literal_order=events
events=0
s=frozenset([step(3),step(4),step(3)])
constructor_order=events
size=len(s)
''')

    def test_saved_methods_growth_clear_and_gc(self):
        self.check('''def factory():
    s={None}
    return s.add,s.remove,s.clear,s
methods=factory()
add=methods[0]
remove=methods[1]
clear=methods[2]
s=methods[3]
for i in range(70):
    add(i)
    garbage={i+100,i+200}
count=len(s)
for i in range(70):
    remove(i)
remaining=s=={None}
clear()
empty=len(s)
add(81)
last=81 in s
''',heap_scale=2,max_slices=30000)

    def test_unsupported_keys_calls_and_iteration_do_not_guess(self):
        for source in (
            's={[]}', 's={1.5}', 's={(1,2)}', 's={frozenset([1])}',
            'set([1], [2])', 'set(iterable=[1])', 'frozenset(None)',
            's={1}\ns.remove(2)', 's=frozenset([1])\ns.add(2)',
            's={1}\ns.add(value=2)', 's={1}\ns.clear(2)',
            's={1}\ns|[2]', 's={1}\ns.get(1)',
            's={1}\nfor x in s:\n    pass',
            's={1}\ns.discard([])', 's={1}\ns==1.5',
        ):
            with self.subTest(source=source):
                self.check(source,expect_vm_error=True)
        self.check('s=set()\nf=s.add\nadd(1)',expect_vm_error=True,expected_external=1)
        # Без обработчика запрещена сама фабрика; с ним set-потребитель
        # генераторов пока неподдержан. Обе ошибки без внешней подмены.
        for generators in (False,True):
            self.check('s=set(x for x in [1,2])',expect_vm_error=True,generators=generators)

    def test_active_source_sound_and_handler_tables(self):
        root=Path(__file__).resolve().parents[2]/'Source/Python/rtype_port'
        groups={
            'audio.py':('REPLACE_COMMANDS','FADE_COMMANDS','NOOP_COMMANDS','ONE_SHOT_COMMANDS'),
            'force.py':('MATRIX_LATCH_CALLBACKS',),
            'stage.py':('M72_INTEGRATOR_MISSING',),
            'enemies.py':('DELEGATED_HANDLERS',),
        }
        for filename,names in groups.items():
            source=(root/filename).read_text(encoding='utf-8')
            nodes=[n for n in ast.walk(ast.parse(source)) if isinstance(n,ast.Assign) and
                   any(isinstance(t,ast.Name) and t.id in names for t in n.targets)]
            self.assertEqual(len(nodes),len(names))
            fixture='\n'.join(ast.get_source_segment(source,n) for n in nodes)+'\n'
            expected={}
            exec(compile(fixture,filename,'exec'),expected)
            checks=[]
            for name in names:
                fixture+=f'n_{name}=len({name})\n'
                checks.append(f'CHECK(PyZ80Target_LoadField(&objects,&modules[$app$],@{name}@,&value));')
                for key in sorted(expected[name]):
                    checks.append(f'result=integer({key}UL);CHECK(PyZ80Target_SetFind(&objects,&value,&result)==1u);')
            with self.subTest(filename=filename):
                self.check(fixture,max_args=100,after='\n'.join(checks))

    def test_comprehension_stack_proof_reconstruction(self):
        import copy
        from pyz80_compiler.whole_program_vm_backend import _unit_specs
        from pyz80_compiler.whole_program_vm_stack_bound import _unit_labels,_compact_core_proof
        from pyz80_compiler.comprehension_lowering import materialize_list_comprehensions
        from test_pyz80_scope_runtime import source_artifact
        artifact=source_artifact('def factory(seed):\n    return {x+seed for x in [1,2]}\n')
        self.assertEqual(artifact.target_coverage['comprehension_lowering']['definitions_by_kind']['set'],1)
        labels,functions=_unit_labels(artifact.document)
        self.assertEqual(list(functions),artifact.compact_document['functions'])
        _compact_core_proof(artifact.document,artifact.compact_document,'m::factory@1',compact_unit_labels=artifact.target_coverage['compact_unit_labels'])
        functions,units=_unit_specs(copy.deepcopy(artifact.document))
        instruction=next(i for u in units for b in u['blocks'] for i in b['instructions'] if i['op']=='run-eager-comprehension')
        instruction['attributes']['plan']['production']['element']['source']='wrong'
        with self.assertRaisesRegex(ValueError,'seal mismatch'):
            materialize_list_comprehensions(functions,units)

    def test_multiline_comprehension_descriptors_keep_ast_identity(self):
        self.check('''seed=1
a={x for x in [1,2,3] if x !=
   seed}
b={x:
   x+seed for x in [1,2] if x !=
   seed}
c=[x for x in [1,2] if x !=
   seed]
set_ok=a=={2,3}
dict_ok=b[2]==3
list_ok=c[0]==2
''')

    def test_growth_failure_and_frozen_mutation_are_atomic(self):
        compile_run(PRELUDE+r'''
int main(void) {
    PyZ80TargetContext context;PyZ80TargetNode nodes[8],before;
    PyZ80TargetField fields[1];PyZ80VMValue items[16],snapshot[16],set,key,ice;
    uint16_t i,used;
    PyZ80Target_Init(&context,nodes,8,fields,1,items,16,0,0,0,0,0,0);
    CHECK(PyZ80Target_SetFrom(&context,0,0,&set));
    for(i=0;i<4;++i) { key=integer(i);CHECK(PyZ80Target_SetAdd(&context,&set,&key)); }
    before=*PyZ80Target_Node(&context,&set);memcpy(snapshot,items,sizeof(items));used=context.item_used;
    context.item_capacity=used;key=integer(4);
    CHECK(!PyZ80Target_SetAdd(&context,&set,&key));
    CHECK(!memcmp(&before,PyZ80Target_Node(&context,&set),sizeof(before)) && !memcmp(snapshot,items,sizeof(items)) && used==context.item_used);
    key=integer(2);CHECK(PyZ80Target_SetAdd(&context,&set,&key));
    context.item_capacity=16;CHECK(PyZ80Target_SetFrom(&context,&set,1,&ice));
    CHECK(!PyZ80Target_SetAdd(&context,&ice,&key) && !PyZ80Target_SetRemove(&context,&ice,&key,1) && !PyZ80Target_SetClear(&context,&ice));
    CHECK(PyZ80Target_SetFind(&context,&ice,&key)==1);
    CHECK(PyZ80Target_SetRemove(&context,&set,&key,0));
    CHECK(PyZ80Target_SetFind(&context,&set,&key)==2 && PyZ80Target_SetFind(&context,&ice,&key)==1);
    return 0;
}
''')

    def test_reverse_insertion_and_removal_keep_search_index(self):
        self.check('''s=set()
for x in range(80,-81,-1):
    s.add(x)
before=len(s)
for x in range(-80,81,2):
    s.remove(x)
after=len(s)
correct=True
for x in range(-81,82):
    expected=-80<=x<=80 and x%2!=0
    if (x in s)!=expected:
        correct=False
s.add(False)
s.add(True)
numeric_keys=len(s)
s.add(None)
s.add('key')
mixed=len(s)
none_present=None in s
string_present='key' in s
''',heap_scale=4,max_slices=60000)


if __name__=='__main__':
    unittest.main()
