"""Real CPython imports versus generated PZVT, native C loader and per-step GC."""
from __future__ import annotations

import importlib
import importlib.abc
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

from generate_pzvt_target_adapters import build_adapter_specs, render_adapter_tables
from pyz80_compiler.module_program import build_module_program
from pyz80_compiler.module_imports import build_import_plan, render_import_plan, collect_source_imports
from test_pyz80_callable_runtime import PRELUDE, TCC, compile_run
from test_pyz80_gc_runtime import artifact_header


class SourceFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def __init__(self, sources):
        self.sources = sources
        self.executed = {}

    def find_spec(self, fullname, path=None, target=None):
        if fullname in self.sources:
            return importlib.util.spec_from_loader(fullname, self,
                is_package=self.sources[fullname][0].name == '__init__.py')

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        path, source = self.sources[module.__name__]
        module.__file__ = str(path)
        self.executed[module.__name__] = module
        exec(compile(source, str(path), 'exec', dont_inherit=True, optimize=0), module.__dict__)


def import_check(source_texts, *, packages=(), root='app', after='', expected_external=0,
                 max_depth=12, expect_vm_error=False, repetitions=1, before_attach='',
                 after_attach='', before_slice='', budget=1, c_helpers='', classes=False,
                 dataclasses=False, library_paths=None, max_args=24, heap_scale=1, skip_oracle_modules=(), max_slices=10000,
                 before_dataclasses='', after_dataclasses='', banked=False, generators=False, generator_slots=4,
                 after_slice='', sorting=False, after_sort='', sequences=False, before_sequences='', after_sequences='',
                 defaultdicts=False, before_defaultdict='', after_defaultdict=''):
    sources = {name: ((library_paths or {}).get(name, Path(name.replace('.', '/') + ('/__init__.py' if name in packages else '.py'))), text)
               for name, text in source_texts.items()}
    finder = SourceFinder(sources)
    saved = {name: sys.modules.pop(name) for name in sources if name in sys.modules}
    sys.meta_path.insert(0, finder)
    error = False
    try:
        try:
            importlib.import_module(root)
        except (NameError, ImportError, TypeError, ValueError, AttributeError, RuntimeError, KeyError, IndexError, StopIteration):
            error = True
        loaded = {name: sys.modules[name] for name in sources if name in sys.modules}
    finally:
        sys.meta_path.remove(finder)
        for name in sources:
            sys.modules.pop(name, None)
        sys.modules.update(saved)
    program = build_module_program(sources)
    artifact = program.artifact
    plan = build_import_plan(program)
    import_h, import_c = render_import_plan(plan)
    constants = artifact.compact_document['constants']
    adapters = build_adapter_specs(artifact.adapter_table, constants, artifact.target_coverage['function_id_table'],
                                  artifact.target_coverage['function_call_signatures'])
    adapter_h, adapter_c = render_adapter_tables(adapters, artifact.target_coverage['positional_call_arities'])
    checks = []
    if not expect_vm_error:
        for i, name in enumerate(sources):
            if name in skip_oracle_modules:
                continue
            if name not in loaded:
                checks.append(f'CHECK(states[{i}]==PYZ80_MODULE_EMPTY && modules[{i}].kind==PYZ80_VM_VALUE_NONE);')
                continue
            checks.append(f'CHECK(states[{i}]==PYZ80_MODULE_READY);')
            for key, value in vars(loaded[name]).items():
                if type(value) not in (int, bool, str, type(None)) or key not in constants:
                    continue
                checks.append(f'CHECK(PyZ80Target_LoadField(&objects,&modules[{i}],{constants.index(key)},&value));')
                if value is None:
                    checks.append('CHECK(value.kind==PYZ80_VM_VALUE_NONE);')
                elif type(value) is str:
                    checks.append(f'CHECK(value.kind==PYZ80_VM_VALUE_SYMBOL && value.symbol=={constants.index(value)});')
                else:
                    kind = 'BOOL' if type(value) is bool else 'I32'
                    checks.append(f'CHECK(value.kind==PYZ80_VM_VALUE_{kind} && value.payload=={int(value)&0xffffffff}UL);')
    def substitute(text):
        for i, name in enumerate(sources):
            text = text.replace('$' + name + '$', str(i))
        for i, constant in enumerate(constants):
            if isinstance(constant, str):
                text = text.replace('@' + constant + '@', str(i))
        return text
    after, before_attach, after_attach, before_slice = map(substitute, (after,before_attach,after_attach,before_slice))
    after_slice=substitute(after_slice)
    after_sort=substitute(after_sort)
    before_dataclasses, after_dataclasses = map(substitute, (before_dataclasses,after_dataclasses))
    before_defaultdict, after_defaultdict = map(substitute, (before_defaultdict,after_defaultdict))
    source = PRELUDE.replace('printf("line %d\\n", __LINE__)', 'printf("line %d: %s\\n", __LINE__, #expr)') + '''
#include "pyz80_target_gc.h"
#include "pyz80_target_builtins.h"
#include "pyz80_target_call_binding.h"
#include "pyz80_target_adapter_plan_generated.h"
#include "pyz80_import_plan_generated.h"
''' + artifact_header(artifact) + c_helpers + f'''
#define MODULES {len(sources)}
#define ERROR {int(error or expect_vm_error)}
#define DEPTH {max_depth}
#define ROOT {program.module_names.index(root)}
#define EXTERNAL {expected_external}
#define REPETITIONS {repetitions}
#define BUDGET {budget}
#define HEAP_NODES {256*heap_scale}
#define HEAP_FIELDS {512*heap_scale}
#define HEAP_ITEMS {512*heap_scale}
#define MAX_ARGS {max_args}
#define MAX_SLICES {max_slices}UL
''' + r'''
static unsigned external_calls;
static uint8_t external(void *ctx, PyZ80VM *vm, uint16_t a, uint16_t d,
    const PyZ80VMValue *args, uint8_t n, uint32_t raw, PyZ80VMValue *result) {
    (void)ctx;(void)vm;(void)a;(void)d;(void)args;(void)n;(void)raw;(void)result;
    printf("unhandled adapter=%u destination=%u\n",a,d);
    ++external_calls;return 0;
}
int main(void) {
    PyZ80TargetContext objects;PyZ80TargetScopes scopes;PyZ80TargetImports imports;
    PyZ80TargetNode nodes[HEAP_NODES];PyZ80TargetField fields[HEAP_FIELDS];
    PyZ80VMValue items[HEAP_ITEMS],closures[DEPTH],globals[FUNCTIONS],modules[MODULES],scratch[MAX_ARGS],value,result;
    PyZ80TargetImportFrame frames[DEPTH];uint8_t states[MODULES];
    uint8_t marks[HEAP_NODES],status;uint16_t queue[HEAP_NODES],fm[HEAP_FIELDS],im[HEAP_ITEMS],i,j;
    uint32_t step_count;
    PyZ80TargetGC gc={marks,queue,fm,im,HEAP_NODES,HEAP_FIELDS,HEAP_ITEMS,0,0,0,0};
    PyZ80VM vm;PyZ80VMAdapter adapter;PyZ80VMLimits limits={DEPTH,0,192,MAX_ARGS};
    PyZ80VMMemoryImage memory={bytes,sizeof(bytes)};
    PyZ80VMImage image={PyZ80VM_MemoryRead,&memory,sizeof(bytes),proof};
    union {uint32_t align;uint8_t bytes[32768];} arena;
    PyZ80Target_Init(&objects,nodes,HEAP_NODES,fields,HEAP_FIELDS,items,HEAP_ITEMS,specs,ALLOCATE+1,ops,OP_COUNT,external,0);
    PyZ80Generated_Bind(&objects);PyZ80Target_EnableBuiltins(&objects);
    adapter=PyZ80Target_VMAdapter(&objects);
    CHECK(PyZ80VM_Init(&vm,&image,&adapter,arena.bytes,sizeof(arena.bytes),&limits)==PYZ80_VM_IDLE);
    memset(globals,0,sizeof(globals));
    CHECK(PyZ80Target_AttachScopes(&scopes,&objects,&vm,closures,DEPTH,globals,FUNCTIONS));
    CHECK(PyZ80Target_AttachCallBinding(&scopes,scratch,MAX_ARGS));
''' + before_attach + r'''
    CHECK(PyZ80Target_AttachImports(&imports,&scopes,&PyZ80GeneratedImportPlan,modules,states,globals,frames,DEPTH));
    CHECK(PyZ80Target_ImportStorageBytes(&PyZ80GeneratedImportPlan,DEPTH)==sizeof(imports)+sizeof(modules)+sizeof(states)+sizeof(globals)+sizeof(frames));
''' + after_attach + r'''
    for(i=0;i<REPETITIONS;++i) {
        CHECK(PyZ80Target_StartModule(&imports,ROOT)==PYZ80_VM_RUNNING);
''' + before_slice + r'''
        status=PYZ80_VM_RUNNING;step_count=0;
        while(status==PYZ80_VM_RUNNING && ++step_count<=MAX_SLICES) {
            status=PyZ80Target_RunSlice(&objects,&vm,&scopes,modules,MODULES,&gc,BUDGET,&result);
            if(status==PYZ80_VM_ERROR && !ERROR)for(j=0;j<vm.call_depth;++j)
                printf("frame=%u unit=%u pc=%lu\n",j,vm.frames[j].unit,(unsigned long)vm.frames[j].pc);
''' + after_slice + r'''
        }
        if(ERROR)CHECK(status==PYZ80_VM_ERROR);
        else {
            if(status!=PYZ80_VM_RETURNED)printf("status=%u error=%u depth=%u step=%lu external=%u\n",status,vm.error,vm.call_depth,(unsigned long)step_count,external_calls);
            CHECK(status==PYZ80_VM_RETURNED && result.kind==PYZ80_VM_VALUE_NONE);
        }
''' + 'if(i==0) {\n' + '\n'.join(checks) + '\n}\n' + after + r'''
    }
    CHECK(external_calls==EXTERNAL*REPETITIONS);
    return 0;
}
'''
    if classes:
        source = source.replace('#include "pyz80_target_gc.h"', '#include "pyz80_target_classes.h"\n#include "pyz80_target_gc.h"')
        source = source.replace('int main(void) {', 'int main(void) {\nPyZ80TargetClasses classes;PyZ80TargetClassFrame class_frames[DEPTH];PyZ80VMValue class_roots[3*DEPTH];uint16_t class_routes[PYZ80_GENERATED_ADAPTER_COUNT];')
        source = source.replace('for(i=0;i<REPETITIONS;++i) {', 'CHECK(PyZ80Target_AttachClasses(&classes,&scopes,class_frames,class_roots,DEPTH,class_routes));\nfor(i=0;i<REPETITIONS;++i) {')
    extras = {
        'pyz80_import_plan_generated.h': import_h, 'pyz80_import_plan_generated.c': import_c,
        'pyz80_target_adapter_plan_generated.h': adapter_h, 'pyz80_target_adapter_plan_generated.c': adapter_c}
    if dataclasses:
        from pyz80_compiler.dataclass_provider import build_plan, render_plan
        dc_h, dc_c = render_plan(build_plan(program))
        extras.update({'pyz80_dataclass_plan_generated.h': dc_h, 'pyz80_dataclass_plan_generated.c': dc_c})
        source = source.replace('#include "pyz80_target_gc.h"', '#include "pyz80_dataclass_plan_generated.h"\n#include "pyz80_target_gc.h"')
        source = source.replace('int main(void) {', 'int main(void) {\nPyZ80TargetDataclasses dataclass_context;')
        source = source.replace('for(i=0;i<REPETITIONS;++i) {', before_dataclasses + '\nCHECK(PyZ80Target_AttachDataclasses(&dataclass_context,&scopes,&PyZ80GeneratedDataclassPlan));\n' + after_dataclasses + '\nfor(i=0;i<REPETITIONS;++i) {')
    if generators:
        source = source.replace('#include "pyz80_target_gc.h"', '#include "pyz80_target_generators.h"\n#include "pyz80_target_gc.h"')
        source = source.replace('int main(void) {', 'int main(void) {\nPyZ80TargetGenerators generators;PyZ80TargetGeneratorRequest generator_frames[DEPTH];PyZ80VMValue generator_roots[3*DEPTH];uint16_t generator_routes[PYZ80_GENERATED_ADAPTER_COUNT];')
        source = source.replace('limits={DEPTH,0,192,MAX_ARGS}',f'limits={{DEPTH,{generator_slots},192,MAX_ARGS}}')
        source = source.replace('bytes[32768]', 'bytes[49152]')
        source = source.replace('for(i=0;i<REPETITIONS;++i) {', 'CHECK(PyZ80Target_AttachGenerators(&generators,&scopes,generator_frames,generator_roots,DEPTH,generator_routes));\nfor(i=0;i<REPETITIONS;++i) {')
    if sequences:
        if not generators:
            raise ValueError('sequence tests require generators=True')
        source = source.replace('#include "pyz80_target_gc.h"', '#include "pyz80_target_sequences.h"\n#include "pyz80_target_gc.h"')
        source = source.replace('int main(void) {', 'int main(void) {\nPyZ80TargetSequences sequences;PyZ80TargetSequenceRequest sequence_frames[DEPTH];PyZ80VMValue sequence_roots[2*DEPTH];uint16_t sequence_routes[PYZ80_GENERATED_ADAPTER_COUNT];')
        source = source.replace('for(i=0;i<REPETITIONS;++i) {', before_sequences+'\nCHECK(PyZ80Target_AttachSequences(&sequences,&scopes,sequence_frames,sequence_roots,DEPTH,sequence_routes));\n'+after_sequences+'\nfor(i=0;i<REPETITIONS;++i) {')
    if defaultdicts:
        if not generators:
            raise ValueError('defaultdict tests require generators=True')
        source = source.replace('#include "pyz80_target_gc.h"', '#include "pyz80_target_defaultdict.h"\n#include "pyz80_target_gc.h"')
        source = source.replace('int main(void) {', 'int main(void) {\nPyZ80TargetDefaultDict defaults;PyZ80TargetDefaultDictFrame default_frames[DEPTH];PyZ80VMValue default_roots[4*DEPTH];uint16_t default_routes[PYZ80_GENERATED_ADAPTER_COUNT];')
        source = source.replace('for(i=0;i<REPETITIONS;++i) {', before_defaultdict+'\nCHECK(PyZ80Target_AttachDefaultDict(&defaults,&scopes,default_frames,default_roots,DEPTH,default_routes));\n'+after_defaultdict+'\nfor(i=0;i<REPETITIONS;++i) {')
    if sorting:
        if not generators:
            raise ValueError('sorting tests require generators=True')
        source = source.replace('#include "pyz80_target_gc.h"', '#include "pyz80_target_sort.h"\n#include "pyz80_target_gc.h"')
        source = source.replace('int main(void) {', 'int main(void) {\nPyZ80TargetSort sorter;PyZ80TargetSortRequest sort_frames[DEPTH];PyZ80VMValue sort_roots[7*DEPTH];uint16_t sort_routes[PYZ80_GENERATED_ADAPTER_COUNT];')
        source = source.replace('for(i=0;i<REPETITIONS;++i) {', 'CHECK(PyZ80Target_AttachSort(&sorter,&scopes,sort_frames,sort_roots,DEPTH,sort_routes));\n'+after_sort+'\nfor(i=0;i<REPETITIONS;++i) {')
    if banked:
        from pyz80_compiler.banked_tables import build_banked_tables
        from test_pyz80_banked_fixture import banked_fixture
        blob, bank_h, bank_c, _ = build_banked_tables(adapters, artifact.target_coverage['positional_call_arities'], artifact.semantic_sha256)
        del extras['pyz80_target_adapter_plan_generated.h'], extras['pyz80_target_adapter_plan_generated.c']
        extras.update({'pyz80_target_banked_plan_generated.h':bank_h, 'pyz80_target_banked_plan_generated.c':bank_c})
        source = source.replace('#include "pyz80_target_adapter_plan_generated.h"', '#include "pyz80_target_banked_plan_generated.h"')
        source = source.replace('int main(void) {', banked_fixture(blob) + '\nint main(void) {\nPyZ80TargetBankedTables bank_tables;uint16_t bank_keys[254];')
        source = source.replace('PyZ80Generated_Bind(&objects);PyZ80Target_EnableBuiltins(&objects);', '')
        marker = 'CHECK(PyZ80VM_Init(&vm,&image,&adapter,arena.bytes,sizeof(arena.bytes),&limits)==PYZ80_VM_IDLE);'
        source = source.replace(marker, marker+'\nbank_init();CHECK(PyZ80Generated_BindBanked(&objects,&vm,&bank_tables,PyZ80Banked_Read,&bank_image,bank_keys,254));PyZ80Target_EnableBuiltins(&objects);')
        source = source.replace('CHECK(external_calls==EXTERNAL*REPETITIONS);',
            'CHECK(bank_maps>0 && bank_maps==bank_restores && current_bank==3 && !bank_image.busy);CHECK(objects.adapters==0 && objects.call_signatures==0);\nCHECK(external_calls==EXTERNAL*REPETITIONS);')
    compile_run(source, gc=True, builtins=True, bindings=True, imports=True, classes=classes,
                dataclasses=dataclasses, banked=banked, generators=generators, sorting=sorting, sequences=sequences, defaultdicts=defaultdicts, extra_sources=extras)
    return program, plan


