"""Исходные in/not in: ограниченный по шагам поиск, порядок, identity и генераторы."""
import unittest

from test_pyz80_callable_runtime import TCC
from test_pyz80_import_runtime import import_check


@unittest.skipUnless(TCC,'нужен локальный C-компилятор')
class SequenceMembershipTests(unittest.TestCase):
    def check(self,source,**options):
        for banked in (False,True):
            with self.subTest(banked=banked):
                import_check({'app':source},generators=True,banked=banked,**options)

    def test_scalar_membership_and_negation(self):
        self.check('''a=1 in (0,True,2)
b=False in [None,0]
c=None not in (0,False,"")
d="flight" in ("spent","flight")
e="other" not in ("spent","flight")
f=0 in ()
g=1 not in []
h=-2147483648 in (2147483647,-2147483648)
i=2147483647 not in [-2147483648]
j=(1,True) in [(0,1),(True,1)]
k=(1,3) not in [(1,2),(3,1)]
''')

    def test_reference_identity_shortcuts_and_empty_unknown_type(self):
        self.check('''a=[]
a.append(a)
b=a in a
c=a not in [a]
d=[1] not in []
e=list in [list]
class Item: pass
obj=Item()
f=obj in (obj,)
g=obj not in ()
''', classes=True)

    def test_unknown_equality_is_error_not_false(self):
        for expression in ('[1] in [[1]]', '1 in [[1],1]', '((1,),) in [((1,),)]'):
            with self.subTest(expression=expression):
                self.check('a='+expression,expect_vm_error=True)
        self.check('a=1 in [1,[1]]\nb=1 not in [1,[1]]')

    def test_membership_consumes_iterator_only_until_match(self):
        self.check('''it=iter([1,2,3,2,4])
a=2 in it
b=next(it)
c=2 not in it
d=next(it)
e=8 in it
f=next(it,99)
rev=reversed([1,2,3,4])
g=3 in rev
h=next(rev)
i=7 not in rev
j=next(rev,98)
''')

    def test_generator_continuations_and_live_mutation(self):
        self.check('''events=0
values=[1,2,3]
def source():
    global events
    for x in values:
        events=events*10+x
        yield x
g=source()
a=2 in g
after_first=events
values.append(4)
b=4 not in g
after_second=events
c=next(g,99)
''')

    def test_nested_membership_generator_has_no_c_recursion(self):
        self.check('''def inner():
    yield 1
    yield 2
def outer():
    yield 3 in inner()
    yield 2 in inner()
    yield 9
g=outer()
a=True in g
b=next(g)
c=next(g,99)
''', after='''for(j=0;j<DEPTH;++j)CHECK(!generator_frames[j].state);
for(j=0;j<DEPTH*3;++j)CHECK(generator_roots[j].kind==PYZ80_VM_VALUE_NONE);''')

    def test_range_views_and_enumerate(self):
        self.check('''a=5 in range(9,-1,-2)
b=6 not in range(9,-1,-2)
d={1:10,2:20}
c=1 in d
e=20 in d.values()
f=(2,20) in d.items()
g=3 not in d.keys()
h=(1,6) in enumerate([5,6,7])
i=5 in {5,6}
j=7 not in {5,6}
''')

    def test_budget_and_no_temporary_list(self):
        self.check('it=iter(range(96))\nanswer=95 in it',
            c_helpers='static unsigned previous_cursor;',after_slice='''
if(PyZ80Target_LoadField(&objects,&modules[0],@it@,&value)) {
    PyZ80TargetNode *node=PyZ80Target_Node(&objects,&value);
    CHECK(node && node->cursor>=previous_cursor && node->cursor<=previous_cursor+1);
    previous_cursor=node->cursor;
}
for(j=0;j<objects.node_used;++j)CHECK(nodes[j].kind!=PYZ80_TARGET_NODE_LIST);
''', after='CHECK(previous_cursor==96);')

    def test_failure_clears_requests_and_roots(self):
        self.check('it=iter([1,[2],3])\na=3 in it',expect_vm_error=True,after='''
for(j=0;j<DEPTH;++j)CHECK(!generator_frames[j].state);
for(j=0;j<DEPTH*3;++j)CHECK(generator_roots[j].kind==PYZ80_VM_VALUE_NONE);''')


if __name__ == '__main__':
    unittest.main()
