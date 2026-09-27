"""Precise safepoint tracing and repeated source execution in bounded arenas."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from generate_pzvt_target_adapters import build_adapter_specs
from test_pyz80_callable_runtime import compile_run, PRELUDE, TCC
from test_pyz80_scope_runtime import source_artifact
from test_pyz80_target_object_runtime import RUNTIME, SDCC


def source_header(source):
    return artifact_header(source_artifact(source))


def artifact_header(artifact):
    ids = artifact.target_coverage["function_id_table"]
    plan = build_adapter_specs(artifact.adapter_table, artifact.compact_document["constants"], ids,
        artifact.target_coverage["function_call_signatures"])
    return (
        "static const uint8_t bytes[]={" + ",".join(map(str,artifact.target_bytecode)) + "};\n"
        "static const uint8_t proof[]={" + ",".join(map(str,bytes.fromhex(artifact.semantic_sha256))) + "};\n"
        "static const uint16_t keys[]={" + ",".join(map(str,plan["field_keys"])) + "};\n"
        "static const uint16_t fixture_class_symbols[]={" + ",".join(map(str,plan["class_symbols"])) + "};\n"
        "static const uint16_t arities[]={" + ",".join(map(str,artifact.target_coverage["positional_call_arities"])) + "};\n"
        "static const PyZ80TargetAdapterSpec specs[]={" + ",".join(f"{{{op},{n},{aux}}}" for op,n,aux in plan["specs"]) +
        ("," if plan["specs"] else "") + "{PYZ80_TARGET_ALLOCATE_INSTANCE,1,0}};\n"
        "static const PyZ80TargetOperatorSpec ops[]={" + ",".join(f"{{{k},{op},0}}" for k,op in plan["operators"]) + "};\n"
        "static const uint8_t positional_calls[]={" + ",".join(map(str,plan["positional_call_flags"] + [0])) + "};\n"
        "static const PyZ80TargetBuiltinSpec builtin_symbols[]={" +
        (",".join(f"{{{k},{op}}}" for k,op in plan["builtin_symbols"]) or "{0,0}") + "};\n"
        f"#define BUILTIN_COUNT {len(plan['builtin_symbols'])}\n"
        "static const PyZ80TargetCallSignature signatures[]={" +
        (",".join("{" + ",".join(map(str,row)) + "}" for row in plan["call_signatures"]) or "{0,0,0,0,0}") + "};\n"
        "static const uint16_t parameter_names[]={" + ",".join(map(str,plan["parameter_names"] or [0])) + "};\n"
        "static const uint16_t call_layout_offsets[]={" + ",".join(map(str,plan["call_layout_offsets"] + [65535])) + "};\n"
        "static const uint16_t call_layout_keys[]={" + ",".join(map(str,plan["call_layout_keys"] or [0])) + "};\n"
        f"#define PARAMETER_NAMES {len(plan['parameter_names'])}\n#define CALL_LAYOUT_KEYS {len(plan['call_layout_keys'])}\n"
        f"#define ALLOCATE {len(plan['specs'])}\n#define OP_COUNT {len(plan['operators'])}\n#define FUNCTIONS {len(ids)}\n")


class GCRuntimeTests(unittest.TestCase):
    @unittest.skipUnless(TCC, "host compiler unavailable")
    def test_returned_closures_survive_owner_return_and_later_collections(self):
        source = 'def factory(seed):\n    x = seed + 3\n    return lambda y: x + y\n'
        namespace = {}
        exec(source, namespace)
        self.assertEqual(namespace["factory"](7)(2), 12)
        self.assertEqual(namespace["factory"](100)(2), 105)
        compile_run(PRELUDE + '#include "pyz80_target_gc.h"\n' + source_header(source) + r'''
int main(void) {
    PyZ80TargetContext objects;PyZ80TargetScopes scopes;
    PyZ80TargetNode nodes[16];PyZ80TargetField fields[8];
    PyZ80VMValue items[64],frames[8],globals[FUNCTIONS],arg,result,roots[2],dead;
    uint8_t marks[16];uint16_t queue[16],fm[8],im[64];
    PyZ80TargetGC gc={marks,queue,fm,im,16,8,64,0,0,0,0};
    PyZ80VM vm;PyZ80VMAdapter adapter;PyZ80VMLimits limits={8,0,64,12};
    PyZ80VMMemoryImage memory={bytes,sizeof(bytes)};
    PyZ80VMImage image={PyZ80VM_MemoryRead,&memory,sizeof(bytes),proof};
    union {uint32_t align;uint8_t bytes[8192];} arena;
    unsigned i;uint32_t pc;
    PyZ80Target_Init(&objects,nodes,16,fields,8,items,64,specs,ALLOCATE+1,ops,OP_COUNT,0,0);
    objects.field_keys=keys;objects.field_key_count=sizeof(keys)/sizeof(keys[0]);objects.function_count=FUNCTIONS;
    objects.positional_call_arities=arities;
    arg=integer(0);arg.kind=PYZ80_VM_VALUE_SYMBOL;arg.symbol=0;
    CHECK(PyZ80Target_Invoke(&objects,0,ALLOCATE,0,&arg,1,0,&globals[0]));
    for(i=1;i<FUNCTIONS;++i)globals[i]=globals[0];
    adapter=PyZ80Target_VMAdapter(&objects);
    CHECK(PyZ80VM_Init(&vm,&image,&adapter,arena.bytes,sizeof(arena.bytes),&limits)==PYZ80_VM_IDLE);
    CHECK(PyZ80Target_AttachScopes(&scopes,&objects,&vm,frames,8,globals,FUNCTIONS));
    arg=integer(7);CHECK(PyZ80VM_StartArgs(&vm,0,&arg,1)==PYZ80_VM_RUNNING);
    CHECK(PyZ80Target_RunSlice(&objects,&vm,&scopes,0,0,&gc,1000,&roots[0])==PYZ80_VM_RETURNED);
    arg=integer(100);CHECK(PyZ80VM_StartArgs(&vm,0,&arg,1)==PYZ80_VM_RUNNING);
    CHECK(PyZ80Target_RunSlice(&objects,&vm,&scopes,roots,1,&gc,1000,&roots[1])==PYZ80_VM_RETURNED);
    for(i=0;i<1000;++i) {
        arg=integer(2);
        CHECK(PyZ80VM_StartClosure(&vm,1,&roots[i%2],&arg,1)==PYZ80_VM_RUNNING);
        CHECK(PyZ80Target_RunSlice(&objects,&vm,&scopes,roots,2,&gc,1000,&result)==PYZ80_VM_RETURNED);
        CHECK(result.payload==(i%2?105:12) && gc.live_nodes==5 && objects.item_used==4);
    }
    dead=roots[1];
    CHECK(PyZ80Target_Collect(&objects,&vm,&scopes,roots,1,&gc) && gc.live_nodes==3 && objects.item_used==2);
    arg=integer(2);CHECK(PyZ80VM_StartClosure(&vm,1,&roots[0],&arg,1)==PYZ80_VM_RUNNING);
    pc=vm.frames[0].pc;
    CHECK(PyZ80Target_RunSlice(&objects,&vm,&scopes,&dead,1,&gc,1000,&result)==PYZ80_VM_ERROR);
    CHECK(vm.error==PYZ80_VM_E_HEAP_ROOTS && vm.frames[0].pc==pc);
    return 0;
}
''', gc=True)

    @unittest.skipUnless(TCC, "host compiler unavailable")
    def test_suspended_frames_are_roots_and_generation_never_wraps(self):
        compile_run(PRELUDE + '#include "pyz80_target_gc.h"\n' + r'''
int main(void) {
    PyZ80TargetContext objects;PyZ80VM vm;
    PyZ80TargetNode nodes[2];PyZ80TargetField fields[1];PyZ80VMValue items[1],value,reused;
    PyZ80VMLocal locals[2];PyZ80VMGenerator generators[1];
    uint8_t marks[2];uint16_t queue[2],fm[1],im[1];
    PyZ80TargetGC gc={marks,queue,fm,im,2,1,1,0,0,0,0};
    PyZ80Target_Init(&objects,nodes,2,fields,1,items,1,0,0,0,0,0,0);
    CHECK(PyZ80Target_AllocateNode(&objects,PYZ80_TARGET_NODE_OBJECT,0,&value));
    memset(&vm,0,sizeof(vm));memset(generators,0,sizeof(generators));memset(locals,0,sizeof(locals));
    vm.adapter=PyZ80Target_VMAdapter(&objects);vm.limits.max_call_depth=1;
    vm.limits.max_generators=1;vm.limits.locals_per_frame=1;
    vm.locals=locals;vm.generators=generators;
    generators[0].in_use=1;generators[0].local_count=1;locals[1].value=value;
    CHECK(PyZ80Target_Collect(&objects,&vm,0,0,0,&gc) && gc.live_nodes==1);
    CHECK(nodes[0].kind==PYZ80_TARGET_NODE_OBJECT);
    generators[0].done=1;
    CHECK(PyZ80Target_Collect(&objects,&vm,0,0,0,&gc) && gc.live_nodes==0);
    CHECK(nodes[0].kind==PYZ80_TARGET_NODE_FREE);
    /* The last generation is valid once. After collection its slot retires. */
    nodes[0].generation=65534;
    CHECK(PyZ80Target_AllocateNode(&objects,PYZ80_TARGET_NODE_OBJECT,0,&value));
    CHECK(value.payload==0xFFFF0001UL);
    CHECK(PyZ80Target_Collect(&objects,0,0,&value,1,&gc));
    CHECK(PyZ80Target_Collect(&objects,0,0,0,0,&gc));
    CHECK(PyZ80Target_AllocateNode(&objects,PYZ80_TARGET_NODE_OBJECT,0,&reused));
    CHECK((uint16_t)reused.payload==2 && nodes[0].generation==65535);
    CHECK(!PyZ80Target_Collect(&objects,0,0,&value,1,&gc));
    CHECK(nodes[1].kind==PYZ80_TARGET_NODE_OBJECT);
    return 0;
}
''', gc=True)

    @unittest.skipUnless(TCC, "host compiler unavailable")
    def test_cycles_live_identity_compaction_and_stale_handles(self):
        compile_run(PRELUDE + '#include "pyz80_target_gc.h"\n' + r'''
int main(void) {
    PyZ80TargetContext objects;
    PyZ80TargetNode nodes[12], before[12];PyZ80TargetField fields[16],before_fields[16];
    PyZ80VMValue items[64],before_items[64],args[2],dead,root,cycle,child,list,iterator,result,old,discarded;
    uint8_t marks[12];uint16_t queue[12],fm[16],im[64];
    PyZ80TargetGC gc={marks,queue,fm,im,12,16,64,0,0,0,0};
    const PyZ80TargetAdapterSpec specs[]={
        {PYZ80_TARGET_ALLOCATE_INSTANCE,1,0},{PYZ80_TARGET_BUILD_LIST,0,0},
        {PYZ80_TARGET_LIST_APPEND,2,0},{PYZ80_TARGET_GET_ITERATOR,1,0},
        {PYZ80_TARGET_ITER_NEXT,1,0},{PYZ80_TARGET_ITER_VALUE,1,0}
    };
    unsigned i;uint32_t root_id;uint16_t old_fields,old_items;
    PyZ80Target_Init(&objects,nodes,12,fields,16,items,64,specs,6,0,0,0,0);
    args[0]=integer(0);args[0].kind=PYZ80_VM_VALUE_SYMBOL;args[0].symbol=77;
    CHECK(PyZ80Target_Invoke(&objects,0,0,0,args,1,0,&dead));old=dead;
    CHECK(PyZ80Target_StoreField(&objects,&dead,1,&dead));
    CHECK(PyZ80Target_Invoke(&objects,0,0,0,args,1,0,&root));root_id=root.payload;
    CHECK(PyZ80Target_Invoke(&objects,0,0,0,args,1,0,&cycle));
    CHECK(PyZ80Target_Invoke(&objects,0,0,0,args,1,0,&child));
    CHECK(PyZ80Target_StoreField(&objects,&cycle,1,&cycle));
    CHECK(PyZ80Target_StoreField(&objects,&root,1,&child));
    CHECK(PyZ80Target_StoreField(&objects,&child,1,&root));
    /* Настоящий недостижимый item перед живым списком: проверяем уплотнение,
       не полагаясь на лишние копии/запас прежнего алгоритма append. */
    CHECK(PyZ80Target_EmptyList(&objects,&discarded));
    CHECK(PyZ80Target_ListAppend(&objects,&discarded,&child));
    CHECK(PyZ80Target_Invoke(&objects,0,1,0,0,0,0,&list));
    args[0]=list;args[1]=child;
    for(i=0;i<9;++i)CHECK(PyZ80Target_Invoke(&objects,0,2,0,args,2,0,&result));
    CHECK(PyZ80Target_Invoke(&objects,0,3,0,&list,1,0,&iterator));
    CHECK(PyZ80Target_StoreField(&objects,&root,2,&iterator));
    old_fields=objects.field_used;old_items=objects.item_used;
    CHECK(PyZ80Target_Collect(&objects,0,0,&root,1,&gc));
    CHECK(root.payload==root_id && gc.live_nodes==4 && objects.field_used==3 && objects.item_used==9);
    CHECK(objects.field_used<old_fields && objects.item_used<old_items);
    CHECK(PyZ80Target_LoadField(&objects,&root,1,&result) && result.payload==child.payload);
    CHECK(PyZ80Target_LoadField(&objects,&child,1,&result) && result.payload==root.payload);
    CHECK(PyZ80Target_Invoke(&objects,0,4,0,&iterator,1,0,&result));
    CHECK(PyZ80Target_Invoke(&objects,0,5,0,&iterator,1,0,&result) && result.payload==child.payload);
    args[0]=integer(0);args[0].kind=PYZ80_VM_VALUE_SYMBOL;args[0].symbol=77;
    CHECK(PyZ80Target_Invoke(&objects,0,0,0,args,1,0,&dead));
    CHECK((uint16_t)old.payload==(uint16_t)dead.payload && old.payload!=dead.payload);
    CHECK(!PyZ80Target_LoadField(&objects,&old,1,&result));
    memcpy(before,nodes,sizeof(nodes));memcpy(before_fields,fields,sizeof(fields));memcpy(before_items,items,sizeof(items));
    CHECK(!PyZ80Target_Collect(&objects,0,0,&old,1,&gc));
    CHECK(!memcmp(before,nodes,sizeof(nodes)) && !memcmp(before_fields,fields,sizeof(fields)) && !memcmp(before_items,items,sizeof(items)));
    /* Invalid reachable field chain is rejected before sweep/compaction. */
    fields[nodes[(uint16_t)root.payload-1].field_head-1].next=65535;
    memcpy(before,nodes,sizeof(nodes));memcpy(before_fields,fields,sizeof(fields));
    CHECK(!PyZ80Target_Collect(&objects,0,0,&root,1,&gc));
    CHECK(!memcmp(before,nodes,sizeof(nodes)) && !memcmp(before_fields,fields,sizeof(fields)));
    return 0;
}
''', gc=True)

    @unittest.skipUnless(TCC, "host compiler unavailable")
    def test_repeated_translated_comprehension_collects_at_every_vm_step(self):
        source = ('def factory(seed):\n    f = lambda y: seed + y\n'
                  '    result = [f(x) for x in [1,2,3,4,5,6]]\n'
                  '    return result[0] + result[5]\n')
        namespace = {}
        exec(source, namespace)
        self.assertEqual(namespace["factory"](7), 21)
        header = source_header(source)
        compile_run(PRELUDE + '#include "pyz80_target_gc.h"\n' + header + r'''
int main(void) {
    PyZ80TargetContext objects;PyZ80TargetScopes scopes;
    PyZ80TargetNode nodes[16];PyZ80TargetField fields[8];
    PyZ80VMValue items[64],frames[8],globals[FUNCTIONS],arg,result;
    uint8_t marks[16];uint16_t queue[16],fm[8],im[64];
    PyZ80TargetGC gc={marks,queue,fm,im,16,8,64,0,0,0,0};
    PyZ80VM vm;PyZ80VMAdapter adapter;PyZ80VMLimits limits={8,0,64,12};
    PyZ80VMMemoryImage memory={bytes,sizeof(bytes)};
    PyZ80VMImage image={PyZ80VM_MemoryRead,&memory,sizeof(bytes),proof};
    union {uint32_t align;uint8_t bytes[8192];} arena;
    unsigned frame,i,steps;uint8_t status;
    PyZ80Target_Init(&objects,nodes,16,fields,8,items,64,specs,ALLOCATE+1,ops,OP_COUNT,0,0);
    objects.field_keys=keys;objects.field_key_count=sizeof(keys)/sizeof(keys[0]);objects.function_count=FUNCTIONS;
    objects.positional_call_arities=arities;
    arg=integer(0);arg.kind=PYZ80_VM_VALUE_SYMBOL;arg.symbol=0;
    CHECK(PyZ80Target_Invoke(&objects,0,ALLOCATE,0,&arg,1,0,&globals[0]));
    for(i=1;i<FUNCTIONS;++i)globals[i]=globals[0];
    adapter=PyZ80Target_VMAdapter(&objects);
    CHECK(PyZ80VM_Init(&vm,&image,&adapter,arena.bytes,sizeof(arena.bytes),&limits)==PYZ80_VM_IDLE);
    CHECK(PyZ80Target_AttachScopes(&scopes,&objects,&vm,frames,8,globals,FUNCTIONS));
    for(frame=0;frame<2000;++frame) {
        arg=integer(frame%31);
        CHECK(PyZ80VM_StartArgs(&vm,0,&arg,1)==PYZ80_VM_RUNNING);
        status=PYZ80_VM_RUNNING;steps=0;
        while(status==PYZ80_VM_RUNNING && ++steps<2000) {
            status=PyZ80Target_RunSlice(&objects,&vm,&scopes,0,0,&gc,1,&result);
        }
        CHECK(status==PYZ80_VM_RETURNED && result.payload==2*(frame%31)+7);
        CHECK(gc.live_nodes==1 && objects.item_used==0 && objects.field_used==0 && objects.node_used<=16);
    }
    CHECK(nodes[1].generation>255); /* Handles remain valid beyond the old 8-bit generation limit. */
    return 0;
}
''', gc=True)

    @unittest.skipUnless(SDCC, "Z80 compiler unavailable")
    def test_collector_compiles_without_static_scratch(self):
        with tempfile.TemporaryDirectory(prefix="pz-gc-z80-") as raw:
            directory = Path(raw)
            for name in ("pyz80_whole_program_vm.h","pyz80_target_object_runtime.h",
                         "pyz80_target_scope_runtime.h","pyz80_target_gc.h","pyz80_target_gc.c","pyz80_target_deque.h","pyz80_target_buffers.h"):
                shutil.copy2(RUNTIME/name,directory/name)
            environment=os.environ.copy()
            environment["PATH"]=str(SDCC.parent)+os.pathsep+environment.get("PATH","")
            run=subprocess.run([str(SDCC),"-mz80","--std-c11","--sdcccall","1","--stack-auto",
                "--opt-code-speed","-c","pyz80_target_gc.c"],cwd=directory,env=environment,
                capture_output=True,text=True,timeout=240)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            self.assertIn("A _DATA size 0 ",(directory/"pyz80_target_gc.rel").read_text())


if __name__ == "__main__":
    unittest.main()
