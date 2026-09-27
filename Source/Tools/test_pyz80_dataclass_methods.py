"""Pinned CPython generator -> unmodified Python AST -> native C runtime."""
import ast
import dataclasses as dc
import hashlib
from pathlib import Path
import textwrap
import unittest

from pyz80_compiler.dataclass_methods import InitField, capture_init_factory
from pyz80_compiler.module_program import build_module_program
from test_pyz80_callable_runtime import TCC
from test_pyz80_module_program import module_check
from test_pyz80_class_runtime import annotation_import_check


def call_factory(plan, bindings):
    return '__create_fn__(' + ','.join(bindings[kind, field] for _, kind, field in plan.bindings) + ')'


class DataclassGeneratorTests(unittest.TestCase):
    def test_stdlib_code_and_generated_text_are_sealed(self):
        plan = capture_init_factory((InitField('a'), InitField('b', default='value')), has_post_init=True)
        self.assertEqual(plan.stdlib_sha256, hashlib.sha256(plan.stdlib_path.read_bytes()).hexdigest())
        self.assertIn('self.__post_init__()', plan.source)
        self.assertIn('self.b=b', plan.source)
        self.assertIn(('__dataclass_dflt_b__', 'default', 'b'), plan.bindings)
        program = build_module_program({'m': (Path('m.py'), plan.source)})
        self.assertFalse([b for r in program.graph['callable_inventory']['callables'] for b in r['cfg']['blockers']])
        self.assertEqual(len(program.initializer_functions), 1)

    def test_host_generated_constructor_matches_dataclass_code_without_patching_stdlib(self):
        original = dc._create_fn
        for frozen in (False, True):
            for slots in (False, True):
                for kw_only in (False, True):
                    with self.subTest(frozen=frozen, slots=slots, kw_only=kw_only):
                        schema = (InitField('a'), InitField('b', kw_only=kw_only, default='value'),
                                  InitField('items', default='factory'),
                                  InitField('extra', init=False, default='factory'))
                        ref = dc.make_dataclass('Record', [('a', 41), ('b', 42, dc.field(default=7, kw_only=kw_only)),
                            ('items', 43, dc.field(default_factory=list)), ('extra', 44, dc.field(init=False, default_factory=list))],
                            frozen=frozen, slots=slots)
                        plan = capture_init_factory(schema, frozen=frozen, slots=slots)
                        ns = {}
                        exec(compile(plan.source, '<generated>', 'exec', dont_inherit=True), ns)
                        values = {('annotation', name): 41+i for i, name in enumerate(('a', 'b', 'items', 'extra'))}
                        values.update({('default', 'b'): 7, ('factory', 'items'): list, ('factory', 'extra'): list,
                            ('factory-sentinel', None): dc._HAS_DEFAULT_FACTORY, ('builtin-object', None): object, ('none', None): None})
                        fn = ns['__create_fn__'](*(values[kind, field] for _, kind, field in plan.bindings))
                        self.assertEqual(fn.__code__.co_code, ref.__init__.__code__.co_code)
                        self.assertEqual(fn.__code__.co_consts, ref.__init__.__code__.co_consts)
                        self.assertEqual(fn.__code__.co_freevars, ref.__init__.__code__.co_freevars)
                        self.assertEqual(fn.__annotations__, ref.__init__.__annotations__)
                        self.assertEqual(fn.__defaults__, ref.__init__.__defaults__)
                        self.assertEqual(fn.__kwdefaults__, ref.__init__.__kwdefaults__)
        self.assertIs(dc._create_fn, original)

    def test_self_field_initvars_classvars_and_invalid_default_order(self):
        plan = capture_init_factory((InitField('self'), InitField('context', kind='initvar'),
                                    InitField('shared', kind='classvar')), has_post_init=True)
        self.assertIn('__dataclass_self__.self=self', plan.source)
        self.assertIn('__dataclass_self__.__post_init__(context)', plan.source)
        self.assertNotIn('shared', plan.source)
        with self.assertRaises(TypeError):
            capture_init_factory((InitField('first', default='value'), InitField('second')))
        for schema in ((InitField('x'), InitField('x')), (InitField('not valid'),),
                       (InitField('x', kind='initvar', default='factory'),), (InitField('x', default='guess'),), iter((InitField('x'),))):
            with self.assertRaises(ValueError): capture_init_factory(schema)


