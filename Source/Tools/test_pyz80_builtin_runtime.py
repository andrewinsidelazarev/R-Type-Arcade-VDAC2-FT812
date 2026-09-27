"""CPython source versus C VM: builtin binding, protocols and bounded range."""
import ast
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from generate_pzvt_target_adapters import build_adapter_specs
from pyz80_compiler.whole_program_vm_backend import CompactTargetVMOracle, WholeProgramVMError
from test_pyz80_callable_runtime import compile_run, PRELUDE, TCC
from test_pyz80_gc_runtime import source_header
from test_pyz80_scope_runtime import source_artifact
from test_pyz80_target_object_runtime import RUNTIME, SDCC


def check_source(source, *, setup="", namespace=None, expected_error=False, repetitions=1, python_argument=7, bindings=False, postcheck="", c_helpers="", before_run=""):
    namespace = dict(namespace or {})
    exec(source, namespace)
    try:
        expected = namespace["factory"](python_argument)
    except (TypeError, ValueError, AttributeError, UnboundLocalError):
        expected_error = True
        expected = 0
    if expected_error:
        expected = 0
    elif type(expected) not in (int, bool):
        raise AssertionError("fixture must produce a scalar")
    artifact = source_artifact(source)
    constants = artifact.compact_document["constants"]
    for name in ("len", "flag", "missing", "number"):
        setup = setup.replace(f"@{name}@", str(constants.index(name)) if name in constants else "65535")
        postcheck = postcheck.replace(f"@{name}@", str(constants.index(name)) if name in constants else "65535")
    postcheck = postcheck.replace("@python_number@", str(getattr(python_argument,"number",0)))
    compile_run(PRELUDE + '#include "pyz80_target_gc.h"\n#include "pyz80_target_builtins.h"\n' +
        ('#include "pyz80_target_call_binding.h"\n' if bindings else '') +
        source_header(source) + c_helpers + f"\n#define EXPECTED {int(expected) & 0xffffffff}UL\n#define ERROR {int(expected_error)}\n" + r'''
static uint16_t external_calls;
static uint8_t external(void *ctx, PyZ80VM *vm, uint16_t id, uint16_t dest,
    const PyZ80VMValue *args, uint8_t count, uint32_t raw, PyZ80VMValue *result) {
    (void)ctx;(void)vm;(void)id;(void)dest;(void)args;(void)count;(void)raw;
    ++external_calls;*result=integer(999);return 1;
}
int main(void) {
    PyZ80TargetContext objects;PyZ80TargetScopes scopes;
    PyZ80TargetNode nodes[48];PyZ80TargetField fields[16];
    PyZ80VMValue items[256],frames[8],globals[FUNCTIONS],arg,result,value,binding_args[12];
    uint8_t marks[48],status;uint16_t queue[48],fm[16],im[256],i,iteration,steps;
    PyZ80TargetGC gc={marks,queue,fm,im,48,16,256,0,0,0,0};
    PyZ80VM vm;PyZ80VMAdapter adapter;PyZ80VMLimits limits={8,0,128,12};
    PyZ80VMMemoryImage memory={bytes,sizeof(bytes)};
    PyZ80VMImage image={PyZ80VM_MemoryRead,&memory,sizeof(bytes),proof};
    union {uint32_t align;uint8_t bytes[16384];} arena;
    PyZ80Target_Init(&objects,nodes,48,fields,16,items,256,specs,ALLOCATE+1,ops,OP_COUNT,external,0);
    objects.field_keys=keys;objects.field_key_count=sizeof(keys)/sizeof(keys[0]);
    objects.function_count=FUNCTIONS;objects.positional_call_arities=arities;
    objects.class_symbols=fixture_class_symbols;
    objects.builtin_symbols=builtin_symbols;objects.builtin_symbol_count=BUILTIN_COUNT;
    objects.positional_call_flags=positional_calls;PyZ80Target_EnableBuiltins(&objects);
    objects.call_signatures=signatures;objects.parameter_names=parameter_names;
    objects.parameter_name_count=PARAMETER_NAMES;objects.call_layout_offsets=call_layout_offsets;
    objects.call_layout_keys=call_layout_keys;objects.call_layout_key_count=CALL_LAYOUT_KEYS;
    CHECK(PyZ80Target_AllocateNode(&objects,PYZ80_TARGET_NODE_OBJECT,0,&globals[0]));
    for(i=1;i<FUNCTIONS;++i)globals[i]=globals[0];
    arg=integer(7);value=integer(0);
''' + setup + r'''
    adapter=PyZ80Target_VMAdapter(&objects);
    CHECK(PyZ80VM_Init(&vm,&image,&adapter,arena.bytes,sizeof(arena.bytes),&limits)==PYZ80_VM_IDLE);
    CHECK(PyZ80Target_AttachScopes(&scopes,&objects,&vm,frames,8,globals,FUNCTIONS));
''' + ('    CHECK(PyZ80Target_AttachCallBinding(&scopes,binding_args,12));\n' if bindings else '') + before_run +
        f"    for(iteration=0;iteration<{repetitions};++iteration) {{\n" + r'''
        CHECK(PyZ80VM_StartArgs(&vm,0,&arg,1)==PYZ80_VM_RUNNING);
        status=PYZ80_VM_RUNNING;steps=0;
        while(status==PYZ80_VM_RUNNING && ++steps<10000)
            status=PyZ80Target_RunSlice(&objects,&vm,&scopes,&arg,1,&gc,1,&result);
        if(ERROR) CHECK(status==PYZ80_VM_ERROR);
        else {
            if(status!=PYZ80_VM_RETURNED)printf("vm status=%d error=%d steps=%d\n",status,vm.error,steps);
            CHECK(status==PYZ80_VM_RETURNED && result.payload==EXPECTED);
            CHECK(objects.item_used==0); /* Result is scalar; dead temporary slices reclaimed. */
        }
        CHECK(external_calls==0); /* Even an invalid recognized call cannot use permissive fallback. */
''' + postcheck + r'''
    }
    return 0;
}
''', gc=True, builtins=True, bindings=bindings)


