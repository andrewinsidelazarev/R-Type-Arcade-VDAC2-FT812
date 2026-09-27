"""Original class AST -> generated PZVT/C, differential checks against CPython."""
import unittest
import ast
from pathlib import Path
from pyz80_compiler.module_program import build_module_program
from pyz80_compiler.function_cfg import lower_python_class_cfg, FunctionCFGError
from test_pyz80_module_program import module_check
from test_pyz80_callable_runtime import TCC
from test_pyz80_import_runtime import import_check
from pyz80_compiler.module_imports import pinned_stdlib_sources


def annotation_import_check(source):
    # The very same stdlib source is translated and run by the CPython oracle.
    future = pinned_stdlib_sources()['__future__'].read_text(encoding='utf-8')
    return import_check({'app':source, '__future__':future}, classes=True)


@unittest.skipUnless(TCC, 'host compiler unavailable')
class ClassRuntimeTests(unittest.TestCase):
    def test_unannotated_function_scope_still_evaluates_annotation_target_receivers(self):
        module_check({'m': '''events=0
def event(n):
    global events
    events=events*10+n
    return 0
def f():
    event(1).missing: event(2)
    event(3)[event(4)]: event(5)
    (x): event(6)
    return 7
answer=f()+events
'''})

    def test_only_derived_class_retains_entire_hierarchy_and_super_cell(self):
        module_check({'m': '''def make():
    class A:
        n=7
    class B(A):
        def read(self):
            return super().n
    return B
Derived=make()
instance=Derived()
answer=instance.read()
'''}, classes=True, repetitions=1000)

    def test_list_concatenation_does_not_mutate_or_alias_operand(self):
        module_check({'m': '''a=[1,2]
b=[3]
c=a+b
c[0]=9
a[1]=7
answer=a[0]*100+c[1]*10+c[2]
size=len(c)
'''}, repetitions=1000)

    def test_dictionary_attributes_are_not_dictionary_keys(self):
        for expression in ('value.x=9', 'answer=value.x'):
            with self.subTest(expression=expression):
                module_check({'m': 'value={"x":7}\n'+expression+'\n'}, error=True)

    def test_native_mro_tables_remain_immutable(self):
        module_check({'m': 'class A: pass\nclass B(A): pass\nB.__mro__[1]=B\n'}, classes=True, error=True)
        module_check({'m': 'class A: pass\nclass B(A): pass\nB.__bases__=(object,)\n'}, classes=True, error=True)

    def test_postponed_module_and_class_annotations_match_compiler_strings(self):
        annotation_import_check('''from __future__ import annotations
x: int | None = 3
class A:
    first: tuple [ int, str ] = 7
    second: 'Forward'
    third: missing()
    if False:
        unreachable: list[whatever]
    (not_stored): ignored()
answer=x+A.first
module_annotation=__annotations__['x']
first=A.__annotations__['first']
second=A.__annotations__['second']
third=A.__annotations__['third']
count=len(A.__annotations__)
flag=annotations.compiler_flag
optional=annotations.getOptionalRelease()[0]
mandatory=annotations.getMandatoryRelease()
''')

    def test_annotation_expressions_and_stores_preserve_observable_order(self):
        module_check({'m': '''events=0
def event(n):
    global events
    events=events*10+n
    return n
class A:
    before=len(__annotations__)
    x: event(2) = event(1)
    y: x+event(3)
    (z): event(4)
answer=events
first=A.__annotations__['x']
second=A.__annotations__['y']
count=len(A.__annotations__)
'''} , classes=True)

    def test_annotation_targets_without_assignment_do_not_load_attributes_or_items(self):
        for future in ('', 'from __future__ import annotations\n'):
            with self.subTest(future=bool(future)):
                source = future+'''events=0
def event(n):
    global events
    events=events*10+n
    return 0
class A:
    event(1).missing: event(2)
    event(3)[event(4)]: event(5)
answer=events
size=len(A.__annotations__)
'''
                if future: annotation_import_check(source)
                else: module_check({'m':source}, classes=True)

    def test_annotation_mappings_preserved_and_class_lookup_not_inherited(self):
        module_check({'m': '''__annotations__={'old':9}
x: 3 = 7
class A:
    x: 5 = 1
class B(A): pass
class C(A):
    __annotations__={'old':6}
    y: 8 = 2
first=__annotations__['old']+__annotations__['x']
second=len(B.__annotations__)
third=A.__annotations__['x']
fourth=C.__annotations__['old']+C.__annotations__['y']
'''}, classes=True, repetitions=1000)

    def test_bad_annotation_mapping_fails_after_value_store(self):
        module_check({'m': '''__annotations__=None
x: 5 = 7
after=99
'''}, classes=True, error=True,
            after='CHECK(PyZ80Target_LoadField(&objects,&modules[0],@x@,&value) && value.payload==7);')

    def test_annotation_dictionary_keeps_insertion_order_on_replacement(self):
        module_check({'m': '''class A:
    x: 1
    y: 2
    x: 3
annotations=A.__annotations__
answer=annotations['x']*10+annotations['y']
size=len(annotations)
truth=bool(annotations)
empty=bool({})
'''}, classes=True, repetitions=1000, after='''CHECK(PyZ80Target_LoadField(&objects,&modules[0],@annotations@,&value));
{PyZ80TargetNode *dict=PyZ80Target_Node(&objects,&value);uint16_t link=dict->field_head;
CHECK(dict->kind==PYZ80_TARGET_NODE_DICT && fields[link-1].key==@x@);
link=fields[link-1].next;CHECK(fields[link-1].key==@y@ && !fields[link-1].next);}''')

    def test_c3_diamond_inherited_initializer_and_live_base_mutation(self):
        module_check({'m': '''class A:
    n=7
    def __init__(self, n=5):
        self.value=n
    def read(self):
        return self.n+self.value
class B(A):
    pass
class C(A):
    n=10
class D(B,C):
    pass
d=D(n=3)
first=d.read()
saved=d.read
def replacement(self):
    return self.value+100
A.read=replacement
C.n=20
second=d.read()
third=saved()
answer=first*10000+second*100+third
mro0=D.__mro__[0].__name__
mro2=D.__mro__[2].__name__
mro4=D.__mro__[4].__name__
base=D.__bases__[1].__name__
primary=D.__base__.__name__
count=len(D.__mro__)
'''}, classes=True, repetitions=1000)

    def test_c3_not_depth_first_or_breadth_first(self):
        module_check({'m': '''class O: pass
class A(O): pass
class B(O): pass
class C(O): pass
class D(A,B): pass
class E(B,C): pass
class F(D,E,C): pass
a=F.__mro__[0].__name__
b=F.__mro__[1].__name__
c=F.__mro__[2].__name__
d=F.__mro__[3].__name__
e=F.__mro__[4].__name__
f=F.__mro__[5].__name__
g=F.__mro__[6].__name__
h=F.__mro__[7].__name__
'''}, classes=True)

    def test_base_expressions_and_decorators_evaluate_once_in_order(self):
        module_check({'m': '''events=0
class A: pass
class B: pass
def base(n,value):
    global events
    events=events*10+n
    return value
def decorator(n):
    global events
    events=events*10+n
    def apply(value):
        global events
        events=events*10+5
        return value
    return apply
@decorator(1)
class C(base(2,A),base(3,B)):
    global events
    events=events*10+4
answer=events
'''}, classes=True)

    def test_duplicate_and_inconsistent_bases_fail_after_suite_and_release_roots(self):
        for bases in ('A,A', 'X,Y'):
            with self.subTest(bases=bases):
                module_check({'m': '''counter=0
class A: pass
class B: pass
class X(A,B): pass
class Y(B,A): pass
class Broken(BASES):
    global counter
    counter=1
counter=99
'''.replace('BASES',bases)}, classes=True, error=True, repetitions=1000,
                    after='CHECK(PyZ80Target_LoadField(&objects,&modules[0],@counter@,&value) && value.payload==1);for(j=0;j<36;++j)CHECK(class_roots[j].kind==PYZ80_VM_VALUE_NONE);')

    def test_explicit_object_and_shadowed_object_identity(self):
        module_check({'m': '''class A(object): pass
class B: pass
object=B
class C(object): pass
first=A.__base__.__name__
second=C.__base__.__name__
third=C.__mro__[-1].__name__
'''}, classes=True)

    def test_super_constructor_and_cooperative_diamond(self):
        module_check({'m': '''class A:
    def __init__(self,n):
        self.n=n
    def read(self):
        return self.n
class B(A):
    def __init__(self,n=3):
        super().__init__(n+1)
    def read(self):
        return super().read()*10+2
class C(A):
    def read(self):
        return super().read()*10+3
class D(B,C):
    def read(self):
        return super().read()*10+4
d=D(n=5)
answer=d.read()
owner=d.__class__.__name__
'''}, classes=True, repetitions=1000)

    def test_saved_super_proxy_and_lexical_class_survive_renaming(self):
        module_check({'m': '''class A:
    def f(self):
        return 7
class B(A):
    def proxy(self):
        return super()
    def owner(self):
        return __class__
b=B()
saved=b.proxy()
Original=B
B=A
first=saved.f()
def changed(self):
    return 9
A.f=changed
second=saved.f()
owner=b.owner().__name__
anchor=saved.__thisclass__.__name__
actual=saved.__self_class__.__name__
third=super(Original,b).f()
'''}, classes=True, repetitions=1000)

    def test_class_cell_not_snapshot_and_decorator_replacement_does_not_rebind(self):
        module_check({'m': '''class Replacement: pass
saved=None
def decorate(cls):
    global saved
    saved=cls
    return Replacement
@decorate
class A:
    f=lambda self: __class__
answer=saved().f().__name__
replacement=A.__name__
'''}, classes=True, repetitions=1000)

    def test_super_uses_current_first_parameter_and_shadowed_builtin_is_ordinary_call(self):
        module_check({'m': '''class A:
    def f(self):
        return self.n
class B(A):
    def f(self,other):
        self=other
        return super().f()
b=B()
b.n=1
c=B()
c.n=9
answer=b.f(c)
def super():
    return 23
class C:
    def f(self):
        return super()
shadowed=C().f()
'''}, classes=True)

    def test_class_inventory_is_source_sealed_and_does_not_execute_host_code(self):
        source='raise RuntimeError("not on host")\nclass A:\n    pass\n'
        program=build_module_program({'m':(Path('m.py'),source)})
        self.assertIn('m::A@2',program.artifact.target_coverage['function_id_table'])
        node=ast.parse(source).body[1]
        node.body=[ast.Pass(lineno=4,col_offset=4)]
        # A semantic change (not just line metadata) must invalidate the seal.
        node.name='Changed'
        with self.assertRaisesRegex(FunctionCFGError,'class AST differs'):
            lower_python_class_cfg(node,source_path=Path('m.py'),source_text=source,callable_id='bad',qualname='bad')

    def test_class_namespace_fallback_and_method_globals(self):
        module_check({'m': '''x=20
class A:
    x=x+1
    y=x+2
    def method(self, n=y):
        return x+n+self.x
a=A()
answer=a.method()
class_name=A.__name__
class_doc=A.__doc__
class_module=A.__module__
class_qualname=A.__qualname__
'''}, classes=True)

    def test_initializers_keywords_and_retained_bound_methods(self):
        module_check({'m': '''counter=0
def default():
    global counter
    counter=counter+1
    return [counter]
class A:
    "docs"
    def __init__(self, x, /, *, y=7):
        self.x=x+y
    def step(self, amount=default()):
        amount[0]=amount[0]+1
        self.x=self.x+amount[0]
        return self.x
a=A(3,y=10)
old=a.step
b=A(5)
first=old()
second=b.step()
third=old()
answer=first*10000+second*100+third
doc=A.__doc__
'''}, classes=True, repetitions=1000)

    def test_outer_cells_are_shared_but_class_locals_are_not_captured(self):
        module_check({'m': '''def outer():
    x=10
    class A:
        x=20
        before=x
        def read(self):
            return x
    x=30
    return A
A=outer()
a=A()
answer=a.read()+A.before
'''}, classes=True, repetitions=1000)

    def test_nested_class_is_not_lexically_inside_outer_class(self):
        module_check({'m': '''x=5
class A:
    x=7
    class B:
        x=x+1
        def read(self):
            return x
b=A.B()
answer=A.B.x*10+b.read()
qualname=A.B.__qualname__
'''}, classes=True)

    def test_class_and_function_decorators_execute_in_source_order(self):
        module_check({'m': '''events=0
def decorator(n):
    global events
    events=events*10+n
    def apply(value):
        global events
        events=events*10+n
        return value
    return apply
@decorator(1)
@decorator(2)
class A:
    @decorator(3)
    def method(self, x=4):
        return x
answer=A().method()+events
'''}, classes=True)

    def test_bad_initializer_return_stops_and_unroots_pending_state(self):
        module_check({'m': '''counter=0
class A:
    def __init__(self):
        global counter
        counter=counter+1
        return 3
a=A()
counter=999
'''}, classes=True, error=True, repetitions=1000,
            after='CHECK(PyZ80Target_LoadField(&objects,&modules[0],@counter@,&value) && value.payload==1);for(j=0;j<36;++j)CHECK(class_roots[j].kind==PYZ80_VM_VALUE_NONE);')

    def test_unsupported_descriptor_protocol_is_not_ignored(self):
        module_check({'m': '''class A:
    def __getattr__(self,name):
        return 7
answer=1
'''}, classes=True, error=True)

    def test_load_name_and_class_deref_are_distinct(self):
        module_check({'m': '''x=5
def outer():
    x=10
    class A:
        before=x
        x=20
        def read(self):
            return x
    class B:
        before=x
    return A.before*100+B.before*10+A().read()
answer=outer()
'''}, classes=True)

    def test_class_global_assignment_and_comprehension_scope(self):
        module_check({'m': '''x=5
class A:
    x=7
    values=[x+i for i in range(3)]
    f=lambda self: x
class B:
    global x
    x=x+10
answer=A.values[0]*100+A().f()+x
'''}, classes=True)

    def test_rebound_class_method_does_not_retarget_saved_method(self):
        module_check({'m': '''class A:
    n=7
    def f(self):
        return self.n
a=A()
saved=a.f
def replacement(self):
    return self.n+100
A.f=replacement
A.n=8
first=saved()
a.n=9
second=a.f()
third=getattr(a,'n')
missing=getattr(a,'missing',7)
answer=first*10000+second*100+third+missing
'''}, classes=True, repetitions=1000)

    def test_imports_inside_class_and_initializer_compose_with_loader(self):
        import_check({'app': '''from a import A
a=A(3)
answer=a.read()
''', 'a': '''x=7
class A:
    from b import y
    z=y
    def __init__(self,n):
        import c
        self.n=n+c.y
    def read(self):
        return self.n+x+self.z
''', 'b': 'y=10\n', 'c': 'y=20\n'}, classes=True)

    def test_class_frame_overflow_is_reported_and_cleans_both_protocols(self):
        import_check({'app': 'class A:\n    x=7\n'}, classes=True, max_depth=1, expect_vm_error=True,
            after='CHECK(vm.error==PYZ80_VM_E_CALL_OVERFLOW);CHECK(states[0]==PYZ80_MODULE_EMPTY);for(j=0;j<3;++j)CHECK(class_roots[j].kind==PYZ80_VM_VALUE_NONE);')

    def test_failed_class_import_can_retry_without_stale_namespace_or_frame(self):
        import_check({'app': 'import a\n', 'a': '''import b
class A:
    b.counter=b.counter+1
    broken=missing
''', 'b': 'counter=0\n'}, classes=True, expected_external=1, repetitions=1000,
            after='CHECK(states[$a$]==PYZ80_MODULE_EMPTY);CHECK(PyZ80Target_LoadField(&objects,&modules[$b$],@counter@,&value) && value.payload==i+1u);for(j=0;j<3*DEPTH;++j)CHECK(class_roots[j].kind==PYZ80_VM_VALUE_NONE);')

    def test_inlined_comprehension_captures_outer_cell_not_class_local(self):
        module_check({'m': '''def outer():
    x=5
    class A:
        x=7
        values=[x+i for i in range(3)]
    return A.values[2]
answer=outer()
'''}, classes=True)

    def test_builtin_metadata_does_not_fall_through_to_getattr_default(self):
        module_check({'m': 'class A:\n    pass\nanswer=getattr(A,"__dict__",7)\n'}, classes=True, error=True)
        module_check({'m': 'class A:\n    __qualname__=7\nanswer=1\n'}, classes=True, error=True)

    def test_private_method_is_blocked_until_real_name_mangling(self):
        program=build_module_program({'m':(Path('m.py'),'class A:\n    def __f(self):\n        return 7\n')})
        self.assertTrue(any(b['code']=='PZFC214' for b in program.graph['callable_inventory']['callables'][0]['cfg']['blockers']))

    def test_class_storage_validation_and_gc_failure_cleanup(self):
        import_check({'app':'class A:\n    pass\n'}, classes=True, expect_vm_error=True,
            after_attach='''CHECK(!PyZ80Target_AttachClasses(&classes,&scopes,class_frames,class_roots,0,class_routes));
CHECK(!PyZ80Target_AttachClasses(&classes,&scopes,class_frames,(PyZ80VMValue*)class_frames,DEPTH,class_routes));
CHECK(!PyZ80Target_AttachClasses(&classes,&scopes,class_frames,class_roots,DEPTH,(uint16_t*)imports.hooks.routes));
CHECK(vm.control_hooks==&imports.hooks && !objects.class_provider);''',
            before_slice='class_roots[0].kind=PYZ80_VM_VALUE_OPAQUE;class_roots[0].payload=0;',
            after='CHECK(vm.error==PYZ80_VM_E_HEAP_ROOTS);CHECK(states[0]==PYZ80_MODULE_EMPTY);for(j=0;j<3*DEPTH;++j)CHECK(class_roots[j].kind==PYZ80_VM_VALUE_NONE);')

    def test_cyclic_control_roots_fail_without_recursive_failure_callback(self):
        import_check({'app':'class A:\n    pass\n'}, classes=True, expect_vm_error=True,
            before_slice='classes.hooks.previous=&classes.hooks;',
            after='CHECK(vm.error==PYZ80_VM_E_HEAP_ROOTS);classes.hooks.previous=&imports.hooks;')


if __name__ == '__main__':
    unittest.main()
