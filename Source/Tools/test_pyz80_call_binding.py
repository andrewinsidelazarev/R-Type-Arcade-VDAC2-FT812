"""Source calls with evaluated defaults and exact keyword binding versus CPython."""
import unittest
import ast
import textwrap
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
from types import MethodType, SimpleNamespace

from test_pyz80_builtin_runtime import check_source
from test_pyz80_callable_runtime import TCC, compile_run, PRELUDE
from test_pyz80_scope_runtime import source_artifact
from test_pyz80_gc_runtime import source_header
from test_pyz80_target_object_runtime import RUNTIME, SDCC


@unittest.skipUnless(TCC, "host compiler unavailable")
class CallBindingTests(unittest.TestCase):
    def test_successful_hook_without_function_identity_fails_closed(self):
        helpers = r'''
static uint8_t hook_calls, hook_depth;
static uint8_t missing_prepare(void *context, PyZ80VM *vm, uint16_t adapter,
    PyZ80VMValue *args, uint8_t *count, uint16_t *function) {
    (void)context;(void)vm;(void)adapter;(void)args;(void)count;(void)function;
    ++hook_calls;hook_depth=vm->call_depth;
    return 1;
}
static uint8_t missing_resolve(void *context, PyZ80VM *vm,
    const PyZ80VMValue *callable, uint8_t count, uint16_t *function) {
    (void)context;(void)vm;(void)callable;(void)count;(void)function;
    ++hook_calls;hook_depth=vm->call_depth;
    return 1;
}
'''
        for call in ("f(seed)", "f(x=seed)"):
            source = "def factory(seed):\n    def f(x):\n        return x + 1\n    return " + call + "\n"
            for hook in ("prepare", "resolve"):
                with self.subTest(call=call, hook=hook):
                    check_source(source, bindings=True, expected_error=True, c_helpers=helpers,
                        before_run="scopes.hooks.prepare=0;scopes.hooks.resolve=0;\n"
                                   f"scopes.hooks.{hook}=missing_{hook};\n",
                        postcheck="CHECK(vm.error==PYZ80_VM_E_ARGUMENT && hook_calls==1);\n"
                                  "CHECK(vm.call_depth==hook_depth); /* No callee frame was pushed. */\n")

    def test_noncallable_type_error_occurs_after_argument_side_effects(self):
        prefix = '''def factory(seed):
    def argument():
        seed.number = seed.number + 1
        return 42
'''
        for tail in ("    cb = None\n    return cb(argument())\n",
                     "    return seed.missing(argument())\n"):
            check_source(prefix+tail,python_argument=SimpleNamespace(number=0),bindings=True,
                setup="CHECK(PyZ80Target_AllocateNode(&objects,PYZ80_TARGET_NODE_OBJECT,0,&arg));"
                      "value=integer(0);CHECK(PyZ80Target_StoreField(&objects,&arg,@number@,&value));",
                postcheck="CHECK(PyZ80Target_LoadField(&objects,&arg,@number@,&value));CHECK(value.payload==@python_number@);\n")

    def test_returned_mutable_defaults_survive_gc_and_calls_from_another_function(self):
        source = '''def factory(seed):
    temporary = [0,1,2]
    def f(x=[seed],*,step=2):
        x[0] = x[0] + step
        return x[0]
    return f

def run(callback):
    return callback(step=3)
'''
        namespace={}
        exec(source,namespace)
        refs=[namespace["factory"](seed) for seed in (7,100)]
        expected=[namespace["run"](refs[index%2]) for index in range(1000)]
        compile_run(PRELUDE + '#include "pyz80_target_gc.h"\n#include "pyz80_target_call_binding.h"\n' +
            source_header(source) + "static const uint32_t expected[]={" + ",".join(map(str,expected)) + "};\n" + r'''
int main(void) {
    PyZ80TargetContext objects;PyZ80TargetScopes scopes;
    PyZ80TargetNode nodes[16];PyZ80TargetField fields[8];
    PyZ80VMValue items[64],frames[8],globals[FUNCTIONS],arg,result,roots[2],scratch[12];
    uint8_t marks[16];uint16_t queue[16],fm[8],im[64];
    PyZ80TargetGC gc={marks,queue,fm,im,16,8,64,0,0,0,0};
    PyZ80VM vm;PyZ80VMAdapter adapter;PyZ80VMLimits limits={8,0,64,12};
    PyZ80VMMemoryImage memory={bytes,sizeof(bytes)};
    PyZ80VMImage image={PyZ80VM_MemoryRead,&memory,sizeof(bytes),proof};
    union {uint32_t align;uint8_t bytes[8192];} arena;
    unsigned i;uint8_t status;
    PyZ80Target_Init(&objects,nodes,16,fields,8,items,64,specs,ALLOCATE+1,ops,OP_COUNT,0,0);
    objects.field_keys=keys;objects.field_key_count=sizeof(keys)/sizeof(keys[0]);objects.function_count=FUNCTIONS;
    objects.positional_call_arities=arities;objects.call_signatures=signatures;objects.parameter_names=parameter_names;
    objects.parameter_name_count=PARAMETER_NAMES;objects.call_layout_offsets=call_layout_offsets;
    objects.call_layout_keys=call_layout_keys;objects.call_layout_key_count=CALL_LAYOUT_KEYS;
    CHECK(PyZ80Target_AllocateNode(&objects,PYZ80_TARGET_NODE_OBJECT,0,&globals[0]));
    for(i=1;i<FUNCTIONS;++i)globals[i]=globals[0];
    adapter=PyZ80Target_VMAdapter(&objects);
    CHECK(PyZ80VM_Init(&vm,&image,&adapter,arena.bytes,sizeof(arena.bytes),&limits)==PYZ80_VM_IDLE);
    CHECK(PyZ80Target_AttachScopes(&scopes,&objects,&vm,frames,8,globals,FUNCTIONS));
    CHECK(!PyZ80Target_AttachCallBinding(&scopes,scratch,11));
    CHECK(!PyZ80Target_AttachCallBinding(&scopes,vm.argument_scratch+1,12));
    CHECK(!PyZ80Target_AttachCallBinding(&scopes,items+1,12));
    CHECK(scopes.hooks.prepare==0);
    CHECK(PyZ80Target_AttachCallBinding(&scopes,scratch,12));
    for(i=0;i<2;++i) {
        arg=integer(i?100:7);CHECK(PyZ80VM_StartArgs(&vm,0,&arg,1)==PYZ80_VM_RUNNING);
        status=PYZ80_VM_RUNNING;
        while(status==PYZ80_VM_RUNNING)
            status=PyZ80Target_RunSlice(&objects,&vm,&scopes,roots,i,&gc,1,&result);
        CHECK(status==PYZ80_VM_RETURNED);roots[i]=result;
    }
    CHECK(gc.live_nodes==5 && objects.item_used==10);
    for(i=0;i<1000;++i) {
        CHECK(PyZ80VM_StartArgs(&vm,2,&roots[i%2],1)==PYZ80_VM_RUNNING);
        status=PYZ80_VM_RUNNING;
        while(status==PYZ80_VM_RUNNING)
            status=PyZ80Target_RunSlice(&objects,&vm,&scopes,roots,2,&gc,1,&result);
        CHECK(status==PYZ80_VM_RETURNED && result.payload==expected[i]);
        CHECK(gc.live_nodes==5 && objects.item_used==10);
    }
    CHECK(PyZ80Target_Collect(&objects,&vm,&scopes,roots,1,&gc));
    CHECK(gc.live_nodes==3 && objects.item_used==5);
    return 0;
}
''',gc=True,bindings=True)

    @unittest.skipUnless(SDCC, "Z80 compiler unavailable")
    def test_binder_compiles_for_sdcc_with_no_static_scratch(self):
        with tempfile.TemporaryDirectory(prefix="pz-call-binding-z80-") as raw:
            directory=Path(raw)
            for name in ("pyz80_whole_program_vm.h","pyz80_target_object_runtime.h","pyz80_target_scope_runtime.h",
                         "pyz80_target_call_binding.h","pyz80_target_call_binding.c"):
                shutil.copy2(RUNTIME/name,directory/name)
            environment=os.environ.copy()
            environment["PATH"]=str(SDCC.parent)+os.pathsep+environment.get("PATH","")
            run=subprocess.run([str(SDCC),"-mz80","--std-c11","--sdcccall","1","--stack-auto",
                "--opt-code-speed","-c","pyz80_target_call_binding.c"],cwd=directory,env=environment,
                capture_output=True,text=True,timeout=240)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            self.assertIn("A _DATA size 0 ",(directory/"pyz80_target_call_binding.rel").read_text())

    def test_actual_lifecycle_initializer_takes_lives_from_source_default(self):
        path = Path(__file__).resolve().parents[1] / "Python/rtype_port/player_lifecycle.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        constants = {node.targets[0].id: ast.literal_eval(node.value) for node in tree.body
            if isinstance(node,ast.Assign) and isinstance(node.targets[0],ast.Name)
            and node.targets[0].id in ("INITIAL_LIVES","MAX_LIVES")}
        owner = next(node for node in tree.body if isinstance(node,ast.ClassDef) and node.name=="PlayerLifecycle")
        method = next(node for node in owner.body if isinstance(node,ast.FunctionDef) and node.name=="__init__")
        # The initializer, including its signature/default and body, is copied
        # directly from AST; the wrapper only supplies the test receiver.
        for call in ("__init__(seed)","__init__(seed,lives=3)"):
            source = "from __future__ import annotations\ndef factory(seed):\n" + textwrap.indent(ast.unparse(method),"    ") + \
                f"\n    {call}\n    return seed.lives\n"
            pool = source_artifact(source).compact_document["constants"]
            setup = "CHECK(PyZ80Target_AllocateNode(&objects,PYZ80_TARGET_NODE_OBJECT,0,&arg));\n"
            for name,value in constants.items():
                setup += f"value=integer({value});CHECK(PyZ80Target_StoreField(&objects,&globals[0],{pool.index(name)},&value));\n"
            check_source(source,namespace=constants,python_argument=SimpleNamespace(),setup=setup,bindings=True)

    def test_module_function_and_bound_method_use_actual_identity(self):
        source = "def factory(seed):\n    return f(y=seed,x=2)\n\ndef f(x,y):\n    return x*10+y\n"
        key = source_artifact(source).compact_document["constants"].index("f")
        check_source(source,bindings=True,setup=f"""
    CHECK(PyZ80Target_Callable(&objects,1,0,&value));
    CHECK(PyZ80Target_StoreField(&objects,&globals[0],{key},&value));
""")
        source = "def factory(seed):\n    return callback(y=seed,x=2)\n\ndef f(self,x,y):\n    return self.number+x*10+y\n"
        namespace={}
        exec(source,namespace)
        namespace["callback"]=MethodType(namespace["f"],SimpleNamespace(number=100))
        key = source_artifact(source).compact_document["constants"].index("callback")
        check_source(source,namespace=namespace,bindings=True,setup=f"""
    CHECK(PyZ80Target_AllocateNode(&objects,PYZ80_TARGET_NODE_OBJECT,0,&value));
    result=integer(100);CHECK(PyZ80Target_StoreField(&objects,&value,@number@,&result));
    CHECK(PyZ80Target_Callable(&objects,1,&value,&result));
    CHECK(PyZ80Target_StoreField(&objects,&globals[0],{key},&result));
""")

    def test_defaults_keywords_and_positional_only(self):
        sources = [
            "def factory(seed):\n    def f(x=seed):\n        return x\n    return f() + f(2)\n",
            "def factory(seed):\n    def f(a,b):\n        return a*10+b\n    return f(b=2,a=seed)\n",
            "def factory(seed):\n    def f(a=seed,*,b=3):\n        return a*10+b\n    return f() + f(b=4) + f(2,b=5)\n",
            "def factory(seed):\n    def f(a,/,b=3,*,c):\n        return a*100+b*10+c\n    return f(seed,c=4)\n",
            "def factory(seed):\n    def f(*,x=seed):\n        return x\n    return f() + f(x=2)\n",
            "def factory(seed):\n    def f(x=None):\n        return bool(x)\n    return f()\n",
            "def factory(seed):\n    f = lambda x=seed, *, y=3: x*10+y\n    return f() + f(y=5,x=2)\n",
            "def factory(seed):\n    f = lambda x,/,*,y: x*10+y\n    return f(seed,y=5)\n",
            "def factory(seed):\n    f = lambda x=seed: x\n    seed = 99\n    return f()\n",
        ]
        for source in sources:
            with self.subTest(source=source):
                check_source(source, bindings=True)

    def test_argument_order_and_single_callee_lookup(self):
        sources = [
            '''def factory(seed):
    seen = [0]
    def side(x):
        seen[0] = seen[0]*10+x
        return x
    def f(a,b):
        return a*10+b
    answer = f(b=side(1),a=side(2))
    return seen[0]*100+answer
''',
            '''def factory(seed):
    seen = [0]
    def side(x):
        seen[0] = seen[0]*10+x
        return x
    def f(a=side(1),b=side(2),*,c=side(3)):
        return a*100+b*10+c
    return seen[0]*1000+f()
''',
            '''def factory(seed):
    def a(x):
        return 10
    def b(x):
        return 20
    slot = [a]
    def argument():
        slot[0] = b
        return 42
    return slot[0](argument())
''',
        ]
        for source in sources:
            with self.subTest(source=source):
                check_source(source,bindings=True)

    def test_default_evaluated_once_and_retains_mutable_identity(self):
        source = '''def factory(seed):
    seen = [0]
    def default():
        seen[0] = seen[0] + 1
        return [seed]
    def f(x=default()):
        x[0] = x[0] + 2
        return x[0]
    a = f()
    b = f()
    c = f([100])
    d = f()
    return seen[0]*10000 + a*100 + b + c + d
'''
        check_source(source, bindings=True, repetitions=1000)

    def test_errors_do_not_invoke_external_provider(self):
        prefix = "def factory(seed):\n    def f(a,/,b=3,*,c):\n        return a+b+c\n    return "
        for call in ("f()", "f(a=1,c=2)", "f(1,2,3,c=4)", "f(1,2,b=3,c=4)", "f(1,c=2,z=9)", "f(1)"):
            with self.subTest(call=call):
                check_source(prefix + call + "\n", bindings=True)
        check_source("def factory(seed):\n    f = lambda y: y\n    return f(y=seed)\n",
                     expected_error=True, bindings=False)


if __name__ == "__main__":
    unittest.main()
