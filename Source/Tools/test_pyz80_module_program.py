"""Unmodified module AST -> PZVT -> C module mappings, compared with exec()."""
import ast
import copy
from pathlib import Path
import unittest

from pyz80_compiler.function_cfg import lower_python_module_cfg, FunctionCFGError
from pyz80_compiler.module_program import build_module_program
from pyz80_compiler.whole_program_vm_backend import build_whole_program_vm, _sha256_json, WholeProgramVMError
from test_pyz80_callable_runtime import PRELUDE, compile_run, TCC
from test_pyz80_gc_runtime import artifact_header
from generate_pzvt_target_adapters import build_adapter_specs, render_adapter_tables


def module_check(sources, *, error=False, after="", c_helpers="", repetitions=1, expected_external=0, classes=False,
                 max_args=24, heap_scale=1):
    program = build_module_program({name: (Path(name + '.py'), source) for name, source in sources.items()})
    checks = []
    constants = program.artifact.compact_document['constants']
    plan = build_adapter_specs(program.artifact.adapter_table, constants,
        program.artifact.target_coverage['function_id_table'], program.artifact.target_coverage['function_call_signatures'])
    generated_h, generated_c = render_adapter_tables(plan, program.artifact.target_coverage['positional_call_arities'])
    for index, (name, source) in enumerate(sources.items()):
        namespace = {'__name__': name} if classes else {}
        try:
            exec(compile(source, name + '.py', 'exec', dont_inherit=True, optimize=0), namespace)
        except (NameError, TypeError, AttributeError):
            error = True
        if not error:
            for key, value in namespace.items():
                if key == '__builtins__' or type(value) not in (int, bool, str, type(None)):
                    continue
                checks.append(f'CHECK(PyZ80Target_LoadField(&objects,&modules[{index}],{constants.index(key)},&value));')
                if value is None:
                    checks.append('CHECK(value.kind==PYZ80_VM_VALUE_NONE);')
                elif type(value) is str:
                    checks.append(f'CHECK(value.kind==PYZ80_VM_VALUE_SYMBOL && value.symbol=={constants.index(value)});')
                else:
                    kind = 'BOOL' if type(value) is bool else 'I32'
                    checks.append(f'CHECK(value.kind==PYZ80_VM_VALUE_{kind} && value.payload=={int(value)&0xffffffff}UL);')
    for constant in constants:
        if isinstance(constant, str):
            after = after.replace('@' + constant + '@', str(constants.index(constant)))
    class_setup = ''
    if classes:
        for index, name in enumerate(sources):
            class_setup += f'value.kind=PYZ80_VM_VALUE_SYMBOL;value.symbol={constants.index(name)};CHECK(PyZ80Target_StoreField(&objects,&modules[{index}],{constants.index("__name__")},&value));\n'
        class_setup += 'CHECK(PyZ80Target_AttachClasses(&classes,&scopes,class_frames,class_roots,12,class_routes));'
    compile_run((PRELUDE + ('#include "pyz80_target_classes.h"\n' if classes else '') + '#include "pyz80_target_gc.h"\n#include "pyz80_target_builtins.h"\n#include "pyz80_target_call_binding.h"\n#include "pyz80_target_adapter_plan_generated.h"\n' +
        artifact_header(program.artifact) +
        'static const uint16_t function_modules[]={' + ','.join(map(str, program.function_module_ids)) + '};\n' +
        'static const uint16_t entries[]={' + ','.join(map(str, program.initializer_functions)) + '};\n' +
        f'#define MODULES {len(sources)}\n#define ERROR {int(error)}\n#define EXTERNAL {expected_external}\n#define REPETITIONS {repetitions}\n#define MAX_ARGS {max_args}\n#define HEAP_SCALE {heap_scale}\n' + c_helpers + r'''
static unsigned external_calls;
static uint8_t external(void *ctx, PyZ80VM *vm, uint16_t a, uint16_t d,
    const PyZ80VMValue *args, uint8_t n, uint32_t raw, PyZ80VMValue *result) {
    (void)ctx;(void)vm;(void)a;(void)d;(void)args;(void)n;(void)raw;(void)result;
    ++external_calls;return 0;
}
int main(void) {
CLASS_DECLARATIONS
    PyZ80TargetContext objects;PyZ80TargetScopes scopes;
    PyZ80TargetNode nodes[128*HEAP_SCALE];PyZ80TargetField fields[128*HEAP_SCALE];
    PyZ80VMValue items[512*HEAP_SCALE],frames[12],globals[FUNCTIONS],modules[MODULES],scratch[MAX_ARGS],value,result;
    uint8_t marks[128*HEAP_SCALE],status;uint16_t queue[128*HEAP_SCALE],fm[128*HEAP_SCALE],im[512*HEAP_SCALE],i,j,iteration;
    PyZ80TargetGC gc={marks,queue,fm,im,128*HEAP_SCALE,128*HEAP_SCALE,512*HEAP_SCALE,0,0,0,0};
    PyZ80VM vm;PyZ80VMAdapter adapter;PyZ80VMLimits limits={12,0,192,MAX_ARGS};
    PyZ80VMMemoryImage memory={bytes,sizeof(bytes)};
    PyZ80VMImage image={PyZ80VM_MemoryRead,&memory,sizeof(bytes),proof};
    union {uint32_t align;uint8_t bytes[32768];} arena;
    PyZ80Target_Init(&objects,nodes,128*HEAP_SCALE,fields,128*HEAP_SCALE,items,512*HEAP_SCALE,specs,ALLOCATE+1,ops,OP_COUNT,external,0);
    objects.field_keys=keys;objects.field_key_count=sizeof(keys)/sizeof(keys[0]);objects.function_count=FUNCTIONS;
    objects.positional_call_arities=arities;objects.positional_call_flags=positional_calls;
    objects.builtin_symbols=builtin_symbols;objects.builtin_symbol_count=BUILTIN_COUNT;PyZ80Target_EnableBuiltins(&objects);
    objects.call_signatures=signatures;objects.parameter_names=parameter_names;objects.parameter_name_count=PARAMETER_NAMES;
    objects.call_layout_offsets=call_layout_offsets;objects.call_layout_keys=call_layout_keys;objects.call_layout_key_count=CALL_LAYOUT_KEYS;
    PyZ80Generated_Bind(&objects); /* Execute the production-emitted C tables. */
    for(i=0;i<MODULES;++i)CHECK(PyZ80Target_AllocateNode(&objects,PYZ80_TARGET_NODE_OBJECT,0,&modules[i]));
    for(i=0;i<FUNCTIONS;++i)globals[i]=modules[function_modules[i]];
    adapter=PyZ80Target_VMAdapter(&objects);
    CHECK(PyZ80VM_Init(&vm,&image,&adapter,arena.bytes,sizeof(arena.bytes),&limits)==PYZ80_VM_IDLE);
    CHECK(PyZ80Target_AttachScopes(&scopes,&objects,&vm,frames,12,globals,FUNCTIONS));
    CHECK(PyZ80Target_AttachCallBinding(&scopes,scratch,MAX_ARGS));
CLASS_SETUP
    for(iteration=0;iteration<REPETITIONS;++iteration) {
        for(i=0;i<MODULES;++i) {
            CHECK(PyZ80VM_StartArgs(&vm,entries[i],0,0)==PYZ80_VM_RUNNING);
            status=PYZ80_VM_RUNNING;j=0;
            while(status==PYZ80_VM_RUNNING && ++j<10000)
                status=PyZ80Target_RunSlice(&objects,&vm,&scopes,modules,MODULES,&gc,1,&result);
            if(ERROR)CHECK(status==PYZ80_VM_ERROR);
            else {if(status!=PYZ80_VM_RETURNED){printf("status=%u error=%u depth=%u step=%u external=%u\n",status,vm.error,vm.call_depth,j,external_calls);for(j=0;j<vm.call_depth;++j)printf("frame=%u unit=%u pc=%lu\n",j,vm.frames[j].unit,(unsigned long)vm.frames[j].pc);}CHECK(status==PYZ80_VM_RETURNED && result.kind==PYZ80_VM_VALUE_NONE);}
        }
''' + '\n'.join(checks) + '\n' + after + r'''
    }
    CHECK(external_calls==EXTERNAL);
    return 0;
}
''').replace('CLASS_DECLARATIONS', 'PyZ80TargetClasses classes;PyZ80TargetClassFrame class_frames[12];PyZ80VMValue class_roots[36];uint16_t class_routes[PYZ80_GENERATED_ADAPTER_COUNT];' if classes else '').replace('CLASS_SETUP',class_setup), gc=True, builtins=True, bindings=True, classes=classes,
        extra_sources={'pyz80_target_adapter_plan_generated.h': generated_h, 'pyz80_target_adapter_plan_generated.c': generated_c})
    return program