@unittest.skipUnless(TCC, 'host C compiler unavailable')
class ImportRuntimeTests(unittest.TestCase):
    def test_import_once_preserves_function_defaults_and_shared_globals(self):
        import_check({'app': 'import a\nimport a as other\nfirst=a.f()\nsecond=other.f()\nanswer=first*100+second\n',
            'a': 'counter=7\ndef f(x=counter):\n    global counter\n    counter=counter+1\n    return counter+x\n'})

    def test_cycle_observes_partial_module_and_does_not_restart_it(self):
        import_check({'app': 'import a\nanswer=a.answer\n',
            'a': 'value=7\nimport b\nanswer=b.seen+1\nvalue=9\n',
            'b': 'from a import value\nseen=value\n'})

    def test_regular_packages_absolute_alias_and_relative_from(self):
        import_check({'app': 'import pkg.sub as sub\nimport pkg.sub\nfrom pkg import sub as alias\nanswer=sub.answer+alias.answer+pkg.sub.answer\n',
            'pkg': 'base=7\n', 'pkg.sub': 'from . import base\nanswer=base+1\n'}, packages=('pkg',))

    def test_fromlist_loading_finishes_before_names_are_bound(self):
        import_check({'app': 'from pkg import x,y\nanswer=x+y.value\n', 'pkg': 'base=7\n',
            'pkg.x': 'value=3\n', 'pkg.y': 'import pkg\npkg.x=99\nvalue=2\n'}, packages=('pkg',))

    def test_package_initializer_imports_requested_child_itself(self):
        import_check({'app': 'import pkg.sub as sub\nanswer=sub.value\n',
            'pkg': 'from . import sub\n', 'pkg.sub': 'value=12\n'}, packages=('pkg',))

    def test_dotted_alias_reads_rebound_parent_attribute_not_cached_leaf(self):
        import_check({'app': 'import pkg.sub as first\nimport pkg\npkg.sub=42\nimport pkg.sub as second\nanswer=first.value+second\n',
            'pkg': 'base=7\n', 'pkg.sub': 'value=8\n'}, packages=('pkg',))

    def test_import_from_cache_fallback_during_cycle(self):
        import_check({'app': 'import pkg.a as a\nanswer=a.value\n', 'pkg': 'base=10\n',
            'pkg.a': 'value=5\nimport pkg.b\nvalue=value+pkg.b.value\n',
            'pkg.b': 'from . import a\nvalue=a.value\n'}, packages=('pkg',))

    def test_failed_import_removes_only_loading_modules_and_can_retry(self):
        import_check({'app': 'import a\n', 'a': 'import b\nb.counter=b.counter+1\nanswer=missing\n',
            'b': 'counter=0\n'}, expected_external=1, repetitions=1000,
            after='CHECK(PyZ80Target_LoadField(&objects,&modules[$b$],@counter@,&value) && value.payload==i+1u);')

    def test_missing_from_name_fails_without_success_fallback(self):
        import_check({'app': 'from a import missing\nafter=10\n', 'a': 'value=7\n'})

    def test_import_inside_function_keeps_real_callee_globals(self):
        import_check({'app': 'from a import f\nanswer=f()\n',
            'a': 'x=7\ndef f():\n    import b\n    return x+b.value\n', 'b': 'value=8\n'})

    def test_vm_frame_overflow_cleans_incomplete_modules(self):
        import_check({'app': 'import a\n', 'a': 'import b\n', 'b': 'value=7\n'},
            max_depth=2, expect_vm_error=True, after='CHECK(vm.error==PYZ80_VM_E_CALL_OVERFLOW);for(j=0;j<MODULES;++j)CHECK(states[j]==PYZ80_MODULE_EMPTY);')

    def test_gc_safepoint_failure_also_unwinds_import_cache(self):
        import_check({'app':'x=7\n'}, expect_vm_error=True, before_slice='gc.node_capacity=0;',
            after='CHECK(vm.error==PYZ80_VM_E_HEAP_ROOTS);CHECK(states[ROOT]==PYZ80_MODULE_EMPTY);')

    def test_deferred_callback_must_supply_a_real_function_identity(self):
        import_check({'app':'value=7\n'}, expect_vm_error=True,
            c_helpers=r'''
static uint8_t missing_target(void *ctx,PyZ80VM *vm,uint16_t adapter,const PyZ80VMValue *args,
    uint8_t count,PyZ80VMValue *result,uint16_t *function) {
    (void)ctx;(void)vm;(void)adapter;(void)args;(void)count;(void)result;(void)function;return 2;
}
''', after_attach='imports.hooks.dispatch=missing_target;imports.hooks.routes=0;',
            after='CHECK(vm.error==PYZ80_VM_E_ARGUMENT);CHECK(states[ROOT]==PYZ80_MODULE_EMPTY);')

    def test_completion_hook_failure_unwinds_parent_and_child(self):
        import_check({'app':'import a\n','a':'value=7\n'}, expect_vm_error=True,
            c_helpers='static uint8_t reject_return(void *ctx,PyZ80VM *vm) {(void)ctx;(void)vm;return 0;}\n',
            after_attach='imports.hooks.returned=reject_return;',
            after='CHECK(vm.error==PYZ80_VM_E_ADAPTER);for(j=0;j<MODULES;++j)CHECK(states[j]==PYZ80_MODULE_EMPTY);')

    def test_import_callback_is_bypassed_for_ordinary_instructions(self):
        import_check({'app':'total=0\nfor i in range(20):\n    total=total+i\n'},
            c_helpers=r'''
static uint8_t reject_dispatch(void *ctx,PyZ80VM *vm,uint16_t adapter,const PyZ80VMValue *args,
    uint8_t count,PyZ80VMValue *result,uint16_t *function) {
    (void)ctx;(void)vm;(void)adapter;(void)args;(void)count;(void)result;(void)function;return 3;
}
''', after_attach='imports.hooks.dispatch=reject_dispatch;')

    def test_non_none_initializer_return_is_rejected_by_vm(self):
        import_check({'app':'value=7\ndef wrong():\n    return 99\n'}, expect_vm_error=True,
            c_helpers=r'''
static uint8_t wrong_target(void *ctx,PyZ80VM *vm,uint16_t adapter,const PyZ80VMValue *args,
    uint8_t count,PyZ80VMValue *result,uint16_t *function) {
    (void)ctx;(void)vm;(void)adapter;(void)args;(void)count;(void)result;*function=1;return 2;
}
''', after_attach='imports.hooks.dispatch=wrong_target;imports.hooks.routes=0;',
            after='CHECK(vm.error==PYZ80_VM_E_ARGUMENT);CHECK(states[ROOT]==PYZ80_MODULE_EMPTY);')

    def test_unsupported_dynamic_module_getattr_is_not_silently_ignored(self):
        import_check({'app':'from pkg import value\nanswer=value\n',
            'pkg':'def __getattr__(name):\n    return 42\n'}, packages=('pkg',), expect_vm_error=True,
            after='CHECK(vm.error==PYZ80_VM_E_ADAPTER);')

    def test_plan_validation_is_atomic_and_rejects_aliases_and_bad_seals(self):
        import_check({'app':'import a\nanswer=a.value\n','a':'value=7\n'}, before_attach=r'''
        {
            PyZ80TargetImportPlan bad=PyZ80GeneratedImportPlan;uint8_t fake_proof[32]={0};
            bad.proof_sha256=fake_proof;
            CHECK(!PyZ80Target_AttachImports(&imports,&scopes,&bad,modules,states,globals,frames,DEPTH));
            CHECK(!vm.control_hooks && !objects.node_used);
            CHECK(!PyZ80Target_AttachImports(&imports,&scopes,&PyZ80GeneratedImportPlan,globals,states,globals,frames,DEPTH));
            CHECK(!PyZ80Target_AttachImports(&imports,&scopes,&PyZ80GeneratedImportPlan,modules,states,globals,(PyZ80TargetImportFrame*)vm.locals,DEPTH));
            CHECK(!vm.control_hooks && !objects.node_used);
            bad=PyZ80GeneratedImportPlan;bad.function_count=0;
            CHECK(!PyZ80Target_AttachImports(&imports,&scopes,&bad,modules,states,globals,frames,DEPTH));
        }
''')

    def test_large_slices_do_not_replay_import_body_or_expression_arguments(self):
        import_check({'app':'import a\nfirst=a.f()\nsecond=a.f()\nanswer=first*100+second\n',
            'a':'counter=0\ndef f():\n    global counter\n    counter=counter+1\n    import b\n    return counter+b.value\n',
            'b':'value=7\n'}, budget=1000)

    def test_escaped_function_from_failed_module_keeps_old_globals_for_new_defs(self):
        import_check({'app':'import a\n', 'a':'''import b
x=b.counter+10
def outer():
    def inner():
        return x
    return inner
if b.counter==0:
    b.saved=outer
b.counter=b.counter+1
missing
''', 'b':'counter=0\n'}, expected_external=1, repetitions=1000, after=r'''
        {
            PyZ80VMValue outer,inner;
            CHECK(PyZ80Target_LoadField(&objects,&modules[$b$],@saved@,&outer));
            CHECK(PyZ80VM_StartClosure(&vm,nodes[(uint16_t)outer.payload-1].class_symbol,&outer,0,0)==PYZ80_VM_RUNNING);
            do {status=PyZ80Target_RunSlice(&objects,&vm,&scopes,modules,MODULES,&gc,1,&result);} while(status==PYZ80_VM_RUNNING);
            CHECK(status==PYZ80_VM_RETURNED);inner=result;
            CHECK(PyZ80VM_StartClosure(&vm,nodes[(uint16_t)inner.payload-1].class_symbol,&inner,0,0)==PYZ80_VM_RUNNING);
            do {status=PyZ80Target_RunSlice(&objects,&vm,&scopes,modules,MODULES,&gc,1,&result);} while(status==PYZ80_VM_RUNNING);
            CHECK(status==PYZ80_VM_RETURNED && result.payload==10);
        }
''')


