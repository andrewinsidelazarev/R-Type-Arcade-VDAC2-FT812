"""Исходные Python-генераторы в C VM: приостановка, корни и стек кадров."""
import ast
import copy
from pathlib import Path
import unittest

from pyz80_compiler.function_cfg import lower_python_function_cfg
from pyz80_compiler.generator_lowering import lower_generator_next_bodies
from pyz80_compiler.whole_program_vm_backend import build_whole_program_vm
from test_pyz80_callable_runtime import compile_run, PRELUDE, TCC
from test_pyz80_gc_runtime import artifact_header
from test_pyz80_scope_runtime import source_artifact
from test_pyz80_whole_program_vm_backend import (
    _resign, function_cfg, block, instruction, terminator,
)


SETUP = r'''
#include "pyz80_target_gc.h"
typedef struct Fixture {
    PyZ80VM vm; PyZ80TargetContext objects; PyZ80TargetScopes scopes;
    PyZ80TargetNode nodes[128]; PyZ80TargetField fields[64];
    PyZ80VMValue items[256], closures[12], globals[FUNCTIONS];
    uint8_t marks[128]; uint16_t queue[128], fm[64], im[256];
    PyZ80TargetGC gc;
    PyZ80VMMemoryImage memory; PyZ80VMImage image;
    union {uint32_t align; uint8_t bytes[24000];} arena;
} Fixture;
static int setup_depth(Fixture *f,uint8_t depth) {
    PyZ80VMAdapter adapter; PyZ80VMLimits limits={12,4,96,12};
    PyZ80VMValue arg; unsigned i;
    memset(f,0,sizeof(*f));
    limits.max_call_depth=depth;
    f->memory.bytes=bytes; f->memory.size=sizeof(bytes);
    f->image.read=PyZ80VM_MemoryRead;f->image.context=&f->memory;
    f->image.size=sizeof(bytes);f->image.expected_proof_sha256=proof;
    PyZ80Target_Init(&f->objects,f->nodes,128,f->fields,64,f->items,256,
        specs,ALLOCATE+1,ops,OP_COUNT,0,0);
    f->objects.field_keys=keys;f->objects.field_key_count=sizeof(keys)/sizeof(keys[0]);
    f->objects.function_count=FUNCTIONS;f->objects.positional_call_arities=arities;
    arg=integer(0);arg.kind=PYZ80_VM_VALUE_SYMBOL;arg.symbol=0;
    if(!PyZ80Target_Invoke(&f->objects,0,ALLOCATE,0,&arg,1,0,&f->globals[0]))return 0;
    for(i=1;i<FUNCTIONS;++i)f->globals[i]=f->globals[0];
    adapter=PyZ80Target_VMAdapter(&f->objects);
    if(PyZ80VM_Init(&f->vm,&f->image,&adapter,f->arena.bytes,sizeof(f->arena.bytes),&limits)!=PYZ80_VM_IDLE)return 0;
    if(!PyZ80Target_AttachScopes(&f->scopes,&f->objects,&f->vm,f->closures,12,f->globals,FUNCTIONS))return 0;
    f->gc.marked=f->marks;f->gc.queue=f->queue;f->gc.field_map=f->fm;f->gc.item_map=f->im;
    f->gc.node_capacity=128;f->gc.field_capacity=64;f->gc.item_capacity=256;
    return 1;
}
static int setup(Fixture *f) { return setup_depth(f,12); }
static uint8_t finish(Fixture *f, PyZ80VMValue *result) {
    unsigned steps=0;uint8_t status=f->vm.status;
    while(status==PYZ80_VM_RUNNING && ++steps<10000)
        status=PyZ80Target_RunSlice(&f->objects,&f->vm,&f->scopes,0,0,&f->gc,1,result);
    return status;
}
static uint8_t resume(Fixture *f,uint16_t handle,PyZ80VMValue *result) {
    uint8_t status=PyZ80VM_GeneratorResume(&f->vm,handle,0,0,result);
    return status==PYZ80_VM_RUNNING?finish(f,result):status;
}
'''


