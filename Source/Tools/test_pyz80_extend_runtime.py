"""Исходный list.extend: мутация, приостановки генератора и GC на каждом шаге."""
import ast
from pathlib import Path
import textwrap
import unittest

from test_pyz80_callable_runtime import TCC
from test_pyz80_import_runtime import import_check


@unittest.skipUnless(TCC, 'нужен локальный C-компилятор')
class ExtendRuntimeTests(unittest.TestCase):
    def check(self, source, **options):
        for banked in (False, True):
            with self.subTest(banked=banked):
                import_check({'app':source}, generators=True, banked=banked, **options)

    def test_bound_method_retains_owner_and_returns_none(self):
        self.check('''a=[1]
alias=a
extend=a.extend
a=None
result=extend((2,3))
first=alias[0]
second=alias[1]
last=alias[2]
size=len(alias)
''')

    def test_self_extension_is_finite_and_keeps_identity(self):
        self.check('''a=[1,2,3]
alias=a
result=a.extend(alias)
same=alias is a
size=len(a)
digits=0
for item in a:
    digits=digits*10+item
empty=[]
result2=empty.extend(empty)
empty_size=len(empty)
cycle=[]
cycle.append(cycle)
cycle.extend(cycle)
cycle_size=len(cycle)
first_cycle=cycle[0] is cycle
second_cycle=cycle[1] is cycle
''')

    def test_native_sources_and_existing_iterator_position(self):
        self.check('''a=[]
a.extend(range(5,-1,-2))
source=[7,8,9]
it=iter(source)
skipped=next(it)
a.extend(it)
a.extend({10:100,11:110})
a.extend({12:120,13:130}.values())
a.extend(())
size=len(a)
total=0
for item in a:
    total=total+item
pairs=[]
pairs.extend({14:140,15:150}.items())
pairs.extend(enumerate([160,170],-2))
key=pairs[0][0]
value=pairs[1][1]
index=pairs[2][0]
last=pairs[3][1]
''')

    def test_generator_observes_each_append_before_its_next_resume(self):
        self.check('''a=[7]
events=0
def values():
    global events
    events=events*10+len(a)
    yield len(a)
    events=events*10+len(a)
    yield len(a)
    events=events*10+len(a)
    a.clear()
    yield 9
    events=events*10+len(a)
g=values()
result=a.extend(g)
size=len(a)
last=a[0]
end=next(g,99)
''')

    def test_nested_extend_and_generator_expression(self):
        self.check('''a=[]
def inner():
    yield [3]
    yield [4]
def outer():
    b=[]
    b.extend(inner())
    yield b
    yield [5]
a.extend(outer())
x=a[0][0][0]
y=a[0][1][0]
z=a[1][0]
b=[]
b.extend(x+1 for x in range(40))
size=len(b)
total=0
for x in b:
    total=total+x
''', max_slices=40000)

    def test_iterator_alias_does_not_use_self_snapshot_rule(self):
        self.check('''a=[1,2,3,4]
it=iter(a)
skipped=next(it)
def finite():
    yield next(it)
    yield next(it)
    yield next(it)
    yield next(it)
    yield next(it)
a.extend(finite())
size=len(a)
tail=a[-1]
next_value=next(it)
''')

    def test_source_class_method_with_same_name_is_not_native(self):
        self.check('''class Receiver:
    def extend(self, value):
        return value+9
r=Receiver()
answer=r.extend(7)
''', classes=True)

    def test_real_pending_transfer_statements_are_unchanged(self):
        path=Path(__file__).resolve().parents[1]/'Python/rtype_port/enemies.py'
        tree=ast.parse(path.read_text(encoding='utf-8-sig'))
        world=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='M72EnemyWorld')
        update=next(n for n in world.body if isinstance(n,ast.FunctionDef) and n.name=='update')
        pending=next(n for n in update.body if isinstance(n,ast.If) and ast.unparse(n.test)=='self.pending')
        # Переносим исходный узел целиком; окружающие объекты — только тестовые входы.
        method='    def transfer(self):\n'+textwrap.indent(ast.unparse(pending),'        ')+'\n'
        self.check('''class Enemy:
    pass
class World:
    pass
'''.replace('class World:\n    pass\n','class World:\n'+method)+'''world=World()
first=Enemy()
second=Enemy()
world.enemies=[first]
world.pending=[second,first]
pending_alias=world.pending
enemies_alias=world.enemies
world.transfer()
size=len(world.enemies)
empty=len(pending_alias)
same=world.enemies is enemies_alias
a=world.enemies[0] is first
b=world.enemies[1] is second
c=world.enemies[2] is first
world.transfer()
still_size=len(world.enemies)
''', classes=True)

    def test_append_budget_is_at_most_one_element_per_vm_slice(self):
        self.check('a=[]\na.extend(range(96))\nsize=len(a)', budget=1,
            c_helpers='static unsigned previous_size;', after_slice='''
if(PyZ80Target_LoadField(&objects,&modules[0],@a@,&value)) {
    PyZ80TargetNode *node=PyZ80Target_Node(&objects,&value);
    CHECK(node && node->kind==PYZ80_TARGET_NODE_LIST);
    CHECK(node->item_count>=previous_size && node->item_count<=previous_size+1);
    previous_size=node->item_count;
}''', after='CHECK(previous_size==96);')

    def test_invalid_calls_do_not_reach_external_fallback(self):
        for call in ('a.extend()', 'a.extend([],[])', 'a.extend(iterable=[])',
                     'a.extend(None)', 'a.extend(7)', 'a.extend("ab")'):
            with self.subTest(call=call):
                self.check('a=[]\n'+call, expect_vm_error=True)

    def test_generator_error_preserves_appended_prefix_and_clears_continuations(self):
        for banked in (False,True):
            with self.subTest(banked=banked):
                import_check({'app':'''import saved
def values():
    yield 7
    yield 8
    [][0]
saved.a.extend(values())
''', 'saved':'a=[]'}, generators=True, banked=banked, expect_vm_error=True,
                    after='''CHECK(PyZ80Target_LoadField(&objects,&modules[$saved$],@a@,&value));
CHECK(PyZ80Target_Node(&objects,&value)->item_count==2);
CHECK(items[PyZ80Target_Node(&objects,&value)->item_start].payload==7);
CHECK(items[PyZ80Target_Node(&objects,&value)->item_start+1].payload==8);
for(j=0;j<DEPTH;++j)CHECK(!generator_frames[j].state);
for(j=0;j<DEPTH*3;++j)CHECK(generator_roots[j].kind==PYZ80_VM_VALUE_NONE);''')


if __name__=='__main__':
    unittest.main()
