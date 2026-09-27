"""min/max и неизменённые функции R-9: Python против C VM с банковым чтением."""
import ast
from pathlib import Path
import unittest

from pyz80_compiler.module_imports import pinned_stdlib_sources
from test_pyz80_callable_runtime import TCC
from test_pyz80_import_runtime import import_check


@unittest.skipUnless(TCC, 'нужен локальный C-компилятор')
class ExtremaRuntimeTests(unittest.TestCase):
    def check(self, source, **options):
        for banked in (False,True):
            with self.subTest(banked=banked):
                import_check({'app':source},banked=banked,generators=True,sorting=True,**options)

    def test_two_scalar_arguments_without_control_sort_provider(self):
        for banked in (False,True):
            import_check({'app':'''low=min(-2147483648,2147483647)
high=max(-2147483648,2147483647)
left_bool=min(True,1) is True
right_bool=max(1,True) is True
low2=min(0,False) is False
high2=max(False,0) is False
'''}, banked=banked)

    def test_positional_and_iterable_forms_keep_first_equal_object(self):
        self.check('''a=min(7,-9,3,12)
b=max(7,-9,3,12)
c=min([True,1]) is True
d=max((1,True)) is True
e=min(range(10,-3,-3))
f=max({7:1,3:2,8:3})
g=min({7:11,3:12,8:9}.values())
h=max(enumerate([8,7,6],4))[1]
i=min([(2,3),(1,7),(1,6)])[1]
j=max((2,3),(1,7),(1,6))[0]
empty=min([],default=41)
empty_none=max((),default=None,key=7)
only=min([None])
''')

    def test_key_called_once_in_input_order_and_default_is_not_transformed(self):
        self.check('''events=0
def key(value):
    global events
    events=events*10+value
    return value%2
a=min([3,2,4,1],key=key)
order1=events
events=0
b=max(2,4,3,1,key=key)
order2=events
events=0
c=min([],key=key,default=99)
order3=events
d=max([],default=98,key=None)
''')

    def test_bound_key_defaults_and_cells_across_gc(self):
        self.check('''class Key:
    def __init__(self, offset):
        self.offset=offset
    def value(self,x,scale=-1,*,bias=3):
        return x*scale+self.offset+bias
def retained():
    obj=Key(7)
    return obj.value
key=retained()
a=min([2,8,3],key=key)
def outer():
    bias=5
    def key(x):
        return x+bias
    return key
b=max([2,8,3],key=outer())
''', classes=True)

    def test_generator_resume_interleaves_with_key(self):
        self.check('''events=0
def values():
    global events
    events=events*10+1
    yield 7
    events=events*10+3
    yield 8
    events=events*10+5
def key(x):
    global events
    events=events*10+2
    return -x
g=values()
a=min(g,key=key)
trace=events
end=next(g,99)
b=max((x*x for x in range(10)),default=-1)
c=min((x for x in ()),default=7)
''')

    def test_exhausted_generator_and_existing_native_iterator(self):
        self.check('''def values():
    yield 7
    yield 2
g=values()
a=min(g)
b=max(g,default=99)
c=min(g,default=None,key=7)
it=iter([9,3,2])
skipped=next(it)
d=max(it)
e=next(it,88)
''')

    def test_key_can_change_global_builtin_without_changing_retained_call(self):
        self.check('''calls=0
def replacement(a,b):
    return 99
def key(x):
    global min,calls
    calls=calls+1
    min=replacement
    return x
a=min([3,1,2],key=key)
b=min(7,8)
''')

    def test_fast_scalar_form_uses_no_heap_or_selection_request(self):
        self.check('before=1\na=min(7,8)\nb=max(-2,-1)\nafter=1',
            c_helpers='static unsigned baseline_nodes,baseline_items;',after_slice='''
if(PyZ80Target_LoadField(&objects,&modules[0],@before@,&value)) {
    if(!baseline_nodes) { baseline_nodes=objects.node_used;baseline_items=objects.item_used; }
    CHECK(objects.node_used==baseline_nodes && objects.item_used==baseline_items);
    for(j=0;j<DEPTH;++j)CHECK(!sort_frames[j].state);
}''')

    def test_generator_error_and_call_overflow_clean_selection_roots(self):
        self.check('''def values():
    yield 7
    [][0]
a=max(values())
''',expect_vm_error=True,after='''
for(j=0;j<DEPTH;++j)CHECK(!sort_frames[j].state && !generator_frames[j].state);
for(j=0;j<DEPTH*7;++j)CHECK(sort_roots[j].kind==PYZ80_VM_VALUE_NONE);''')
        self.check('''def key(x):
    return min([x],key=key)
a=min([1],key=key)
''',max_depth=5,expect_vm_error=True,after='''
CHECK(vm.error==PYZ80_VM_E_CALL_OVERFLOW);
for(j=0;j<DEPTH;++j)CHECK(!sort_frames[j].state);
for(j=0;j<DEPTH*7;++j)CHECK(sort_roots[j].kind==PYZ80_VM_VALUE_NONE);''')

    def test_generated_contract_registers_extrema_and_keeps_limits_explicit(self):
        from generate_pzvt_target_adapters import build_adapter_specs
        from test_pyz80_scope_runtime import source_artifact
        artifact=source_artifact('def f(a):\n    a.extend(())\n    return min(a,key=None,default=max(1,2))\n')
        plan=build_adapter_specs(artifact.adapter_table,artifact.compact_document['constants'],
            artifact.target_coverage['function_id_table'],artifact.target_coverage['function_call_signatures'])
        operations={operation for symbol,operation in plan['builtin_symbols']}
        self.assertTrue({'PYZ80_BUILTIN_MIN','PYZ80_BUILTIN_MAX','PYZ80_BUILTIN_LIST_EXTEND',
                         'PYZ80_KEYWORD_KEY','PYZ80_KEYWORD_DEFAULT'}<=operations)
        contract=plan['container_protocol']
        self.assertFalse(contract['dynamic_call_sites_proved'])
        self.assertIn('no materialized input',contract['extrema_protocol']['storage'])
        self.assertTrue(contract['extrema_protocol']['pending'])
        self.assertIn('source generators',contract['list_extend_protocol']['sources'])

    def test_key_mutation_of_native_input_is_live_not_snapshot(self):
        self.check('''source=[2,3]
calls=0
def key(x):
    global calls
    calls=calls+1
    if calls==1:
        source.append(1)
    return x
a=min(source,key=key)
size=len(source)
''')

    def test_nested_sort_extrema_and_extend_in_key(self):
        self.check('''def values(x):
    yield x
    yield x+1
def key(x):
    a=[]
    a.extend(values(x))
    b=sorted(a,key=lambda value:-value)
    return min(b,key=lambda value:-value)
a=max([2,8,3],key=key)
b=sorted([2,8,3],key=lambda x:max(values(x)))[0]
''', max_slices=40000)

    def test_candidate_budget_one_per_slice(self):
        self.check('it=iter(range(100))\na=max(it)',budget=1,
            c_helpers='static unsigned previous_cursor;',after_slice='''
if(PyZ80Target_LoadField(&objects,&modules[0],@it@,&value)) {
    PyZ80TargetNode *node=PyZ80Target_Node(&objects,&value);
    CHECK(node && node->kind==PYZ80_TARGET_NODE_ITERATOR);
    CHECK(node->cursor>=previous_cursor && node->cursor<=previous_cursor+1);
    previous_cursor=node->cursor;
}''',after='CHECK(previous_cursor==100);')

    def test_invalid_calls_and_unsupported_comparisons_stop_explicitly(self):
        for expression in ('min()', 'max([])', 'min(1,2,default=0)',
                           'max(iterable=[1])', 'min([1],reverse=True)',
                           'max([1],key=7)', 'min(1)', 'max([1,None])',
                           'min(["b","a"])', 'max([1.5,2.0])'):
            with self.subTest(expression=expression):
                self.check('a='+expression,expect_vm_error=True)

    def test_builtin_shadowing_and_default_argument_evaluation(self):
        self.check('''events=0
def fallback():
    global events
    events=events+1
    return 99
a=min([7],default=fallback())
def max(a,b):
    return a+b
b=max(2,3)
''')

    def test_key_error_clears_all_control_roots(self):
        self.check('''def key(x):
    return [][0]
a=min([1,2],key=key)
''',expect_vm_error=True,after='''
for(j=0;j<DEPTH;++j)CHECK(!sort_frames[j].state && !generator_frames[j].state);
for(j=0;j<DEPTH*7;++j)CHECK(sort_roots[j].kind==PYZ80_VM_VALUE_NONE);
for(j=0;j<DEPTH*3;++j)CHECK(generator_roots[j].kind==PYZ80_VM_VALUE_NONE);''')

    def test_unchanged_r9_pitch_and_beam_functions(self):
        path=Path(__file__).resolve().parents[1]/'Python/rtype_port/game.py'
        tree=ast.parse(path.read_text(encoding='utf-8-sig'))
        names={'advance_pitch','beam_native_width','advance_wave_charge'}
        constants={'PITCH_MAX','PITCH_NEUTRAL','WAVE_MAX_CHARGE'}
        selected=[n for n in tree.body if
                  (isinstance(n,ast.FunctionDef) and n.name in names) or
                  (isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in constants for t in n.targets))]
        self.assertEqual(len(selected),6)
        definitions='from __future__ import annotations\n'+ast.unparse(ast.Module(body=selected,type_ignores=[]))
        reference={}
        exec(compile(definitions,str(path),'exec'),reference)
        pitch_expected=[reference['advance_pitch'](p,u,d) for p in range(reference['PITCH_MAX']+1)
                        for u in (False,True) for d in (False,True)]
        charges=range(-4,reference['WAVE_MAX_CHARGE']+5)
        expected={'pitches':pitch_expected,
                  'widths':[reference['beam_native_width'](c) for c in charges],
                  'charges':[reference['advance_wave_charge'](c) for c in charges]}
        checks=[]
        for name,values in expected.items():
            checks.append('{ static const int32_t expected[]={'+','.join(map(str,values))+'};\n'+
                'PyZ80TargetNode *node;CHECK(PyZ80Target_LoadField(&objects,&modules[0],@'+name+'@,&value));\n'+
                'node=PyZ80Target_Node(&objects,&value);CHECK(node && node->item_count=='+str(len(values))+');\n'+
                'for(j=0;j<node->item_count;++j)CHECK(items[node->item_start+j].kind==PYZ80_VM_VALUE_I32 &&\n'+
                'items[node->item_start+j].payload==(uint32_t)expected[j]); }')
        source=definitions+'''
pitches=[]
widths=[]
charges=[]
pitch_digest=0
for pitch in range(PITCH_MAX+1):
    for up in (False,True):
        for down in (False,True):
            value=advance_pitch(pitch,up,down)
            pitches.append(value)
            pitch_digest=pitch_digest+value
beam_digest=0
charge_digest=0
for charge in range(-4,WAVE_MAX_CHARGE+5):
    width=beam_native_width(charge)
    next_charge=advance_wave_charge(charge)
    widths.append(width)
    charges.append(next_charge)
    beam_digest=beam_digest+width
    charge_digest=charge_digest+next_charge
a=beam_native_width(4)
b=beam_native_width(128)
c=advance_wave_charge(127)
'''
        library=pinned_stdlib_sources()['__future__']
        for banked in (False,True):
            import_check({'app':source,'__future__':library.read_text(encoding='utf-8')},
                banked=banked,generators=True,sorting=True,classes=True,heap_scale=4,
                library_paths={'__future__':library},max_slices=100000,after='\n'.join(checks))


if __name__=='__main__':
    unittest.main()
