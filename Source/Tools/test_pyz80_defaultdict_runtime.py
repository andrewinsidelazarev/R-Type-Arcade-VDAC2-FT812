"""Фабрики отсутствующих ключей: исходный Python против пошагового C runtime."""
from pathlib import Path
import ast
import unittest

from pyz80_compiler.collections_provider import source_path
from test_pyz80_callable_runtime import TCC
from test_pyz80_import_runtime import import_check


class DefaultDictContractTests(unittest.TestCase):
    def test_mapping_methods_use_dict_receiver_operations(self):
        from generate_pzvt_target_adapters import container_protocol
        names=('get','pop','clear','keys','values','items','__missing__')
        report=container_protocol({name:i for i,name in enumerate(names)})
        methods={row['name']:row['operation'] for row in report['registered_methods'] if row['receiver']=='defaultdict'}
        self.assertEqual(methods,{name:'PYZ80_BUILTIN_DICT_'+name.upper() for name in names[:-1]} |
                         {'__missing__':'PYZ80_BUILTIN_DEFAULTDICT_MISSING'})
        self.assertFalse(report['dynamic_call_sites_proved'])


@unittest.skipUnless(TCC,'нужен локальный C-компилятор')
class DefaultDictTests(unittest.TestCase):
    def check(self, source, *, extra_modules=None, **options):
        library=source_path()
        sources={'app':source,'collections':library.read_text(encoding='utf-8')}
        sources.update(extra_modules or {})
        libraries={'collections':library}
        if 'from __future__ import annotations' in source:
            future=library.parent.parent/'__future__.py'
            sources['__future__']=future.read_text(encoding='utf-8')
            libraries['__future__']=future
        for banked in (False,True):
            with self.subTest(banked=banked):
                import_check(sources,
                    library_paths=libraries,skip_oracle_modules=('collections',),
                    generators=True,defaultdicts=True,banked=banked,**options)

    def test_missing_list_factory_and_get_does_not_insert(self):
        self.check('''from collections import defaultdict
events=defaultdict(list)
before=len(events)
missing=events.get(7)
not_inserted=len(events)
events[3].append(9)
same=events[3] is events[3]
events[7].append(11)
value=events[3][0]
other=events[7][0]
size=len(events)
''')

    def test_empty_native_factories_and_type_identity(self):
        self.check('''import collections
from collections import defaultdict, deque
d=defaultdict(int)
zero=d[1]
b=defaultdict(bool)
false=b[2]
types=(list,dict,set,frozenset,deque,defaultdict)
empty_count=0
for factory in types:
    m=defaultdict(factory)
    empty_count+=len(m[1])==0
    empty_count+=m[1] is m[1]
same=defaultdict is collections.defaultdict
different=defaultdict is not dict
is_mapping=isinstance(d,dict)
is_default=isinstance(d,defaultdict)
plain_is_not=not isinstance({},defaultdict)
sub=issubclass(defaultdict,dict)
not_sub=not issubclass(dict,defaultdict)
value=hasattr(d,'default_factory')
''',classes=True)

    def test_mapping_operations_do_not_invoke_factory(self):
        self.check('''from collections import defaultdict
calls=[]
def factory():
    calls.append(1)
    return 99
d=defaultdict(factory,{'first':3,'second':5},third=7)
before=len(calls)
absent=d.get('missing',17)
present='first' in d
missing='missing' not in d
popped=d.pop('first')
fallback=d.pop('absent',19)
del d['second']
values=list(d.values())
remaining=values[0]
size=len(d)
d.clear()
empty=not d
after=len(calls)
factory_same=d.default_factory is factory
''')

    def test_initial_mapping_is_shallow_and_keyword_factory_is_a_key(self):
        self.check('''from collections import defaultdict
child=[3]
original=defaultdict(list,{'child':child,'a':1})
copy=defaultdict(None,original,a=7,z=9)
child[0]=11
shallow=copy['child'] is original['child']
value=copy['child'][0]
original_a=original['a']
new_a=copy['a']
keys=tuple(copy)
key0=keys[0]
key1=keys[1]
key2=keys[2]
keyword=defaultdict(default_factory=list)
factory_is_none=keyword.default_factory is None
key_is_list=keyword['default_factory'] is list
''')

    def test_source_closure_default_argument_and_nested_factory(self):
        self.check('''from collections import defaultdict
calls=[]
def make(seed):
    def factory(extra=3):
        calls.append(seed)
        return [seed+extra]
    return factory
inner=defaultdict(make(7))
def outer_factory():
    return inner[11]
outer=defaultdict(outer_factory)
value=outer[9][0]
same=outer[9] is inner[11]
called=len(calls)
seed=calls[0]
''')

    def test_bound_source_method_and_native_method_factory(self):
        self.check('''from collections import defaultdict,deque
class Factory:
    def __init__(self):
        self.calls=0
    def create(self):
        self.calls+=1
        return [self.calls]
owner=Factory()
d=defaultdict(owner.create)
first=d[1][0]
second=d[2][0]
calls=owner.calls
q=deque([17,19])
t=defaultdict(q.popleft)
q=None
native_first=t[0]
native_second=t[1]
''',classes=True)

    def test_key_evaluated_once_and_factory_rebinding_does_not_change_target(self):
        self.check('''from collections import defaultdict
events=[]
def key():
    events.append(3)
    return 7
def factory():
    global d
    events.append(5)
    d[7]=11
    d.default_factory=list
    d=defaultdict(int)
    return 13
d=defaultdict(factory)
original=d
value=d[key()]
inserted=original[7]
new_size=len(d)
changed=original.default_factory is list
event_count=len(events)
event0=events[0]
event1=events[1]
''')

    def test_explicit_missing_always_calls_factory_and_setter_accepts_any_value(self):
        self.check('''from collections import defaultdict
calls=[]
def factory():
    calls.append(1)
    return len(calls)
d=defaultdict(factory)
first=d[3]
second=d.__missing__(3)
stored=d[3]
count=len(calls)
d.default_factory=17
saved=d.default_factory
existing=d[3]
absent=d.get(4)
d.default_factory=None
changed=d.default_factory is None
''')

    def test_source_generator_factory_is_lazy(self):
        self.check('''from collections import defaultdict
events=[]
def factory():
    events.append(1)
    yield 17
    events.append(2)
    yield 19
d=defaultdict(factory)
g=d[4]
before=len(events)
same=d[4] is g
first=next(g)
mid=len(events)
second=next(g)
end=next(g,99)
after=len(events)
''')

    def test_views_iteration_and_value_updates(self):
        self.check('''from collections import defaultdict
d=defaultdict(list,{3:11,5:13,7:17})
keys=d.keys()
values=d.values()
pairs=d.items()
it=iter(values)
first=next(it)
d[5]=19
second=next(it)
back=tuple(reversed(keys))
last_key=back[0]
first_key=back[-1]
entries=tuple(pairs)
pair_key=entries[1][0]
pair_value=entries[1][1]
keyset=set(d)
contains=5 in keyset
size=len(keyset)
d[9]=23
live_size=len(keys)
''')

    def test_iterator_alone_retains_factory_closure(self):
        self.check('''from collections import defaultdict
def create():
    child=[37]
    def factory():
        return child
    d=defaultdict(factory,{7:3})
    return iter(d.items())
it=create()
pair=next(it)
key=pair[0]
value=pair[1]
end=next(it,99)
''',after=r'''
        { PyZ80VMValue it,owner,*parts,factory,prototype,receiver;
          PyZ80TargetNode *n;
          CHECK(PyZ80Target_LoadField(&objects,&modules[$app$],@it@,&it));
          n=PyZ80Target_Node(&objects,&it);
          owner=it;owner.payload=((uint32_t)n->source_generation<<16)|n->source_link;
          CHECK(PyZ80Target_DefaultDictParts(&objects,PyZ80Target_Node(&objects,&owner),&parts));
          factory=parts[1];
          CHECK(PyZ80Target_UnwrapCallable(&objects,&factory,&prototype,&receiver));
        }
''')

    def test_invalid_factories_and_signatures_fail_closed(self):
        for expression in ('defaultdict(7)','defaultdict(list,{},3)','d[7]',
                           'd.__missing__()', 'd.__missing__(key=7)',
                           'defaultdict(list,[(3,4)])', 'd.update({1:2})',
                           'defaultdict(tuple)[3]', 'defaultdict(str)[3]'):
            with self.subTest(expression=expression):
                self.check('from collections import defaultdict\nd=defaultdict()\n'+expression+'\n',
                           expect_vm_error=True)

    def test_invalid_setter_errors_only_at_missing_access(self):
        self.check('''from collections import defaultdict
import saved
d=defaultdict(list)
saved.d=d
d.default_factory=13
d[1]=7
saved.before=d[1]
missing=d[2]
''',extra_modules={'saved':'before=None\nd=None\n'},expect_vm_error=True,after=r'''
        CHECK(PyZ80Target_LoadField(&objects,&modules[$saved$],@before@,&value));CHECK(value.payload==7u);
        CHECK(PyZ80Target_LoadField(&objects,&modules[$saved$],@d@,&value));
        CHECK(PyZ80Target_Length(&objects,&value,&step_count));CHECK(step_count==1u);
''')

    def test_failed_source_factory_retains_side_effect_but_not_missing_key(self):
        self.check('''from collections import defaultdict
import saved
def factory():
    saved.events.append(19)
    return {}[3]
d=defaultdict(factory)
saved.d=d
value=d[3]
''',extra_modules={'saved':'d=None\nevents=[]\n'},expect_vm_error=True,after=r'''
        CHECK(PyZ80Target_LoadField(&objects,&modules[$saved$],@events@,&value));
        CHECK(PyZ80Target_Length(&objects,&value,&step_count));CHECK(step_count==1u);
        CHECK(PyZ80Target_LoadField(&objects,&modules[$saved$],@d@,&value));
        CHECK(PyZ80Target_Length(&objects,&value,&step_count));CHECK(step_count==0u);
        for(j=0;j<DEPTH;++j)CHECK(default_frames[j].phase==0u);
        for(j=0;j<4*DEPTH;++j)CHECK(default_roots[j].kind==PYZ80_VM_VALUE_NONE);
''')

    def test_key_mutation_invalidates_active_iterator(self):
        self.check('''from collections import defaultdict
d=defaultdict(list,{1:3,2:5})
it=iter(d)
first=next(it)
d[3]
next(it)
''',expect_vm_error=True)

    def test_attach_rejects_overlaps_and_short_storage(self):
        self.check('answer=1\n',before_defaultdict=r'''
CHECK(!PyZ80Target_AttachDefaultDict(&defaults,&scopes,default_frames,default_roots,0,default_routes));
CHECK(!PyZ80Target_AttachDefaultDict(&defaults,&scopes,default_frames,(PyZ80VMValue*)default_frames,DEPTH,default_routes));
CHECK(!PyZ80Target_AttachDefaultDict(&defaults,&scopes,default_frames,default_roots,DEPTH,(uint16_t*)generator_roots));
CHECK(!PyZ80Target_AttachDefaultDict(&defaults,&scopes,(PyZ80TargetDefaultDictFrame*)vm.locals,default_roots,DEPTH,default_routes));
''')

    def test_gc_rejects_corrupted_mapping_owner(self):
        for damage in ('node->item_count=1u;', 'parts[0]=value;',
                       'node->item_start=objects.item_used;', 'parts[0].payload^=0x10000UL;'):
            with self.subTest(damage=damage):
                self.check('from collections import defaultdict\nd=defaultdict(list)\nphase=1\nx=d[1]\n',
                    expect_vm_error=True,c_helpers='static unsigned damaged;',after_slice=r'''
if(!damaged && PyZ80Target_LoadField(&objects,&modules[$app$],@phase@,&value)) {
    PyZ80TargetNode *node;PyZ80VMValue *parts;
    CHECK(PyZ80Target_LoadField(&objects,&modules[$app$],@d@,&value));
    node=PyZ80Target_Node(&objects,&value);
    CHECK(PyZ80Target_DefaultDictParts(&objects,node,&parts));
    '''+damage+r'''
    damaged=1;
}
''',after='CHECK(damaged==1);CHECK(vm.error==PYZ80_VM_E_HEAP_ROOTS);')

    def test_constructor_copy_takes_one_item_per_vm_step(self):
        self.check('''from collections import defaultdict
source={i:i+3 for i in range(60)}
d=defaultdict(list,source)
first=d[0]
last=d[59]
size=len(d)
''',heap_scale=2,max_slices=30000,c_helpers='static unsigned copied,last_count;',after_slice=r'''
for(j=0;j<DEPTH;++j)if(default_frames[j].phase==1u) {
    uint32_t length;
    CHECK(PyZ80Target_Length(&objects,&default_roots[j*4],&length));
    CHECK(length>=last_count && length<=last_count+1u);
    last_count=(unsigned)length;++copied;
}
''',after='CHECK(last_count==60u && copied>=60u);')

    def test_nested_generator_consumer_and_sort_callbacks(self):
        self.check('''from collections import defaultdict
events=[]
def source():
    for i in range(3):
        events.append(i)
        yield i
def key(value):
    return -value
def factory():
    return sorted(list(source()),key=key)
d=defaultdict(factory)
first=d[1][0]
last=d[1][-1]
calls=len(events)
''',sorting=True,sequences=True)

    def test_recursive_factory_obeys_vm_call_depth(self):
        self.check('''from collections import defaultdict
import saved
def factory():
    return d[1]
d=defaultdict(factory)
saved.d=d
x=d[1]
''',extra_modules={'saved':'d=None\n'},max_depth=4,expect_vm_error=True,after=r'''
CHECK(vm.error==PYZ80_VM_E_CALL_OVERFLOW);
CHECK(PyZ80Target_LoadField(&objects,&modules[$saved$],@d@,&value));
CHECK(PyZ80Target_Length(&objects,&value,&step_count));CHECK(step_count==0u);
for(j=0;j<DEPTH;++j)CHECK(!default_frames[j].phase);
for(j=0;j<4*DEPTH;++j)CHECK(default_roots[j].kind==PYZ80_VM_VALUE_NONE);
''')

    def test_insert_failure_does_not_publish_factory_result(self):
        self.check('''from collections import defaultdict
import saved
def factory():
    saved.events.append(19)
    return 27
d=defaultdict(factory)
saved.d=d
phase=1
x=d[3]
''',extra_modules={'saved':'d=None\nevents=[]\n'},expect_vm_error=True,
            c_helpers='static unsigned injected;',after_slice=r'''
if(!injected && PyZ80Target_LoadField(&objects,&modules[$app$],@phase@,&value)) {
    PyZ80VMValue mapping;
    CHECK(PyZ80Target_LoadField(&objects,&modules[$app$],@d@,&value));
    CHECK(PyZ80Target_Mapping(&objects,&value,&mapping));
    PyZ80Target_Node(&objects,&mapping)->current.payload=0xFFFFFFFFUL;
    injected=1;
}
''',after=r'''
CHECK(injected==1u);
CHECK(PyZ80Target_LoadField(&objects,&modules[$saved$],@d@,&value));
CHECK(PyZ80Target_Length(&objects,&value,&step_count));CHECK(step_count==0u);
CHECK(PyZ80Target_LoadField(&objects,&modules[$saved$],@events@,&value));
CHECK(PyZ80Target_Length(&objects,&value,&step_count));CHECK(step_count==1u);
for(j=0;j<4*DEPTH;++j)CHECK(default_roots[j].kind==PYZ80_VM_VALUE_NONE);
''')

    def test_type_identity_survives_alias_and_source_shadowing(self):
        self.check('''import collections
from collections import defaultdict as Mapping
d=Mapping(list)
def defaultdict():
    return 19
local=defaultdict()
collections.defaultdict=defaultdict
from collections import defaultdict as changed
changed_result=changed()
d[3].append(17)
original=d[3][0]
same=d.default_factory is list
''')
        self.check('import collections\nx=defaultdict()\n',expect_vm_error=True,expected_external=1)
        for banked in (False,True):
            import_check({'app':'from collections import defaultdict\nx=defaultdict(7)\n',
                          'collections':'def defaultdict(value):\n    return value+5\n'},banked=banked)

    @staticmethod
    def decoder_source():
        path=Path(__file__).resolve().parents[1]/'Python/rtype_port/tsfm.py'
        source=path.read_text(encoding='utf-8-sig')
        tree=ast.parse(source)
        names={'PAGE_SIZE','PAGE_MARKER','END_MARKER','LOOP_MARKER'}
        selected=[n for n in tree.body if
            (isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in names for t in n.targets)) or
            (isinstance(n,ast.FunctionDef) and n.name=='decode_stream')]
        assert len(selected)==5
        # Строки тела и константы исходника копируются дословно, без собственной версии декодера.
        lines=source.splitlines(keepends=True)
        return 'from __future__ import annotations\nfrom collections import defaultdict\n'+''.join(
            ''.join(lines[n.lineno-1:n.end_lineno])+'\n' for n in selected)

    def test_unchanged_tsfm_decoder_registers_and_frame_order(self):
        prefix=self.decoder_source()
        oracle={}
        exec(compile(prefix,'tsfm.py#decode_stream','exec',dont_inherit=True),oracle)
        fixtures=([255,0], [7,0,255,0],
                  [0,2,0,46,0,1,40,2,3,1,1,39,17,0,1,0,39,19,255,0],
                  [1,1,0,160,5,250,1,1,164,7,2,0,255,0])
        for data in fixtures:
            with self.subTest(data=data):
                # В C пока проверяется список байтовых значений, не протокол bytes/файлового ввода.
                expected,frames=oracle['decode_stream'](bytes(data))
                self.assertEqual((expected,frames),oracle['decode_stream'](data))
                source=prefix+f'events,frames=decode_stream({data!r})\nsize=len(events)\nkeys=tuple(events)\n'
                for index,(frame,writes) in enumerate(expected.items()):
                    source+=f'frame_{index}=keys[{index}]\ncount_{index}=len(events[{frame}])\n'
                    for row,write in enumerate(writes):
                        for col in range(3):
                            source+=f'v_{index}_{row}_{col}=events[{frame}][{row}][{col}]\n'
                self.check(source,classes=True,sequences=True,max_args=32,max_slices=30000)

    def test_unchanged_tsfm_page_jump_at_real_16kb_boundary(self):
        source=self.decoder_source()+'''data=[0]*(PAGE_SIZE+7)
data[0]=PAGE_MARKER
data[PAGE_SIZE]=3
data[PAGE_SIZE+1]=1
data[PAGE_SIZE+2]=1
data[PAGE_SIZE+3]=40
data[PAGE_SIZE+4]=19
data[PAGE_SIZE+5]=END_MARKER
events,frames=decode_stream(data)
size=len(events)
chip=events[3][0][0]
register=events[3][0][1]
value=events[3][0][2]
'''
        self.check(source,classes=True,sequences=True,heap_scale=40,budget=128,max_slices=2000)


if __name__=='__main__':
    unittest.main()