class GeneratorRuntimeTests(unittest.TestCase):
    @unittest.skipUnless(TCC, "host compiler unavailable")
    def test_nested_resume_preserves_callers_and_never_reenters_run(self):
        main = function_cfg('main', 1, [block('entry', [
            instruction(0,'constant',[700],'%sentinel'),
            instruction(1,'fixture-next',[1],'%a'),
            instruction(2,'fixture-next',[1],'%b'),
            instruction(3,'fixture-next',[1],'%c'),
            instruction(4,'vm-binary-i32',['add','%a','%b'],'%ab'),
            instruction(5,'vm-binary-i32',['add','%ab','%c'],'%abc'),
            instruction(6,'vm-binary-i32',['add','%sentinel','%abc'],'%result'),
        ],terminator('return',['%result'],[]))])
        outer = function_cfg('outer',2,[
            block('entry',[instruction(0,'vm-call',['m::helper@3'],'%a')],
                terminator('yield',['%a'],['second'])),
            block('second',[instruction(1,'vm-call',['m::helper@3'],'%b')],
                terminator('yield',['%b'],['done'])),
            block('done',[instruction(2,'constant',[88],'%c')],terminator('return',['%c'],[])),
        ])
        helper = function_cfg('helper',3,[block('entry',[
            instruction(0,'fixture-next',[0],'%v')],terminator('return',['%v'],[]))])
        source = 'def values(seed):\n    for x in [1,2]:\n        yield seed + x\n    return 40\n'
        inner = lower_python_function_cfg(ast.parse(source).body[0],class_name=None,
            source_path=Path('fixture.py'),source_text=source).to_json()
        rows = [{'callable_id':identity,'module':'m','cfg':cfg} for identity,cfg in (
            ('m::main@1',main),('m::outer@2',outer),('m::helper@3',helper),('m::values@1',inner))]
        graph = {'format':'synthetic.active-call-graph.v1',
            'call_graph':{'proven_reachable_callable_ids':[r['callable_id'] for r in rows],'call_sites':[]},
            'callable_inventory':{'callables':rows}}
        _resign(graph)
        artifact = build_whole_program_vm(graph)
        next_id = next(r['adapter_id'] for r in artifact.adapter_table if r['op']=='fixture-next')
        compile_run(PRELUDE + artifact_header(artifact) + SETUP + f'\n#define NEXT {next_id}\n' + r'''
typedef struct Control {
    PyZ80VMControlHooks hooks,outer;
    PyZ80VMValue roots[12];PyZ80VMFrame callers[12];PyZ80VMLocal locals[12][96];
    uint8_t state[12];uint16_t handle[12];unsigned requests,events,yields,returns,max_depth,mode;
} Control;
static uint8_t dispatch(void *raw,PyZ80VM *vm,uint16_t adapter,const PyZ80VMValue *args,
    uint8_t count,PyZ80VMValue *result,uint16_t *function) {
    Control *c=raw;unsigned depth=vm->call_depth-1;
    if(adapter!=NEXT)return 0;
    if(count!=1 || args[0].kind!=PYZ80_VM_VALUE_I32 || depth>=12)return 3;
    if(c->state[depth]==2) {
        *result=c->roots[depth];c->roots[depth]=integer(0);c->state[depth]=0;return 1;
    }
    if(c->state[depth])return 3;
    c->callers[depth]=vm->frames[depth];++c->callers[depth].instructions_remaining;
    memcpy(c->locals[depth],vm->locals+depth*96,vm->frames[depth].local_count*sizeof(PyZ80VMLocal));
    c->state[depth]=1;c->handle[depth]=(uint16_t)args[0].payload;
    if(c->mode==1 && depth)c->handle[depth]=1;
    if(c->mode==2 && depth) {
        if(PyZ80VM_GeneratorClose(vm,1)!=PYZ80_VM_ERROR)return 3;
        return 3;
    }
    *function=c->handle[depth];++c->requests;return 5;
}
static uint8_t event(void *raw,PyZ80VM *vm,uint16_t handle,uint8_t yielded,const PyZ80VMValue *value) {
    Control *c=raw;unsigned depth=vm->call_depth-2;
    if(depth>=12 || c->state[depth]!=1 || c->handle[depth]!=handle)return 2;
    if(memcmp(&c->callers[depth],&vm->frames[depth],sizeof(PyZ80VMFrame)) ||
        memcmp(c->locals[depth],vm->locals+depth*96,vm->frames[depth].local_count*sizeof(PyZ80VMLocal)))return 2;
    c->roots[depth]=*value;c->state[depth]=2;++c->events;
    if(yielded)++c->yields;else ++c->returns;
    return 1;
}
int main(void) {
    Fixture f;Control c;PyZ80VMValue arg,value;uint16_t handle;unsigned mode,step;uint8_t status;
    for(mode=0;mode<4;++mode) {
        CHECK(setup_depth(&f,mode==3?3:12));memset(&c,0,sizeof(c));c.mode=mode;
        c.hooks.dispatch=dispatch;c.hooks.context=&c;c.hooks.generator_event=event;
        c.hooks.roots=c.roots;c.hooks.root_count=12;
        c.outer.dispatch=dispatch;c.outer.context=&c;c.outer.previous=&c.hooks;
        f.vm.control_hooks=&c.outer;
        arg=integer(10);CHECK(PyZ80VM_GeneratorCreateArgs(&f.vm,3,0,&arg,1,&handle)==PYZ80_VM_IDLE && handle==0);
        CHECK(PyZ80VM_GeneratorCreate(&f.vm,1,&handle)==PYZ80_VM_IDLE && handle==1);
        CHECK(PyZ80VM_Start(&f.vm,0)==PYZ80_VM_RUNNING);
        status=PYZ80_VM_RUNNING;
        for(step=0;step<1000 && status==PYZ80_VM_RUNNING;++step) {
            if(f.vm.call_depth>c.max_depth)c.max_depth=f.vm.call_depth;
            status=PyZ80Target_RunSlice(&f.objects,&f.vm,&f.scopes,0,0,&f.gc,1,&value);
        }
        if(mode) {
            CHECK(status==PYZ80_VM_ERROR);
            CHECK(f.vm.error==(mode==3?PYZ80_VM_E_CALL_OVERFLOW:PYZ80_VM_E_GENERATOR_STATE));
            CHECK(f.vm.generators[1].done && !f.vm.generators[1].reserved);
            CHECK(f.vm.active_generator==PYZ80_VM_NO_GENERATOR);
        } else {
            CHECK(status==PYZ80_VM_RETURNED && value.payload==811 && c.max_depth==5);
            CHECK(c.requests==5 && c.events==5 && c.yields==4 && c.returns==1);
            CHECK(!f.vm.call_depth && f.vm.active_generator==PYZ80_VM_NO_GENERATOR);
            CHECK(resume(&f,0,&value)==PYZ80_VM_RETURNED && value.payload==40);
            CHECK(f.vm.generators[0].done && f.vm.generators[1].done);
        }
    }
    return 0;
}
''', gc=True)

    @unittest.skipUnless(TCC, "host compiler unavailable")
    def test_source_loops_values_and_independent_frames_match_cpython(self):
        sources = [
            'def values(seed):\n    for x in [1,2,3]:\n        yield seed + x\n    return 99\n',
            'def values(seed):\n    for x in [1,2,3]:\n        for y in [4,5]:\n            if x == 2:\n                continue\n            yield seed + x * y\n    return 77\n',
            'def values(seed):\n    x = 0\n    while x < 4:\n        x = x + 1\n        if x == 3:\n            break\n        yield seed + x\n    return x\n',
            'def values(seed):\n    got = yield seed\n    if got is None:\n        yield seed + 1\n    return 41\n',
            'def values(seed):\n    if seed < 0:\n        yield 0\n    return 13\n',
        ]
        for source in sources:
            with self.subTest(source=source):
                ns = {}
                exec(source, ns)
                expected = []
                for seed in (7, 90):
                    iterator, values = ns['values'](seed), []
                    try:
                        while True:
                            values.append(next(iterator))
                    except StopIteration as exc:
                        expected.append((values, exc.value))
                artifact = source_artifact(source)
                self.assertEqual(len(artifact.target_coverage['generator_lowering']['bodies']), 1)
                self.assertTrue(any(b['terminator']['opcode'] == 5
                    for u in artifact.compact_document['units'] for b in u['blocks']))
                checks = []
                for index in range(len(expected[0][0])):
                    for handle in range(2):
                        checks.append(f'CHECK(resume(&f,h[{handle}],&value)==PYZ80_VM_YIELDED && value.payload=={expected[handle][0][index]});')
                for handle in range(2):
                    checks.append(f'CHECK(resume(&f,h[{handle}],&value)==PYZ80_VM_RETURNED && value.payload=={expected[handle][1]});')
                compile_run(PRELUDE + artifact_header(artifact) + SETUP + r'''
int main(void) {
    Fixture f;PyZ80VMValue arg,value;uint16_t h[2];unsigned cycle;
    CHECK(setup(&f));
    for(cycle=0;cycle<100;++cycle) {
        arg=integer(7);CHECK(PyZ80VM_GeneratorCreateArgs(&f.vm,0,0,&arg,1,&h[0])==PYZ80_VM_IDLE);
        arg=integer(90);CHECK(PyZ80VM_GeneratorCreateArgs(&f.vm,0,0,&arg,1,&h[1])==PYZ80_VM_IDLE);
        CHECK(!f.vm.call_depth && !f.vm.generators[h[0]].reserved && !f.vm.generators[h[1]].reserved);
        arg=integer(1000);
''' + '\n'.join(checks) + r'''
        CHECK(!f.vm.call_depth && f.vm.active_generator==PYZ80_VM_NO_GENERATOR);
        CHECK(resume(&f,h[0],&value)==PYZ80_VM_ERROR && f.vm.error==PYZ80_VM_E_GENERATOR_STATE);
        CHECK(PyZ80VM_GeneratorClose(&f.vm,h[0])==PYZ80_VM_IDLE);
        CHECK(PyZ80VM_GeneratorClose(&f.vm,h[1])==PYZ80_VM_IDLE);
    }
    CHECK(setup(&f));arg=integer(7);
    CHECK(PyZ80VM_GeneratorCreateArgs(&f.vm,0,0,&arg,1,&h[0])==PYZ80_VM_IDLE);
    CHECK(PyZ80VM_GeneratorResume(&f.vm,h[0],&arg,1,&value)==PYZ80_VM_ERROR);
    CHECK(!f.vm.call_depth && !f.vm.generators[h[0]].done);
    CHECK(resume(&f,h[0],&value)!=PYZ80_VM_ERROR);
    CHECK(setup(&f));arg=integer(7);
    CHECK(PyZ80VM_StartArgs(&f.vm,0,&arg,1)==PYZ80_VM_RUNNING);
    CHECK(finish(&f,&value)==PYZ80_VM_ERROR);
    CHECK(f.vm.error==PYZ80_VM_E_ADAPTER);
    return 0;
}
''', gc=True)

    @unittest.skipUnless(TCC, "host compiler unavailable")
    def test_retained_closure_survives_owner_return_and_gc(self):
        source = ('def factory(seed):\n    def values():\n'
                  '        for x in [1,2,3]:\n            yield seed + x\n'
                  '        return seed\n    seed = seed + 10\n    return values\n')
        artifact = source_artifact(source)
        compile_run(PRELUDE + artifact_header(artifact) + SETUP + r'''
int main(void) {
    Fixture f;PyZ80VMValue arg,value;uint16_t h[2];unsigned i;
    CHECK(setup(&f));
    for(i=0;i<2;++i) {
        arg=integer(20*i);
        CHECK(PyZ80VM_StartArgs(&f.vm,0,&arg,1)==PYZ80_VM_RUNNING);
        CHECK(finish(&f,&value)==PYZ80_VM_RETURNED);
        CHECK(PyZ80VM_GeneratorCreateArgs(&f.vm,1,&value,0,0,&h[i])==PYZ80_VM_IDLE);
    }
    f.vm.result=integer(0);
    CHECK(PyZ80Target_Collect(&f.objects,&f.vm,&f.scopes,0,0,&f.gc));
    CHECK(resume(&f,h[0],&value)==PYZ80_VM_YIELDED && value.payload==11);
    CHECK(resume(&f,h[1],&value)==PYZ80_VM_YIELDED && value.payload==31);
    CHECK(resume(&f,h[0],&value)==PYZ80_VM_YIELDED && value.payload==12);
    CHECK(resume(&f,h[1],&value)==PYZ80_VM_YIELDED && value.payload==32);
    CHECK(resume(&f,h[1],&value)==PYZ80_VM_YIELDED && value.payload==33);
    CHECK(resume(&f,h[0],&value)==PYZ80_VM_YIELDED && value.payload==13);
    CHECK(resume(&f,h[1],&value)==PYZ80_VM_RETURNED && value.payload==30);
    CHECK(resume(&f,h[0],&value)==PYZ80_VM_RETURNED && value.payload==10);
    CHECK(PyZ80Target_Collect(&f.objects,&f.vm,&f.scopes,0,0,&f.gc));
    CHECK(f.gc.live_nodes==1);
    return 0;
}
''', gc=True)

    @unittest.skipUnless(TCC, "host compiler unavailable")
    def test_creation_during_call_and_yielded_heap_values_keep_exact_identity(self):
        source = ('def values(seed):\n    yield seed\n    yield [seed]\n    return seed\n'
                  'def noop():\n    return 0\n')
        artifact = source_artifact(source)
        build_list = next(r['adapter_id'] for r in artifact.adapter_table if r['op']=='build-list')
        compile_run(PRELUDE + artifact_header(artifact) + SETUP + f'\n#define LIST {build_list}\n' + r'''
int main(void) {
    Fixture f;PyZ80VMValue arg,seed,value;PyZ80VMFrame before;uint16_t handle,link;uint32_t identity,pc;
    CHECK(setup(&f));arg=integer(99);
    CHECK(PyZ80Target_Invoke(&f.objects,&f.vm,LIST,0,&arg,1,0,&seed));identity=seed.payload;
    CHECK(PyZ80VM_Start(&f.vm,1)==PYZ80_VM_RUNNING);
    before=f.vm.frames[0];pc=before.pc;
    CHECK(PyZ80VM_GeneratorCreateArgs(&f.vm,0,0,&seed,1,&handle)==PYZ80_VM_IDLE);
    CHECK(f.vm.status==PYZ80_VM_RUNNING && f.vm.call_depth==1);
    CHECK(!memcmp(&before,&f.vm.frames[0],sizeof(before)) && f.vm.frames[0].pc==pc);
    CHECK(f.objects.node_used==2 && f.objects.item_used==1);
    CHECK(finish(&f,&value)==PYZ80_VM_RETURNED);
    CHECK(resume(&f,handle,&value)==PYZ80_VM_YIELDED && value.payload==identity);
    link=(uint16_t)value.payload;CHECK(f.items[f.nodes[link-1].item_start].payload==99);
    CHECK(resume(&f,handle,&value)==PYZ80_VM_YIELDED && value.payload!=identity);
    link=(uint16_t)value.payload;CHECK(f.items[f.nodes[link-1].item_start].payload==identity);
    CHECK(resume(&f,handle,&value)==PYZ80_VM_RETURNED && value.payload==identity);
    CHECK(f.gc.live_nodes==2);
    CHECK(PyZ80VM_GeneratorClose(&f.vm,handle)==PYZ80_VM_IDLE);
    f.vm.result=integer(0);
    CHECK(PyZ80Target_Collect(&f.objects,&f.vm,&f.scopes,0,0,&f.gc) && f.gc.live_nodes==1);
    return 0;
}
''', gc=True)

    def test_complex_protocols_stay_pending_and_corrupt_descriptors_are_rejected(self):
        for source in (
            'def values():\n    yield from [1,2]\n',
            'def values():\n    try:\n        yield 1\n    finally:\n        x = 2\n',
            'def values():\n    try:\n        yield 1\n    except ValueError:\n        yield 2\n',
        ):
            artifact = source_artifact(source)
            self.assertFalse(artifact.target_coverage['generator_lowering']['bodies'])
            self.assertTrue(artifact.target_coverage['generator_lowering']['pending'])
        source = 'def values():\n    yield 1\n'
        cfg = lower_python_function_cfg(ast.parse(source).body[0], class_name=None,
            source_path=Path('fixture.py'), source_text=source).to_json()
        pristine = {'kind':1,'owner':0,'entry':cfg['entry'],'blocks':cfg['blocks'],
                    'meta':{k:v for k,v in cfg.items() if k not in ('blocks','expression_programs')}}
        for op in ('generator-save-frame','generator-restore-frame','generator-resume-value'):
            unit = copy.deepcopy(pristine)
            item = next(i for b in unit['blocks'] for i in b['instructions'] if i['op']==op)
            item['arguments'][0] = 77
            with self.assertRaisesRegex(ValueError, 'generator'):
                lower_generator_next_bodies([{'callable_id':'values'}],[unit])


if __name__ == '__main__':
    unittest.main()
