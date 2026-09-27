"""Проверки типов и атрибутов исходного Python в C VM с банковыми таблицами."""
import ast
from pathlib import Path
import textwrap
import unittest

from pyz80_compiler.module_imports import pinned_stdlib_sources
from test_pyz80_callable_runtime import TCC
from test_pyz80_import_runtime import import_check


@unittest.skipUnless(TCC,'нужен локальный C-компилятор')
class TypeCheckTests(unittest.TestCase):
    def check(self,source,**options):
        for banked in (False,True):
            with self.subTest(banked=banked):
                import_check({'app':source},banked=banked,classes=True,generators=True,sorting=True,**options)

    def test_source_classes_diamond_and_class_identity(self):
        self.check('''class A: pass
class B(A): pass
class C(A): pass
class D(B,C): pass
class Other: pass
obj=D()
a=isinstance(obj,D)
b=isinstance(obj,A)
c=isinstance(obj,C)
d=isinstance(obj,Other)
e=isinstance(D,A)
f=isinstance(obj,object)
g=issubclass(D,A)
h=issubclass(C,B)
i=issubclass(A,D)
j=issubclass(D,object)
k=issubclass(object,A)
alias=A
class A: pass
old=isinstance(obj,alias)
new=isinstance(obj,A)
''')

    def test_native_types_bool_is_int_but_int_is_not_bool(self):
        self.check('''a=isinstance(True,int)
b=isinstance(1,bool)
c=issubclass(bool,int)
d=issubclass(int,bool)
e=isinstance("x",str)
f=isinstance([],list)
g=isinstance((),tuple)
h=isinstance({},dict)
i=isinstance(set(),set)
j=isinstance(frozenset(),set)
k=isinstance(frozenset(),frozenset)
l=isinstance(range(3),range)
m=isinstance(enumerate([]),enumerate)
n=isinstance(None,object)
o=isinstance(len,object)
p=isinstance(int,object)
q=isinstance(True,str)
r=isinstance([],dict)
s=issubclass(list,object)
t=issubclass(list,tuple)
''')

    def test_nested_tuple_short_circuit_and_empty_tuple(self):
        self.check('''class A: pass
class B: pass
a=isinstance(A(),((),(B,(A,7)),None))
b=issubclass(A,(B,((A,7),)))
c=isinstance(7,())
d=issubclass(7,((),))
e=isinstance(7,((str,),(),(list,)))
f=issubclass(bool,(str,((int,),)))
''')

    def test_type_checks_inside_class_body_constructor_and_sort_key(self):
        self.check('''class Base: pass
class Child(Base):
    valid=issubclass(Base,object)
    def __init__(self):
        self.valid=isinstance(self,Base)
def key(x):
    return not isinstance(x,Child)
child=Child()
base=Base()
result=sorted([base,child],key=key)
a=result[0] is child
b=child.valid
c=Child.valid
d=isinstance(child,(int,Child))
''')

    def test_hasattr_plain_inherited_bound_methods_and_none(self):
        self.check('''class Base:
    inherited=None
    def method(self): return 7
class Child(Base): pass
c=Child()
c.value=None
a=hasattr(c,"value")
b=hasattr(c,"missing")
d=hasattr(c,"inherited")
e=hasattr(c,"method")
f=hasattr(Child,"inherited")
g=hasattr(c,"__class__")
h=hasattr([],"append")
i=hasattr({},"keys")
j=hasattr(Child,"missing")
''')

    def test_invalid_types_layouts_and_unknown_protocols_do_not_fall_back(self):
        for expression in ('isinstance(1)', 'isinstance(1,int,str)',
                           'isinstance(object=1,classinfo=int)', 'issubclass(7,int)',
                           'isinstance(7,(str,7,int))', 'issubclass(int,(str,None,int))',
                           'isinstance(7,len)', 'hasattr(object(),7)',
                           'hasattr(object())','hasattr(object(),name="x")'):
            with self.subTest(expression=expression):
                self.check('answer='+expression,expect_vm_error=True)
        self.check('''class C:
    def __getattr__(self,name): return 7
a=hasattr(C(),"x")
''',expect_vm_error=True)

    def test_classinfo_is_evaluated_once_and_source_shadowing_is_preserved(self):
        self.check('''calls=0
def info():
    global calls
    calls=calls+1
    return (str,(list,((int,),)))
a=isinstance(7,info())
def isinstance(a,b): return 99
b=isinstance(7,int)
def hasattr(a,b): return 88
c=hasattr(None,"x")
''')

    def test_depth_is_bounded_by_existing_binding_workspace(self):
        source='''info=int
for i in range(40):
    info=(info,)
answer=isinstance(7,info)
'''
        self.check(source,max_args=64,heap_scale=2)
        self.check(source,max_args=24,expect_vm_error=True,
            after='''for(j=0;j<DEPTH;++j)CHECK(!class_frames[j].operation);
for(j=0;j<MAX_ARGS;++j)CHECK(scratch[j].kind==PYZ80_VM_VALUE_NONE);''')

    def test_wide_shared_tuple_tree_yields_and_keeps_heap_constant(self):
        self.check('''info=(str,)
for i in range(8):
    info=(info,info)
ready=1
answer=isinstance(7,info)
''',max_slices=30000,c_helpers='static unsigned baseline_nodes,baseline_items,visits;',
            after_slice='''if(PyZ80Target_LoadField(&objects,&modules[0],@ready@,&value)) {
if(!baseline_nodes) { baseline_nodes=objects.node_used;baseline_items=objects.item_used; }
CHECK(objects.node_used==baseline_nodes && objects.item_used==baseline_items);
if(class_frames[1].operation==3)++visits;
}''',after='CHECK(visits>=256);')

    def test_same_ast_function_occurrences_remain_distinct(self):
        self.check('''def f(): return 7
old=f
def f(): return 7
different=old is not f
class A:
    def method(self): return 8
old_class=A
class A:
    def method(self): return 8
different_classes=old_class is not A
old_instance=old_class()
a=isinstance(old_instance,old_class)
b=isinstance(old_instance,A)
c=old( )+f()+old_instance.method()+A().method()
''')

    def test_no_constructor_support_is_inferred_from_type_identity(self):
        for expression in ('int(7)','str("x")','dict()'):
            with self.subTest(expression=expression):
                self.check('result='+expression,expect_vm_error=True)

    def test_cyclic_classinfo_stops_at_configured_depth_without_stack_wrap(self):
        for capacity in (24,255):
            self.check('info=(int,)\nready=1\nanswer=isinstance(7,info)',expect_vm_error=True,max_args=capacity,
                c_helpers='static unsigned changed;',after_slice='''
if(!changed && PyZ80Target_LoadField(&objects,&modules[0],@ready@,&value)) {
    CHECK(PyZ80Target_LoadField(&objects,&modules[0],@info@,&value));
    items[PyZ80Target_Node(&objects,&value)->item_start]=value;changed=1;
}''',after='''CHECK(changed);
for(j=0;j<DEPTH;++j)CHECK(!class_frames[j].operation);
for(j=0;j<MAX_ARGS;++j)CHECK(scratch[j].kind==PYZ80_VM_VALUE_NONE);''')

    def test_checks_in_defaults_do_not_damage_later_argument_binding(self):
        self.check('''class A: pass
def function(value=isinstance(7,(str,(int,))),*,cls=A):
    return value and isinstance(cls(),(str,A))
a=function()
b=function(False,cls=A)
c=function(True,cls=A)
''')

    def test_corrupt_mro_is_error_not_false_or_identity_success(self):
        self.check('''class A: pass
obj=A()
predicate=isinstance
''',c_helpers='#include "pyz80_target_type_checks.h"',after='''{
    PyZ80VMValue args[3],out;PyZ80TargetNode *node;uint16_t saved;
    CHECK(PyZ80Target_LoadField(&objects,&modules[0],@predicate@,&args[0]));
    CHECK(PyZ80Target_LoadField(&objects,&modules[0],@obj@,&args[1]));
    CHECK(PyZ80Target_LoadField(&objects,&modules[0],@A@,&args[2]));
    CHECK(PyZ80Target_TypeCheck(&classes,&vm,0,args,&out)==3);
    vm.call_depth=1;node=PyZ80Target_Node(&objects,&args[2]);saved=node->item_count;
    node->item_count=1;
    CHECK(PyZ80Target_TypeCheck(&classes,&vm,0,args,&out)==3);
    node->item_count=saved;
    CHECK(PyZ80Target_TypeCheck(&classes,&vm,0,args,&out)==1 && out.payload==1);
    vm.call_depth=0;
}''')

    def test_hasattr_does_not_hide_library_or_attribute_failures(self):
        self.check('''class A: pass
a=hasattr(A(),"__dict__")
''',expect_vm_error=True)

    def test_actual_object_pool_bind_method(self):
        path=Path(__file__).resolve().parents[1]/'Python/rtype_port/enemies.py'
        tree=ast.parse(path.read_text(encoding='utf-8-sig'))
        pool=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='M72ObjectPool')
        bind=next(n for n in pool.body if isinstance(n,ast.FunctionDef) and n.name=='bind')
        source='from __future__ import annotations\nclass Pool:\n'+textwrap.indent(ast.unparse(bind),'    ')+'''
class Enemy: pass
pool=Pool()
pool.serial=7
pool.residue={11:(23,45),12:(67,89)}
a=Enemy()
a.inherit_slot_fractions=True
a.x_fraction=0
pool.bind(a,11)
b=Enemy()
b.inherit_slot_fractions=False
b.x_fraction=9
b.y_fraction=8
pool.bind(b,12)
ax=a.x_fraction
ay=hasattr(a,"y_fraction")
aslot=a.object_slot
serial=a.scheduler_serial
bx=b.x_fraction
by=b.y_fraction
last_serial=pool.serial
'''
        library=pinned_stdlib_sources()['__future__']
        for banked in (False,True):
            import_check({'app':source,'__future__':library.read_text(encoding='utf-8')},
                library_paths={'__future__':library},classes=True,generators=True,banked=banked)

    def test_actual_palette_release_branch_for_every_source_type(self):
        path=Path(__file__).resolve().parents[1]/'Python/rtype_port/enemies.py'
        tree=ast.parse(path.read_text(encoding='utf-8-sig'))
        world=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='M72EnemyWorld')
        update=next(n for n in world.body if isinstance(n,ast.FunctionDef) and n.name=='update')
        branch=next(n for n in ast.walk(update) if isinstance(n,ast.If) and
                    ast.unparse(n.test)=='isinstance(enemy, GroundWalker)')
        types=[]
        for n in ast.walk(branch):
            if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='isinstance':
                types.extend(x.id for x in ast.walk(n.args[1]) if isinstance(x,ast.Name))
        source='''class Enemy:
    def __init__(self):
        self.secondary_palette=11
        self.flash_palette=22
        self.alt_palette=33
class Resources:
    def __init__(self): self.last=0
    def release(self,value): self.last=value
'''+''.join('class '+name+'(Enemy): pass\n' for name in types)
        source+='class World:\n    def release_palette(self,enemy):\n'+textwrap.indent(ast.unparse(branch),'        ')+'\n'
        source+='world=World()\nworld.resources=Resources()\n'
        for i,name in enumerate(types+['Enemy']):
            source+='world.resources.last=0\nworld.release_palette('+name+'())\nresult'+str(i)+'=world.resources.last\n'
        self.check(source,heap_scale=4,max_slices=40000)


if __name__=='__main__':
    unittest.main()
