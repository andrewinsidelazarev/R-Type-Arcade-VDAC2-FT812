"""Real stdlib decorator/imports -> source factories -> C classes, stepwise GC."""
import ast
from pathlib import Path
import textwrap
import unittest

from pyz80_compiler.dataclass_methods import capture_eq_factory
from pyz80_compiler.dataclass_provider import is_provider_source
from pyz80_compiler.module_imports import pinned_stdlib_sources
from pyz80_compiler.module_program import build_module_program
from test_pyz80_callable_runtime import TCC
from test_pyz80_import_runtime import import_check


def check(source, **kwargs):
    paths = pinned_stdlib_sources()
    return import_check({'app': source, **{n:p.read_text(encoding='utf-8') for n,p in paths.items()}},
                        library_paths=paths, classes=True, dataclasses=True, heap_scale=3, **kwargs)


@unittest.skipUnless(TCC, 'host C compiler unavailable')
class DataclassProviderTests(unittest.TestCase):
    def test_import_decorate_construct_defaults_and_post_init(self):
        program, _ = check('''from dataclasses import dataclass
@dataclass
class Record:
    x: 'int'
    y: 'int' = 7
    def __post_init__(self):
        self.x = self.x + self.y
a = Record(3)
b = Record(y=9, x=2)
answer = a.x * 100 + b.x
unchanged_default = Record.y
annotations = Record.__init__.__annotations__['x']
first_match = Record.__match_args__[0]
unhashable = Record.__hash__ is None
''')
        self.assertEqual(len([r for r in program.graph['dataclass_candidates'] if r['class_id'].startswith('app::')]), 1)

    def test_explicit_alias_local_decorator_and_defaults_changed_before_decoration(self):
        check('''from dataclasses import dataclass as decorate
def dataclass(cls):
    cls.marker = 42
    return cls
@dataclass
class Local:
    x: 'int' = 3
class Real:
    x: 'int' = 4
Real.x = 12
original = Real
Real = decorate(Real, repr=False, eq=False)
Real.x = 99
obj = Real()
answer = obj.x * 100 + Local.marker
same = original is Real
''')

    def test_local_dataclasses_module_not_replaced_by_library_provider(self):
        import_check({'app':'from dataclasses import dataclass\n@dataclass\nclass A:\n    pass\nanswer=A.marker\n',
                      'dataclasses':'def dataclass(cls):\n    cls.marker=17\n    return cls\n'}, classes=True)

    def test_changed_class_module_cannot_use_guessed_method_globals(self):
        paths=pinned_stdlib_sources()
        import_check({'app': '''from dataclasses import dataclass
import foreign
NotImplemented = 17
class A:
    x: 'int' = 1
class B:
    pass
A.__module__ = 'foreign'
A = dataclass(A)
answer = A().__eq__(B())
''', 'foreign': 'NotImplemented=99\n', **{n:p.read_text(encoding='utf-8') for n,p in paths.items()}},
            library_paths=paths, classes=True, dataclasses=True, heap_scale=3, expect_vm_error=True)

    def test_existing_init_and_explicit_match_args_preserved(self):
        check('''from dataclasses import dataclass
@dataclass
class Record:
    __match_args__ = ('other',)
    x: 'int' = 7
    def __init__(self, x):
        self.x = x + 2
obj = Record(3)
answer = obj.x
match = Record.__match_args__[0]
''')

    def test_explicit_doc_preserved_but_falsy_doc_needs_real_signature_text(self):
        check('''from dataclasses import dataclass
@dataclass
class A:
    "existing documentation"
    x: 'int' = 7
answer = A.__doc__
''')
        for doc in ("''", 'False', '0'):
            with self.subTest(doc=doc):
                check("from dataclasses import dataclass\n@dataclass\nclass A:\n    __doc__ = "+doc+"\n    x: 'int'=7\nanswer=A.__doc__\n", expect_vm_error=True)

    def test_decorator_factory_captures_options_and_distinct_local_classes(self):
        check('''from dataclasses import dataclass
def make(default):
    @dataclass(init=True, eq=False, repr=False, match_args=False)
    class Record:
        x: 'int' = default
    return Record
A = make(3)
B = make(9)
a = A()
b = B()
answer = a.x * 10 + b.x
different = A is not B
''')

    def test_changed_schema_is_not_translated_as_stale_fields(self):
        check('''from dataclasses import dataclass
class A:
    x: 'int' = 7
A.__annotations__['other'] = 'int'
A = dataclass(A, init=False)
''', expect_vm_error=True)

    def test_generated_equality_runs_exact_source_body_on_scalar_fields(self):
        check('''from dataclasses import dataclass
@dataclass
class Pair:
    x: 'int'
    y: 'str' = 'a'
a = Pair(3)
b = Pair(3)
c = Pair(4)
equal = a.__eq__(b)
different = a.__eq__(c)
alias = Pair(3, y='b')
different_string = a.__eq__(alias)
''')

    def test_post_init_selection_occurs_at_decoration_and_lookup_at_call_time(self):
        check('''from dataclasses import dataclass
class A:
    x: 'int' = 1
def first(self):
    self.x = self.x + 10
def second(self):
    self.x = self.x + 20
A.__post_init__ = first
A = dataclass(A)
a = A()
A.__post_init__ = second
b = A()
answer = a.x * 100 + b.x
@dataclass
class B:
    x: 'int' = 1
B.__post_init__ = first
c = B()
no_late_injection = c.x
''')

    def test_invalid_default_order_init_false_and_empty_class(self):
        check('''from dataclasses import dataclass
@dataclass(init=False, eq=False, repr=False)
class A:
    x: 'int' = 8
    y: 'int'
@dataclass
class Empty:
    pass
obj = A()
answer = obj.x
empty = Empty()
empty_match_count = len(Empty.__match_args__)
''')
        check("from dataclasses import dataclass\n@dataclass\nclass A:\n    x: 'int'=8\n    y: 'int'\n", expect_vm_error=True)

    def test_annotations_defaults_and_reordered_keys_cannot_escape_guard(self):
        for change in ("A.__annotations__['x'] = 'float'", "A.x = []",
                       "A.__annotations__ = None", "A.__annotations__['z'] = 'int'",
                       "A.__qualname__ = 'Other'"):
            with self.subTest(change=change):
                check("from dataclasses import dataclass\nclass A:\n    x: 'int'=8\n"+change+'\nA=dataclass(A)\n', expect_vm_error=True)

    def test_attach_validates_proof_origin_signature_ranges_alias_and_idle_state(self):
        check("from dataclasses import dataclass\n@dataclass\nclass A:\n    x: 'int'=8\nobj=A()\nanswer=obj.x\n",
              before_dataclasses=r'''
    {
        PyZ80DataclassPlan bad=PyZ80GeneratedDataclassPlan;
        PyZ80DataclassClass row=bad.classes[0];
        uint8_t wrong[32];
        memset(wrong,0,sizeof(wrong));bad.proof=wrong;
        CHECK(!PyZ80Target_AttachDataclasses(&dataclass_context,&scopes,&bad));
        bad=PyZ80GeneratedDataclassPlan;bad.classes=&row;bad.class_count=1;
        row.origin=65535u;
        CHECK(!PyZ80Target_AttachDataclasses(&dataclass_context,&scopes,&bad));
        row=PyZ80GeneratedDataclassPlan.classes[0];row.field_start=65535u;
        CHECK(!PyZ80Target_AttachDataclasses(&dataclass_context,&scopes,&bad));
        row=PyZ80GeneratedDataclassPlan.classes[0];row.apply_plain=row.origin;
        CHECK(!PyZ80Target_AttachDataclasses(&dataclass_context,&scopes,&bad));
        CHECK(!PyZ80Target_AttachDataclasses((PyZ80TargetDataclasses*)nodes,&scopes,&PyZ80GeneratedDataclassPlan));
        CHECK(!PyZ80Target_AttachDataclasses(0,&scopes,&PyZ80GeneratedDataclassPlan));
        CHECK(!PyZ80Target_AttachDataclasses(&dataclass_context,0,&PyZ80GeneratedDataclassPlan));
        CHECK(!PyZ80Target_AttachDataclasses(&dataclass_context,&scopes,0));
        CHECK(!objects.library_provider);
    }
''', after_dataclasses='CHECK(!PyZ80Target_AttachDataclasses(&dataclass_context,&scopes,&PyZ80GeneratedDataclassPlan));')

    def test_unsupported_options_and_protocol_reads_stop_explicitly(self):
        for ending in ('A = dataclass(A, frozen=True)', 'A = dataclass(A, slots=True)',
                       'A = dataclass(A, kw_only=True)', 'A = dataclass(A, order=True)',
                       'A = dataclass(A)\nx = A.__dataclass_fields__',
                       'A = dataclass(A)\nx = getattr(A, "__dataclass_params__", None)',
                       'A = dataclass(A)\nx = A.__doc__',
                       'A = dataclass(A)\nx = A().__repr__()'):
            with self.subTest(ending=ending):
                check("from dataclasses import dataclass\nclass A:\n    x: 'int' = 7\n"+ending+'\n', expect_vm_error=True)

    def test_actual_enemy_class_keeps_decorator_and_post_init(self):
        path = Path(__file__).resolve().parents[1]/'Python/rtype_port/enemies.py'
        text = path.read_text(encoding='utf-8')
        node = next(n for n in ast.parse(text).body if isinstance(n, ast.ClassDef) and n.name=='Enemy')
        # Extract the complete original class, INCLUDING its original decorator.
        lines = text.splitlines(keepends=True)
        original = ''.join(lines[min(n.lineno for n in node.decorator_list)-1:node.end_lineno])
        fields = [n.target.id for n in node.body if isinstance(n, ast.AnnAssign)]
        self.assertEqual(len(fields), 22)
        source = 'from __future__ import annotations\nfrom dataclasses import dataclass\n' + original
        operations = '''
a = Enemy('test', 10, 20, 3, 4)
b = Enemy('test', 30, 40, 5, 6, hp=3)
normal_cadence = a.force_damage_cadenced
armored_cadence = b.force_damage_cadenced
b.take_damage(None, 3)
dead = not b.alive
destroyed = b.destroyed
'''
        operations += ''.join(f'field_{name} = a.{name}\n' for name in fields)
        source += '\nfor iteration in range(100):\n' + textwrap.indent(operations, '    ')
        for banked in (False, True):
            with self.subTest(banked=banked):
                check(source, max_args=64, max_slices=200000, banked=banked)


class DataclassEqualityGeneratorTests(unittest.TestCase):
    def test_provider_is_sealed_by_path_and_bytes_not_module_spelling(self):
        path=pinned_stdlib_sources()['dataclasses']
        source=path.read_text(encoding='utf-8')
        self.assertTrue(is_provider_source('dataclasses',path,source))
        self.assertFalse(is_provider_source('dataclasses',Path('dataclasses.py'),source))
        self.assertFalse(is_provider_source('copy',path,source))
        with self.assertRaises(ValueError):
            is_provider_source('dataclasses',path,source+'\n')

    def test_equality_factory_is_cpython_code(self):
        import dataclasses
        original = dataclasses._create_fn
        plan = capture_eq_factory(('x','y'))
        ns={}
        exec(compile(plan.source,'<equality>','exec',dont_inherit=True),ns)
        function=ns['__create_fn__']()
        reference=dataclasses.make_dataclass('Ref',[('x',int),('y',int)]).__eq__
        self.assertEqual(function.__code__.co_code,reference.__code__.co_code)
        self.assertEqual(function.__code__.co_consts,reference.__code__.co_consts)
        self.assertIs(original,dataclasses._create_fn)