@unittest.skipUnless(TCC, 'host C compiler unavailable')
class FunctionAnnotationRuntimeTests(unittest.TestCase):
    def test_identity_uses_handles_and_singletons_but_never_numeric_equality(self):
        module_check({'m': '''a=[]
b=[]
same=a is a
different=a is not b
none=a is None
reverse=None is not a
true=True is True
false=True is False
number=0
zero=None is number
'''})
        module_check({'m': 'x=1000\ny=1000\nanswer=x is y\n'}, error=True, expected_external=1)
        module_check({'m': 'a=()\nb=()\nanswer=a is b\n'})
        module_check({'m': 'a=(1,2)\nb=(1,2)\nanswer=a is b\n'}, error=True, expected_external=1)
        module_check({'m': 'a=(1,2)\nb=a\nanswer=a is b\n'})

    def test_failed_annotation_keeps_default_side_effects_and_previous_binding(self):
        module_check({'m': '''events=0
f=99
def mark(n):
 global events
 events=events*10+n
 return n
def f(a:mark(1)=mark(7), b:missing=mark(8)): pass
''',}, error=True, expected_external=1,
            after='CHECK(PyZ80Target_LoadField(&objects,&modules[0],@events@,&value) && value.payload==781u);CHECK(PyZ80Target_LoadField(&objects,&modules[0],@f@,&value) && value.payload==99u);')

    def test_evaluation_order_defaults_annotations_decorators_and_posonly(self):
        module_check({'m': '''events=0
def mark(n):
    global events
    events=events*10+n
    return n
def decorate(f):
    global seen
    seen=f.__annotations__['b']*10+f.__annotations__['a']
    return f
@decorate
def f(a:mark(1)=mark(7), /, b:mark(2)=mark(8), *, c:mark(3)=mark(9))->mark(4):
    return a+b+c
answer=f()
returned=f.__annotations__['return']
'''})

    def test_annotation_dictionary_lifetime_aliasing_and_bound_methods(self):
        module_check({'m': '''def make():
    value=[7]
    def f(x:value): return x
    return f
f=make()
saved=f.__annotations__
class A:
    method=f
a=A()
same=a.method.__annotations__ is saved
saved['x'][0]=9
answer=f.__annotations__['x'][0]
f.__annotations__=None
empty=len(f.__annotations__)
f.__annotations__={'new':11}
updated=a.method.__annotations__['new']
'''}, classes=True, repetitions=1000)

    def test_empty_annotations_are_lazy_and_assigning_invalid_value_fails(self):
        module_check({'m': 'def f(): pass\na=f.__annotations__\nb=f.__annotations__\nsame=a is b\nsize=len(a)\n'}, repetitions=1000,
            after='''CHECK(PyZ80Target_LoadField(&objects,&modules[0],@f@,&value));
CHECK(!PyZ80Target_FindAttribute(&objects,&value,@__annotations__@,0));
CHECK(!PyZ80Target_FindAttribute(0,&value,@__annotations__@,&result));
CHECK(!PyZ80Target_FindAttribute(&objects,0,@__annotations__@,&result));
CHECK(!PyZ80Target_FindAttribute(&objects,&value,65535u,&result));''')
        module_check({'m': 'def f(): pass\nf.__annotations__=7\n'}, error=True)
        module_check({'m': 'class A:\n def f(self): pass\na=A()\na.f.__annotations__={}\n'}, classes=True, error=True)

    def test_postponed_function_annotations_are_compiler_strings_not_executed(self):
        annotation_import_check('''from __future__ import annotations
def f(x: missing[1 + 2], /, y: (int | None) = 7) -> 'Quoted':
    return y
x_annotation=f.__annotations__['x']
y_annotation=f.__annotations__['y']
result_annotation=f.__annotations__['return']
answer=f(3)
''')