class ImportPlanTests(unittest.TestCase):
    def test_local_import_inventory_includes_dormant_branches_without_executing(self):
        with tempfile.TemporaryDirectory(prefix='pyz80-import-sources-') as raw:
            directory = Path(raw)
            (directory/'pkg').mkdir()
            for filename, source in {
                'app.py':'from pkg import sub\ndef later():\n    import local_only\n',
                'pkg/__init__.py':'raise RuntimeError("must not execute on build host")\n',
                'pkg/sub.py':'from . import helper\n', 'pkg/helper.py':'value=7\n',
                'local_only.py':'import external_dependency\n', 'unreferenced.py':'import forbidden\n'
            }.items():
                (directory/filename).write_text(source, encoding='utf-8')
            modules = collect_source_imports(directory, ('app',))
            self.assertEqual(set(modules), {'app','pkg','pkg.sub','pkg.helper','local_only'})
            self.assertNotIn('pkg', sys.modules)

    def test_incomplete_package_chain_is_not_a_native_import(self):
        program = build_module_program({'app':(Path('app.py'),'import pkg.sub\n'),
                                        'pkg.sub':(Path('pkg/sub.py'),'value=7\n')})
        plan = build_import_plan(program)
        self.assertEqual(plan['requests'], [])
        self.assertEqual(len(plan['pending']), 1)

    def test_import_star_remains_an_explicit_provider_boundary(self):
        program = build_module_program({'app':(Path('app.py'),'from a import *\n'),
                                        'a':(Path('a.py'),'value=7\n')})
        plan = build_import_plan(program)
        self.assertEqual(plan['requests'], [])
        self.assertTrue(any(row['op']=='python-import-star' for row in program.artifact.adapter_table))


if __name__ == '__main__':
    unittest.main()