@unittest.skipUnless(TCC, "host compiler unavailable")
class BuiltinRuntimeTests(unittest.TestCase):
    def test_local_opcode_stops_at_its_owner_in_independent_oracle(self):
        artifact = source_artifact("def factory(seed):\n    return seed\n")
        self.assertEqual(CompactTargetVMOracle(artifact).run(0,[23]),23)
        artifact = source_artifact("def factory(seed):\n    return len\n    len = seed\n")
        with self.assertRaisesRegex(WholeProgramVMError,"unbound Python local"):
            CompactTargetVMOracle(artifact).run(0,[23])

    def test_builtin_expressions_taken_from_game_source(self):
        root = Path(__file__).resolve().parents[2] / "Source/Python/rtype_port"
        game = ast.parse((root/"game.py").read_text(encoding="utf-8"))
        # Keep the source expression, including mask and bool(), unchanged.
        directions = [node.value for node in ast.walk(game) if isinstance(node, ast.Assign)
            and len(node.targets)==1 and isinstance(node.targets[0],ast.Name)
            and node.targets[0].id in ("up","down") and isinstance(node.value,ast.Call)
            and isinstance(node.value.func,ast.Name) and node.value.func.id=="bool"
            and any(isinstance(n,ast.Name) and n.id=="rom_direction" for n in ast.walk(node.value))]
        self.assertEqual(len(directions),2)
        for expression in directions:
            for direction in (0,4,8,12):
                check_source("def factory(seed):\n    rom_direction = seed\n    return " + ast.unparse(expression)+"\n",
                             setup=f"arg=integer({direction});", python_argument=direction)
        enemies = ast.parse((root/"enemies.py").read_text(encoding="utf-8"))
        world = next(node for node in enemies.body if isinstance(node,ast.ClassDef) and node.name=="M72EnemyWorld")
        draw = next(node for node in world.body if isinstance(node,ast.FunctionDef) and node.name=="draw")
        expressions = [node for node in ast.walk(draw) if isinstance(node,ast.Call)
            and isinstance(node.func,ast.Name) and node.func.id=="getattr"]
        expression = next(node for node in expressions if isinstance(node.args[1],ast.Constant)
                          and node.args[1].value=="render_ready")
        source = "def factory(seed):\n    enemy = seed\n    return " + ast.unparse(expression)+"\n"
        check_source(source, setup="CHECK(PyZ80Target_AllocateNode(&objects,PYZ80_TARGET_NODE_OBJECT,0,&arg));")
        key = source_artifact(source).compact_document["constants"].index("render_ready")
        check_source(source, python_argument=type("Plain",(),{"render_ready":False})(), setup=f"""
    CHECK(PyZ80Target_AllocateNode(&objects,PYZ80_TARGET_NODE_OBJECT,0,&arg));
    value.kind=PYZ80_VM_VALUE_BOOL;value.payload=0;
    CHECK(PyZ80Target_StoreField(&objects,&arg,{key},&value));
""")

    def test_getattr_absence_is_distinct_from_corrupt_storage(self):
        compile_run(PRELUDE + '#include "pyz80_target_builtins.h"\n' + r'''
int main(void) {
    PyZ80TargetContext objects;PyZ80TargetNode nodes[2];PyZ80TargetField fields[2];
    PyZ80VMValue items[1],args[4],result;uint8_t flags[]={1};
    PyZ80TargetAdapterSpec specs[]={{PYZ80_TARGET_UNSUPPORTED,4,0}};
    PyZ80TargetBuiltinSpec names[]={{0,PYZ80_BUILTIN_GETATTR}};
    PyZ80Target_Init(&objects,nodes,2,fields,2,items,1,specs,1,0,0,0,0);
    objects.builtin_symbols=names;objects.builtin_symbol_count=1;objects.positional_call_flags=flags;
    PyZ80Target_EnableBuiltins(&objects);
    args[0]=integer(PYZ80_BUILTIN_GETATTR);args[0].kind=PYZ80_VM_VALUE_BUILTIN;args[0].symbol=0;
    CHECK(PyZ80Target_AllocateNode(&objects,PYZ80_TARGET_NODE_OBJECT,0,&args[1]));
    args[2]=integer(0);args[2].kind=PYZ80_VM_VALUE_SYMBOL;args[2].symbol=1;args[3]=integer(17);
    CHECK(PyZ80Target_Invoke(&objects,0,0,0,args,4,0,&result) && result.payload==17);
    nodes[0].field_head=3;
    CHECK(!PyZ80Target_Invoke(&objects,0,0,0,args,4,0,&result));
    nodes[0].field_head=0;nodes[0].generation++;
    CHECK(!PyZ80Target_Invoke(&objects,0,0,0,args,4,0,&result));
    return 0;
}
''', builtins=True)

    def test_source_scalars_aliases_strings_and_iteration(self):
        expressions = ["bool()", "bool(None)", "bool(False)", "bool(7)", "bool('')", "bool('я')",
                       "bool([])", "bool([0])", "bool(())", "bool(range(0))", "bool(range(-3))",
                       "bool(range(2))", "bool(len)", "len('')", "len('Aя😀')", "len([1,2,3])",
                       "len((1,2))", "len(range(7))", "len(range(7,-8,-3))", "len(range(8,1))",
                       "len(range(2147483647,(-2147483647-1),(-2147483647-1)))", "len(range(True))",
                       "len(range(65535))", "7 if '' else 9"]
        for expression in expressions:
            with self.subTest(expression=expression):
                check_source(f"def factory(seed):\n    return {expression}\n")
        sources = [
            "def factory(seed):\n    f = len\n    return f([1,2,3])\n",
            "def factory(seed):\n    len = lambda x: seed\n    return len([])\n",
            "def factory(seed):\n    def len(x):\n        return seed + 2\n    return len([])\n",
            "def factory(seed):\n    f = lambda x: len([x,seed])\n    return f(9)\n",
            "def factory(seed):\n    values = [x * 2 for x in range(9,-4,-3)]\n    return len(values) + values[3]\n",
            "def factory(seed):\n    values = [x for x in range(2147483647,(-2147483647-1),(-2147483647-1))]\n    return values[1]\n",
            "def factory(seed):\n    values = [x for x in range((-2147483647-1),2147483647,2147483647)]\n    return values[2]\n",
            "def factory(seed):\n    x = 0\n    for y in range(8):\n        x = x + y\n    return x\n",
        ]
        for source in sources:
            with self.subTest(source=source):
                check_source(source)

    def test_invalid_calls_and_unbound_locals_never_fall_back(self):
        for expression in ("len()", "len(7)", "len([], [])", "bool(1,2)", "bool(x=1)",
                           "range()", "range(1,2,0)", "range(1,2,3,4)", "getattr(seed, 'x')"):
            with self.subTest(expression=expression):
                check_source(f"def factory(seed):\n    return {expression}\n")
        # Large valid Python ranges require another width backend, not truncation.
        check_source("def factory(seed):\n    return len(range(65536))\n", expected_error=True)
        check_source("def factory(seed):\n    x = len([])\n    len = seed\n    return x\n")
        # Even an assignment after return makes the name a Python local.
        check_source("def factory(seed):\n    return len([])\n    len = seed\n")

    def test_module_shadowing_and_plain_getattr(self):
        check_source("def factory(seed):\n    return len\n", namespace={"len":42},
                     setup="value=integer(42);CHECK(PyZ80Target_StoreField(&objects,&globals[0],@len@,&value));")
        check_source("def factory(seed):\n    return len([])\n", namespace={"len":42},
                     setup="value=integer(42);CHECK(PyZ80Target_StoreField(&objects,&globals[0],@len@,&value));")
        # A closure reads the same actual module mapping, not a copied snapshot.
        check_source("def factory(seed):\n    f = lambda: len\n    return f()\n", namespace={"len":42},
                     setup="value=integer(42);CHECK(PyZ80Target_StoreField(&objects,&globals[0],@len@,&value));")
        check_source("def factory(seed):\n    return getattr(seed, 'missing', 17)\n",
                     setup="CHECK(PyZ80Target_AllocateNode(&objects,PYZ80_TARGET_NODE_OBJECT,0,&arg));")
        source = "def factory(seed):\n    return getattr(seed, 'number', 17)\n"
        # CPython reference receives the equivalent object via a wrapper literal.
        namespace = {"object_value": type("Plain", (), {"number":23})()}
        source = "def factory(seed):\n    return getattr(object_value, 'number', 17)\n"
        artifact = source_artifact(source)
        key = artifact.compact_document["constants"].index("object_value")
        check_source(source, namespace=namespace, setup=f"""
    CHECK(PyZ80Target_AllocateNode(&objects,PYZ80_TARGET_NODE_OBJECT,0,&value));
    CHECK(PyZ80Target_StoreField(&objects,&globals[0],{key},&value));
    result=integer(23);CHECK(PyZ80Target_StoreField(&objects,&value,@number@,&result));
""")

    def test_range_and_builtin_handles_survive_1000_gc_runs(self):
        check_source("def factory(seed):\n    f = len\n    values = [x+seed for x in range(12)]\n    return f(values)+values[11]\n",
                     repetitions=1000)

    def test_generator_only_marks_complete_positional_layouts(self):
        rows = [{"op":"python-call", "argument_count":2, "attributes":{"argument_layout":layout}}
                for layout in ([['positional',None]], [['keyword','x']], [['star-positional',None]], [], None)]
        plan=build_adapter_specs(rows,["len","range","x"])
        self.assertEqual(plan["positional_call_flags"],[1,0,0,0,0])
        self.assertEqual(plan["unsupported"]["python-call"],5)

    @unittest.skipUnless(SDCC, "Z80 compiler unavailable")
    def test_sdcc_no_static_scratch(self):
        with tempfile.TemporaryDirectory(prefix="pz-builtins-z80-") as raw:
            directory=Path(raw)
            for name in ("pyz80_whole_program_vm.h","pyz80_target_object_runtime.h",
                         "pyz80_target_builtins.h","pyz80_target_builtins.c","pyz80_target_deque.h","pyz80_target_buffers.h"):
                shutil.copy2(RUNTIME/name,directory/name)
            environment=os.environ.copy()
            environment["PATH"]=str(SDCC.parent)+os.pathsep+environment.get("PATH","")
            run=subprocess.run([str(SDCC),"-mz80","--std-c11","--sdcccall","1","--stack-auto",
                "--opt-code-speed","-c","pyz80_target_builtins.c"],cwd=directory,env=environment,
                capture_output=True,text=True,timeout=240)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            self.assertIn("A _DATA size 0 ",(directory/"pyz80_target_builtins.rel").read_text())


if __name__ == "__main__":
    unittest.main()