class ModuleProgramTests(unittest.TestCase):
    def test_module_ast_is_sealed_and_not_a_function_wrapper(self):
        source = 'x=1\n'
        node = ast.parse(source)
        cfg = lower_python_module_cfg(node, source_path=Path('m.py'), source_text=source)
        self.assertEqual(cfg.signature['execution_kind'], 'module-body')
        self.assertEqual(cfg.function_name, '<module>')
        node.body[0].value.value = 2
        with self.assertRaisesRegex(FunctionCFGError, 'module AST differs'):
            lower_python_module_cfg(node, source_path=Path('m.py'), source_text=source)
        with self.assertRaises(SyntaxError):
            lower_python_module_cfg(ast.parse('return 3'), source_path=Path('m.py'), source_text='return 3')

    def test_definitions_are_not_added_to_static_reachability(self):
        program = build_module_program({'m': (Path('m.py'), 'def unused():\n    return 42\n')})
        document = program.artifact.document
        self.assertEqual(document['proven_reachable_callable_ids'], ['m::<module>@1'])
        self.assertEqual(document['definition_callable_ids'], ['m::unused@1'])
        graph = copy.deepcopy(program.graph)
        graph['callable_inventory']['definition_callable_ids'].append('m::<module>@1')
        graph['semantic_sha256'] = _sha256_json({k:v for k,v in graph.items() if k!='semantic_sha256'})
        with self.assertRaisesRegex(WholeProgramVMError, 'overlap or duplicate'):
            build_whole_program_vm(graph)

    @unittest.skipUnless(TCC, 'host compiler unavailable')
    def test_module_defaults_snapshot_and_late_global_lookup(self):
        module_check({'m': 'x=7\ndef f(y=x,*,z=2):\n    return y+x+z\nx=8\nanswer=f(z=3)\n'})

    @unittest.skipUnless(TCC, 'host compiler unavailable')
    def test_module_mutable_defaults_and_redefinition_keep_old_callable(self):
        module_check({'m': '''counter=0
def default():
    global counter
    counter=counter+1
    return [counter]
def f(x=default()):
    x[0]=x[0]+1
    return x[0]
first=f()
alias=f
def f(x=30):
    return x
second=alias()
third=f()
answer=first*100+second*10+third
'''}, repetitions=1000)

    @unittest.skipUnless(TCC, 'host compiler unavailable')
    def test_explicit_global_does_not_capture_same_named_enclosing_local(self):
        module_check({'m': '''x=10
def outer():
    x=20
    def f():
        global x
        x=x+1
        return x
    return f()
answer=outer()
'''})

    @unittest.skipUnless(TCC, 'host compiler unavailable')
    def test_two_modules_with_identical_function_and_variable_names(self):
        source='x={value}\ndef f(y=x):\n    return y+x\nx=x+1\nanswer=f()\n'
        module_check({'a': source.format(value=7), 'b': source.format(value=100)})

    @unittest.skipUnless(TCC, 'host compiler unavailable')
    def test_foreign_function_global_writes_use_its_definition_module(self):
        module_check({'a': '''counter=7
def f():
    global counter
    counter=counter+1
    return counter
''', 'b': '''counter=100
def run(cb):
    global counter
    counter=cb()
    return counter
'''}, after=r'''
    {
        PyZ80VMValue cb,runner;
        CHECK(PyZ80Target_LoadField(&objects,&modules[0],@f@,&cb));
        CHECK(PyZ80Target_LoadField(&objects,&modules[1],@run@,&runner));
        for(j=0;j<1000;++j) {
            CHECK(PyZ80VM_StartClosure(&vm,nodes[(uint16_t)runner.payload-1].class_symbol,&runner,&cb,1)==PYZ80_VM_RUNNING);
            do {status=PyZ80Target_RunSlice(&objects,&vm,&scopes,modules,MODULES,&gc,1,&result);} while(status==PYZ80_VM_RUNNING);
            CHECK(status==PYZ80_VM_RETURNED && result.payload==8u+j);
            CHECK(PyZ80Target_LoadField(&objects,&modules[0],@counter@,&value) && value.payload==8u+j);
            CHECK(PyZ80Target_LoadField(&objects,&modules[1],@counter@,&value) && value.payload==8u+j);
        }
    }
''')

    @unittest.skipUnless(TCC, 'host compiler unavailable')
    def test_name_error_keeps_prior_effects_and_stops_later_stores(self):
        module_check({'m':'x=1\nbefore=missing\nx=2\n'}, expected_external=1,
            after='CHECK(PyZ80Target_LoadField(&objects,&modules[0],@x@,&value) && value.payload==1);')

    @unittest.skipUnless(TCC, 'host compiler unavailable')
    def test_store_capacity_error_never_falls_back(self):
        source='\n'.join(f'name{i}={i}' for i in range(129))
        module_check({'m': source}, error=True,
            after='CHECK(objects.field_used==128);CHECK(PyZ80Target_LoadField(&objects,&modules[0],@name127@,&value) && value.payload==127);')

    @unittest.skipUnless(TCC, 'host compiler unavailable')
    def test_generator_definition_is_not_miscompiled_as_an_ordinary_call(self):
        program=module_check({'m':'touched=0\ndef values():\n    global touched\n    touched=99\n    yield 7\nanswer=values()\n'},
            error=True, expected_external=0,
            after='CHECK(PyZ80Target_LoadField(&objects,&modules[0],@touched@,&value) && value.payload==0);'
                  'CHECK(PyZ80Target_FindField(&objects,&modules[0],@answer@,&value)==2);')
        self.assertTrue(any(row['op']=='generator-next-enter' for row in program.artifact.adapter_table))
        self.assertEqual(len(program.artifact.target_coverage['generator_lowering']['bodies']),1)

    @unittest.skipUnless(TCC, 'host compiler unavailable')
    def test_module_loops_lambda_and_builtin_shadowing(self):
        module_check({'m': '''total=0
for i in range(5):
    total=total+i
f=lambda x=total: x+total
total=20
before=f()
len=lambda x: 7
answer=len([])+before
'''})

    @unittest.skipUnless(TCC, 'host compiler unavailable')
    def test_module_names_do_not_use_function_unbound_local_rules(self):
        module_check({'m': 'before=len([1,2])\nlen=7\nanswer=before+len\n'})

    @unittest.skipUnless(TCC, 'host compiler unavailable')
    def test_module_docstring_and_package_source(self):
        path=Path(__file__).resolve().parents[2]/'Source/Python/rtype_port/__init__.py'
        module_check({'rtype_port':path.read_text(encoding='utf-8')})
        module_check({'m':'"module documentation"\nx=2\n'})

    def test_expanded_bases_and_metaclass_remain_explicit_blockers(self):
        for source in ('class A(*bases):\n    pass\n', 'class A(metaclass=Meta):\n    x=1\n'):
            cfg=lower_python_module_cfg(ast.parse(source),source_path=Path('m.py'),source_text=source)
            self.assertTrue(cfg.blockers)

    def test_zero_local_blocked_body_decodes_without_invented_destination(self):
        program=build_module_program({'m':(Path('m.py'),'class A(metaclass=Meta):\n    pass\n')})
        self.assertTrue(program.graph['callable_inventory']['callables'][0]['cfg']['blockers'])
        self.assertTrue(any(row['op'].startswith('blocked-') for row in program.artifact.adapter_table))


if __name__=='__main__':
    unittest.main()
