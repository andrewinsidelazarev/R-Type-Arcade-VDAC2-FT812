"""Словари: исходный Python -> PZVT -> C, без подмены игровых таблиц."""
import ast
from pathlib import Path
import unittest

from pyz80_compiler.module_imports import pinned_stdlib_sources
from test_pyz80_callable_runtime import PRELUDE, TCC, compile_run
from test_pyz80_import_runtime import import_check


@unittest.skipUnless(TCC, 'нужен локальный C-компилятор')
class DictRuntimeTests(unittest.TestCase):
    def check(self, source, **options):
        for banked in (False, True):
            with self.subTest(banked=banked):
                import_check({'app':source}, banked=banked, **options)

    def test_scalar_keys_aliases_order_and_get(self):
        self.check('''d={True:7, 0:8, None:9, 'one':10, -2147483648:11, 2147483647:12}
d[1]=17
d[False]=18
d['one']=20
order=[key for key in d]
first_is_true=order[0] is True
second=order[1]
third_is_none=order[2] is None
fourth=order[3]
fifth=order[4]
sixth=order[5]
size=len(d)
answer=d[True]+d[0]+d[None]+d['one']+d[-2147483648]+d[2147483647]
present=1 in d
missing=4 not in d
not_present='missing' in d
default=d.get('absent',31)
none_default=d.get('absent')
existing=d.get(False,99)
truth=bool(d)
''')

    def test_promotion_preserves_existing_fields_and_overwrite_order(self):
        self.check('''d={'x':3,'y':4}
d[2]=5
d['x']=13
d[None]=6
order=[key for key in d]
first=order[0]
second=order[1]
third=order[2]
fourth=order[3]
answer=d['x']+d.get('y')+d[2]+d[None]
size=len(d)
''')

    def test_get_is_bound_to_original_owner_and_not_a_global_builtin(self):
        self.check('''def factory():
    d={3:7,'x':9}
    return d.get
saved=factory()
other={3:70}
answer=0
for i in range(100):
    garbage={i:i+1}
    answer=answer+saved(3)+saved('x')+saved(8,2)
''',max_slices=30000)
        self.check("d={1:2}\nf=d.get\nget(1)\n",expect_vm_error=True,expected_external=1)

    def test_values_remain_live_after_relocation_and_cycles(self):
        self.check('''class Item:
    def __init__(self,x):
        self.x=x
d={'item':Item(7)}
d[None]=d
for i in range(70):
    d[i]=Item(i+10)
    garbage=[i,i+1]
answer=d['item'].x+d[69].x
cycle=d[None] is d
size=len(d)
''',classes=True,heap_scale=2,max_slices=30000)

    def test_literal_evaluation_order_and_duplicate_first_key_identity(self):
        self.check('''events=0
def step(n):
    global events
    events=events*10+n
    return n
d={step(1):step(2),step(3):step(4),True:step(5)}
order=[key for key in d]
first_is_true=order[0] is True
first=order[0]
second=order[1]
answer=d[True]*100+d[3]+events
size=len(d)
''')

    def test_dict_comprehension_keeps_key_value_order_scope_and_duplicates(self):
        self.check('''events=0
x=99
def key(x):
    global events
    events=events*10+x
    return x
def value(x):
    global events
    events=events*10+x+1
    return x+10
def make(seed):
    return {key(x):value(x)+seed for x in [1,2,1] if x}
d=make(3)
order=[k for k in d]
first=order[0]
second=order[1]
answer=d[1]*100+d[2]
unchanged=x
size=len(d)
''')

    def test_nested_dict_loops_and_key_seal_reconstruction(self):
        self.check('''seed=7
d={x*10+y:seed+x+y for x in [1,2] for y in [2,3] if y==2}
keys=[key for key in d]
first=keys[0]
second=keys[1]
answer=d[12]+d[22]
empty={key:key for key in []}
empty_size=len(empty)
''')
        import copy
        from test_pyz80_scope_runtime import source_artifact
        from pyz80_compiler.whole_program_vm_backend import _unit_specs
        from pyz80_compiler.comprehension_lowering import materialize_list_comprehensions
        from pyz80_compiler.whole_program_vm_stack_bound import _unit_labels, _compact_core_proof
        artifact=source_artifact('def make(seed):\n    return {x:x+seed for x in [1,2]}\n')
        self.assertEqual(artifact.target_coverage['comprehension_lowering']['definitions_by_kind']['dict'],1)
        labels,functions=_unit_labels(artifact.document)
        self.assertEqual(list(functions),artifact.compact_document['functions'])
        _compact_core_proof(artifact.document,artifact.compact_document,artifact.target_coverage['function_id_table'][0],compact_unit_labels=artifact.target_coverage['compact_unit_labels'])
        for field in ('key','value'):
            functions,units=_unit_specs(copy.deepcopy(artifact.document))
            item=next(i for u in units for b in u['blocks'] for i in b['instructions'] if i['op']=='run-eager-comprehension')
            item['attributes']['plan']['production'][field]['source']='unrelated'
            with self.assertRaisesRegex(ValueError,'seal mismatch'):
                materialize_list_comprehensions(functions,units)

    def test_signed_literal_is_folded_but_runtime_operand_is_not(self):
        self.check('''events=0
def value():
    global events
    events=events+1
    return 7
minimum=-2147483648
other=-value()
d={minimum:other}
answer=d[minimum]
''')
        from test_pyz80_scope_runtime import source_artifact
        artifact=source_artifact('def make():\n    return -2147483648\n')
        self.assertIn(-2147483648,artifact.compact_document['constants'])
        self.assertNotIn(2147483648,artifact.compact_document['constants'])
        self.assertNotIn('python-unary',[row['op'] for row in artifact.adapter_table])

    def test_iteration_allows_value_changes_but_rejects_size_changes(self):
        self.check('''d={1:10,2:20,3:30}
answer=0
for key in d:
    d[key]=d[key]+1
    answer=answer*10+key
value=d[3]
''')
        self.check('''d={'first':1,'second':2}
for key in d:
    d[99]=7
''',expect_vm_error=True)

    def test_unsupported_or_unhashable_keys_and_invalid_get_calls_fail_closed(self):
        for expr in ('d[[]]=7','d.get([])','[] in d','d[(1,2)]=7','d[1.5]=7',
                     'd.get()','d.get(1,2,3)','d.get(key=1)','d.missing', 'd.get=7', 'd[99]'):
            with self.subTest(expr=expr):
                self.check('d={1:2}\n'+expr+'\n',expect_vm_error=True)

    def test_active_stage_tables_execute_without_editing_their_source(self):
        path=Path(__file__).resolve().parents[1]/'Python/rtype_port/enemies.py'
        text=path.read_text(encoding='utf-8')
        names={'STAGE_EVENT_RANGES','STAGE1_CHECKPOINT_SLOT_RESIDUE'}
        statements=[]
        for node in ast.parse(text).body:
            targets=node.targets if isinstance(node,ast.Assign) else [node.target] if isinstance(node,ast.AnnAssign) else []
            if any(isinstance(t,ast.Name) and t.id in names for t in targets):
                statements.append(ast.get_source_segment(text,node))
        self.assertEqual(len(statements),2)
        source='from __future__ import annotations\n'+'\n'.join(statements)+'''
checksum=0
for stage in STAGE_EVENT_RANGES:
    row=STAGE_EVENT_RANGES[stage]
    checksum=checksum+(row[1]-row[0])
stage_count=len(STAGE_EVENT_RANGES)
last_start=STAGE_EVENT_RANGES[8][0]
residue=STAGE1_CHECKPOINT_SLOT_RESIDUE.get(0x0640)
first_fraction=residue[0]
unknown=STAGE1_CHECKPOINT_SLOT_RESIDUE.get(0x9999, (7,8))[1]
'''
        future=pinned_stdlib_sources()['__future__'].read_text(encoding='utf-8')
        for banked in (False,True):
            import_check({'app':source,'__future__':future},classes=True,banked=banked,max_args=64)

    def test_capacity_failures_and_exhausted_iterators_are_stable(self):
        compile_run(PRELUDE+r'''
int main(void) {
    PyZ80TargetContext context;PyZ80TargetNode nodes[8],saved;
    PyZ80TargetField fields[8];PyZ80VMValue items[64],snapshot[64],d,k,v,result,iterator;
    PyZ80TargetAdapterSpec specs[]={{PYZ80_TARGET_GET_ITERATOR,1,0},{PYZ80_TARGET_ITER_NEXT,1,0},
        {PYZ80_TARGET_ITER_HAS_VALUE,1,0},{PYZ80_TARGET_ITER_VALUE,1,0}};
    uint16_t before;
    PyZ80Target_Init(&context,nodes,8,fields,8,items,64,specs,4,0,0,0,0);
    CHECK(PyZ80Target_AllocateNode(&context,PYZ80_TARGET_NODE_DICT,65535,&d));
    k=integer(1);k.kind=PYZ80_VM_VALUE_SYMBOL;k.symbol=7;v=integer(10);
    CHECK(PyZ80Target_DictStore(&context,&d,&k,&v));
    saved=nodes[0];memcpy(snapshot,items,sizeof(items));context.item_capacity=0;k=integer(2);
    CHECK(!PyZ80Target_DictStore(&context,&d,&k,&v));
    CHECK(!memcmp(&saved,&nodes[0],sizeof(saved)) && !memcmp(snapshot,items,sizeof(items)));
    context.item_capacity=64;CHECK(PyZ80Target_DictStore(&context,&d,&k,&v));
    saved=nodes[0];before=context.item_used;memcpy(snapshot,items,sizeof(items));
    nodes[0].source_link=nodes[0].item_count;context.item_capacity=context.item_used;k=integer(3);
    saved=nodes[0];CHECK(!PyZ80Target_DictStore(&context,&d,&k,&v));
    CHECK(context.item_used==before && !memcmp(&saved,&nodes[0],sizeof(saved)) && !memcmp(snapshot,items,sizeof(items)));
    context.item_capacity=64;
    CHECK(PyZ80Target_Invoke(&context,0,0,0,&d,1,0,&iterator));
    CHECK(PyZ80Target_Invoke(&context,0,1,0,&iterator,1,0,&result));
    CHECK(PyZ80Target_Invoke(&context,0,1,0,&iterator,1,0,&result));
    CHECK(PyZ80Target_Invoke(&context,0,1,0,&iterator,1,0,&result));
    CHECK(PyZ80Target_Invoke(&context,0,2,0,&iterator,1,0,&result) && result.payload==0);
    CHECK(PyZ80Target_DictStore(&context,&d,&k,&v));
    CHECK(PyZ80Target_Invoke(&context,0,1,0,&iterator,1,0,&result));
    CHECK(PyZ80Target_Invoke(&context,0,2,0,&iterator,1,0,&result) && result.payload==0);
    return 0;
}
''')


if __name__=='__main__':unittest.main()