@unittest.skipUnless(TCC, 'host C compiler unavailable')
class GeneratedInitRuntimeTests(unittest.TestCase):
    def test_actual_enemy_fields_defaults_and_original_post_init_body(self):
        path = Path(__file__).resolve().parents[1] / 'Python/rtype_port/enemies.py'
        source = path.read_text(encoding='utf-8')
        enemy = next(node for node in ast.parse(source).body if isinstance(node, ast.ClassDef) and node.name == 'Enemy')
        fields = [node for node in enemy.body if isinstance(node, ast.AnnAssign)]
        post = next(node for node in enemy.body if isinstance(node, ast.FunctionDef) and node.name == '__post_init__')
        post_source = ast.get_source_segment(source, post)
        schema = tuple(InitField(node.target.id, default='value' if node.value is not None else 'missing') for node in fields)
        plan = capture_init_factory(schema, has_post_init=True)
        bindings = {('annotation', node.target.id): repr(ast.unparse(node.annotation)) for node in fields}
        bindings.update({('default', node.target.id): ast.get_source_segment(source, node.value) for node in fields if node.value is not None})
        bindings.update({('factory-sentinel', None): 'None', ('builtin-object', None): 'object', ('none', None): 'None'})
        # The independent CPython oracle decorates the source-declared fields.
        namespace = {}
        exec(compile(post_source, str(path), 'exec', dont_inherit=True), namespace)
        oracle = dc.make_dataclass('Enemy', [(node.target.id, ast.unparse(node.annotation),
            dc.field(default=ast.literal_eval(node.value))) if node.value is not None else
            (node.target.id, ast.unparse(node.annotation)) for node in fields], namespace={'__post_init__': namespace['__post_init__']})
        cases = [(1, None), (4, None), (4, False), (1, True)]
        # ast.get_source_segment keeps original indentation on continuation
        # lines. Reparse the original method through ast.unparse for this unit
        # wrapper; the method's semantic AST is independently checked below.
        fixture = plan.source + '\nclass Enemy:\n __init__=' + call_factory(plan, bindings) + '\n' + textwrap.indent(ast.unparse(post), ' ') + '\n'
        actual_post = next(node for node in ast.parse(fixture).body[-1].body if isinstance(node, ast.FunctionDef))
        self.assertEqual(ast.dump(actual_post, include_attributes=False), ast.dump(post, include_attributes=False))
        checks = []
        for index, (hp, cadenced) in enumerate(cases):
            reference = oracle('test', 10, 20, 3, 4, hp=hp, force_damage_cadenced=cadenced)
            fixture += f"enemy=Enemy('test',10,20,3,4,hp={hp},force_damage_cadenced={cadenced!r})\n"
            for field in dc.fields(reference):
                key = f'case_{index}_{field.name}'
                fixture += f'{key}=enemy.{field.name}\n'
                expected = getattr(reference, field.name)
                if type(expected) in (bool, int):
                    checks.append(f'CHECK(PyZ80Target_LoadField(&objects,&modules[0],@{key}@,&value) && value.payload=={int(expected)}u);')
        module_check({'m': fixture}, classes=True, max_args=64, heap_scale=3, repetitions=100, after='\n'.join(checks))

    def test_keyword_only_initvar_self_field_and_non_init_class_default(self):
        schema = (InitField('self'), InitField('token', kind='initvar', kw_only=True),
                  InitField('stored', init=False, default='value'))
        plan = capture_init_factory(schema, has_post_init=True)
        bindings = {('annotation', name): 'None' for name in ('self', 'token', 'stored')}
        bindings.update({('factory-sentinel', None): 'None', ('builtin-object', None): 'object', ('none', None): 'None'})
        source = plan.source + '\nclass Record:\n stored=7\n __init__=' + call_factory(plan, bindings) + '''
 def __post_init__(self,token):
  self.total=self.self+token
  return 999
r=Record(11,token=13)
answer=r.total+r.stored
missing=getattr(r,'token',88)
'''
        module_check({'m': source}, classes=True, repetitions=1000,
            after='CHECK(PyZ80Target_LoadField(&objects,&modules[0],@answer@,&value) && value.payload==31u);')

    def test_exact_generated_init_runs_as_method_and_super_uses_dynamic_post_init(self):
        plan = capture_init_factory((InitField('a'), InitField('b', default='value')), has_post_init=True)
        bindings = {('annotation', 'a'): '41', ('annotation', 'b'): '42', ('default', 'b'): 'default',
                    ('factory-sentinel', None): 'None', ('builtin-object', None): 'object', ('none', None): 'None'}
        # Independent oracle: the actual decorator, not the generated text.
        @dc.dataclass
        class Record:
            a: int
            b: int = 7
            def __post_init__(self): self.total = self.a + self.b
        class Child(Record):
            def __init__(self, value): super().__init__(value)
            def __post_init__(self): self.total = self.a * self.b
        expected = Record(3).total * 100 + Child(5).total
        source = plan.source + '\ndefault=7\nclass Record:\n __init__=' + call_factory(plan, bindings) + '''
 def __post_init__(self): self.total=self.a+self.b
class Child(Record):
 def __init__(self,value): super().__init__(value)
 def __post_init__(self): self.total=self.a*self.b
default=99
Record.b=88
first=Record(a=3)
second=Child(5)
answer=first.total*100+second.total
annotations=Child.__init__.__annotations__
type_a=Record.__init__.__annotations__['a']
''' + f'correct=answer=={expected}\n'
        module_check({'m': source}, classes=True, repetitions=1000, after='CHECK(PyZ80Target_LoadField(&objects,&modules[0],@correct@,&value) && value.payload==1u);')

    def test_factory_defaults_are_called_per_instance_and_explicit_values_bypass_them(self):
        plan = capture_init_factory((InitField('items', default='factory'), InitField('extra', init=False, default='factory')))
        bindings = {('annotation', 'items'): 'None', ('annotation', 'extra'): 'None',
                    ('factory', 'items'): 'factory', ('factory', 'extra'): 'factory',
                    ('factory-sentinel', None): 'sentinel', ('builtin-object', None): 'object', ('none', None): 'None'}
        source = plan.source + '''
counter=0
sentinel=object()
def factory():
 global counter
 counter=counter+1
 return [counter]
class Record:
 __init__=''' + call_factory(plan, bindings) + '''
a=Record()
b=Record()
explicit=[9]
c=Record(explicit)
a.items[0]=99
answer=b.items[0]*100+c.extra[0]
distinct=a.items is not b.items
retained=c.items is explicit
'''
        module_check({'m': source}, classes=True, repetitions=1000,
            after='CHECK(PyZ80Target_LoadField(&objects,&modules[0],@counter@,&value) && value.payload==5u);')


if __name__ == '__main__': unittest.main()
