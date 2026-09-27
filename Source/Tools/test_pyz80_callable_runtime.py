"""Execute finite Python callbacks in the real C object runtime, without stubs."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from generate_pzvt_target_adapters import build_adapter_specs
from pyz80_compiler.whole_program_vm_backend import build_whole_program_vm
from test_pyz80_target_object_runtime import RUNTIME, TCC
from test_pyz80_whole_program_vm_backend import (
    _resign, finite_bound_callback_abi_graph, instruction,
)


def compile_run(source, *, scopes=False, gc=False, builtins=False, bindings=False, imports=False, classes=False, dataclasses=False, banked=False, generators=False, sorting=False, sequences=False, defaultdicts=False, extra_sources=None):
    with tempfile.TemporaryDirectory(prefix="pyz80-callable-") as raw:
        directory = Path(raw)
        files = ["pyz80_whole_program_vm.c", "pyz80_whole_program_vm.h",
                 "pyz80_target_object_runtime.c", "pyz80_target_object_runtime.h",
                 "pyz80_target_deque.c", "pyz80_target_deque.h",
                 "pyz80_target_buffers.c", "pyz80_target_buffers.h"]
        if scopes or gc or bindings or imports or classes:
            files += ["pyz80_target_scope_runtime.c", "pyz80_target_scope_runtime.h"]
        if gc:
            files += ["pyz80_target_gc.c", "pyz80_target_gc.h"]
        if builtins:
            files += ["pyz80_target_builtins.c", "pyz80_target_builtins.h"]
        if bindings:
            files += ["pyz80_target_call_binding.c", "pyz80_target_call_binding.h"]
        if imports:
            files += ["pyz80_target_imports.c", "pyz80_target_imports.h"]
        if classes:
            files += ["pyz80_target_classes.c", "pyz80_target_classes.h",
                      "pyz80_target_type_checks.c", "pyz80_target_type_checks.h"]
        if dataclasses:
            if not classes:
                raise ValueError('dataclasses provider requires real native classes')
            files += ["pyz80_target_dataclasses.c", "pyz80_target_dataclasses.h"]
        if banked:
            files += ["pyz80_target_banked_tables.c", "pyz80_target_banked_tables.h",
                      "pyz80_banked_image.c", "pyz80_banked_image.h"]
        if generators:
            files += ["pyz80_target_generators.c", "pyz80_target_generators.h"]
        if sorting:
            if not generators:
                raise ValueError('sort tests require generator/control provider support')
            files += ["pyz80_target_sort.c", "pyz80_target_sort.h"]
        if sequences:
            if not generators:
                raise ValueError('sequence tests require shared control storage support')
            files += ["pyz80_target_sequences.c", "pyz80_target_sequences.h"]
        if defaultdicts:
            if not generators:
                raise ValueError('defaultdict tests require shared control storage support')
            files += ["pyz80_target_defaultdict.c", "pyz80_target_defaultdict.h"]
        for name in files:
            shutil.copy2(RUNTIME / name, directory / name)
        for name, content in (extra_sources or {}).items():
            (directory / name).write_text(content)
            files.append(name)
        (directory / "check.c").write_text(source)
        built = subprocess.run([str(TCC), "-std=c11", "-Wall", "-Werror", "-o", "check.exe",
                                "check.c", *(name for name in files if name.endswith(".c"))],
                               cwd=directory, capture_output=True, text=True, timeout=120)
        if built.returncode:
            raise AssertionError(built.stdout + built.stderr)
        run = subprocess.run([str(directory / "check.exe")], cwd=directory,
                             capture_output=True, text=True, timeout=30)
        if run.returncode:
            raise AssertionError(f"C runner failed: {run.returncode}: {run.stdout} {run.stderr}")


PRELUDE = r'''
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "pyz80_target_object_runtime.h"
#define CHECK(expr) do { if (!(expr)) { printf("line %d\n", __LINE__); return 1; } } while (0)
static PyZ80VMValue integer(uint32_t n) {
    PyZ80VMValue v = {PYZ80_VM_VALUE_I32, 0, PYZ80_VM_NO_SYMBOL, 0};
    v.payload = n; return v;
}
'''


def callback_artifact():
    graph, lowering, abi = finite_bound_callback_abi_graph()
    rows = graph["callable_inventory"]["callables"]
    rows[0]["cfg"]["signature"]["parameters"] = [
        {"name": name, "kind": "positional-or-keyword", "default": None}
        for name in ("callback_a", "callback_b")]
    # Each target writes through self, detecting wrong receiver binding even if
    # the arithmetic result happens to match. Call sites and signatures unchanged.
    for row in rows[1:]:
        instructions = row["cfg"]["blocks"][0]["instructions"]
        instructions.extend([
            instruction(3, "load-name", ["self"], "%self"),
            instruction(4, "store-attribute", ["%self", "answer", "%value"]),
        ])
    for row in rows:
        _resign(row["cfg"])
    _resign(graph)
    lowering["active_call_graph_semantic_sha256"] = graph["semantic_sha256"]
    _resign(lowering)
    abi["active_call_graph_semantic_sha256"] = graph["semantic_sha256"]
    abi["call_site_lowering_semantic_sha256"] = lowering["semantic_sha256"]
    _resign(abi)
    return build_whole_program_vm(graph, active_call_site_lowering=lowering,
                                  whole_program_vm_call_abi=abi)


class CallableRuntimeTests(unittest.TestCase):
    def test_generator_requires_exact_identities_and_deduplicates_slices(self):
        rows = [{"op": op, "argument_count": count, "candidate_callable_ids": ["b", "a"]}
                for op, count in (("resolve-finite-callable-identity", 1),
                                  ("extract-finite-bound-callable-receiver", 2))]
        plan = build_adapter_specs(rows, [], ["a", "b"])
        self.assertEqual(plan["dispatch_functions"], [2, 1, 0])
        self.assertEqual([spec[2] for spec in plan["specs"]], [0, 0])
        for candidates in ([], ["a", "a"], ["missing"], None):
            with self.subTest(candidates=candidates), self.assertRaises(RuntimeError):
                build_adapter_specs([dict(rows[0], candidate_callable_ids=candidates)], [], ["a", "b"])
        with self.assertRaises(RuntimeError):
            build_adapter_specs(rows, [])
        with self.assertRaises(RuntimeError):
            build_adapter_specs(rows, [], ["a", "a"])

    @unittest.skipUnless(TCC, "host compiler unavailable")
    def test_callable_identity_receiver_and_capacity_guards(self):
        compile_run(PRELUDE + r'''
int main(void) {
    PyZ80TargetNode nodes[12], before[12]; PyZ80TargetContext context;
    const PyZ80TargetAdapterSpec specs[] = {
        {PYZ80_TARGET_ALLOCATE_INSTANCE,1,0}, {PYZ80_TARGET_REQUIRE_CALLABLE,1,0},
        {PYZ80_TARGET_RESOLVE_CALLABLE,1,0}, {PYZ80_TARGET_BOUND_RECEIVER,2,0}};
    const uint16_t dispatch[] = {2,2,1};
    PyZ80VMValue a, b, freefn, bound_a, bound_b, alias, args[2], result, saved;
    uint16_t used;
    PyZ80Target_Init(&context,nodes,12,0,0,0,0,specs,4,0,0,0,0);
    context.function_count=4; context.dispatch_functions=dispatch;
    context.dispatch_function_count=3;
    args[0]=integer(0); args[0].kind=PYZ80_VM_VALUE_SYMBOL; args[0].symbol=77;
    CHECK(PyZ80Target_Invoke(&context,0,0,0,args,1,0,&a));
    CHECK(PyZ80Target_Invoke(&context,0,0,0,args,1,0,&b));
    CHECK(PyZ80Target_Callable(&context,1,0,&freefn));
    CHECK(PyZ80Target_Callable(&context,1,&a,&bound_a));
    CHECK(PyZ80Target_Callable(&context,1,&b,&bound_b));
    alias=a; CHECK(PyZ80Target_Callable(&context,2,&alias,&alias));
    args[0]=freefn;
    CHECK(PyZ80Target_Invoke(&context,0,1,0,args,1,0,&result));
    CHECK(result.payload==freefn.payload);
    CHECK(PyZ80Target_Invoke(&context,0,2,0,args,1,0,&result));
    CHECK(result.kind==PYZ80_VM_VALUE_I32 && result.payload==1);
    args[1]=integer(1);
    CHECK(!PyZ80Target_Invoke(&context,0,3,0,args,2,0,&result));
    args[0]=bound_a;
    CHECK(PyZ80Target_Invoke(&context,0,3,0,args,2,0,&result)); CHECK(result.payload==a.payload);
    args[0]=bound_b;
    CHECK(PyZ80Target_Invoke(&context,0,3,0,args,2,0,&result)); CHECK(result.payload==b.payload);
    args[1]=integer(0);
    CHECK(!PyZ80Target_Invoke(&context,0,3,0,args,2,0,&result));
    args[0]=alias;
    CHECK(PyZ80Target_Invoke(&context,0,3,0,args,2,0,&result)); CHECK(result.payload==a.payload);
    args[1]=integer(2); CHECK(!PyZ80Target_Invoke(&context,0,3,0,args,2,0,&result));
    args[1]=integer(0xffffffffUL); CHECK(!PyZ80Target_Invoke(&context,0,3,0,args,2,0,&result));
    args[0]=bound_a; args[0].payload^=0x10000UL;
    CHECK(!PyZ80Target_Invoke(&context,0,1,0,args,1,0,&result));
    args[0]=bound_a; args[0].payload|=0x80000000UL;
    CHECK(!PyZ80Target_Invoke(&context,0,1,0,args,1,0,&result));
    args[0]=bound_a; args[1]=integer(1); ++nodes[0].generation;
    CHECK(!PyZ80Target_Invoke(&context,0,3,0,args,2,0,&result)); --nodes[0].generation;
    CHECK(PyZ80Target_Callable(&context,3,0,&args[0]));
    CHECK(!PyZ80Target_Invoke(&context,0,2,0,args,1,0,&result));
    args[0]=bound_a; context.dispatch_function_count=2;
    CHECK(!PyZ80Target_Invoke(&context,0,2,0,args,1,0,&result));
    context.dispatch_function_count=3;
    used=context.node_used; result=integer(123); saved=result;
    memcpy(before,nodes,sizeof(nodes)); context.node_capacity=used;
    CHECK(!PyZ80Target_Callable(&context,1,&a,&result));
    CHECK(context.node_used==used && !memcmp(before,nodes,sizeof(nodes)) && !memcmp(&saved,&result,sizeof(result)));
    context.node_capacity=12;
    CHECK(!PyZ80Target_Callable(&context,4,&a,&result)); CHECK(context.node_used==used);
    CHECK(!PyZ80Target_Callable(&context,1,&saved,&result)); CHECK(context.node_used==used);
    return 0;
}
''')

    @unittest.skipUnless(TCC, "host compiler unavailable")
    def test_compiled_bound_callbacks_preserve_self_without_any_provider(self):
        artifact = callback_artifact()
        function_ids = [*artifact.document["proven_reachable_callable_ids"],
                        *artifact.document.get("guarded_callable_ids", ())]
        plan = build_adapter_specs(list(artifact.adapter_table), artifact.compact_document["constants"], function_ids)
        # LOAD_NAME keeps an external fallback descriptor even for parameters.
        # There is no provider: execution must resolve these from the VM frames.
        self.assertFalse(plan["unsupported"])
        answer_symbol = artifact.compact_document["constants"].index("answer")
        class Worker:
            def difference(self, *, left, right):
                self.answer = left - right
                return self.answer

            def decoy_difference(self, *, left, right):
                self.answer = left + right
                return self.answer

        a, b = Worker(), Worker()
        callbacks = [a.difference, b.difference, a.decoy_difference, b.decoy_difference]
        expected = []
        for first in callbacks:
            for second in callbacks:
                a.answer = b.answer = 0
                total = first(right=2, left=7) + second(right=4, left=9)
                expected.append((total, a.answer, b.answer))
        header = (
            "static const uint8_t bytes[]={" + ",".join(map(str, artifact.target_bytecode)) + "};\n"
            "static const uint8_t proof[]={" + ",".join(map(str, bytes.fromhex(artifact.semantic_sha256))) + "};\n"
            "static const uint16_t dispatch[]={" + ",".join(map(str, plan["dispatch_functions"])) + "};\n"
            "static const PyZ80TargetAdapterSpec specs[]={" +
            ",".join(f"{{{op},{count},{aux}}}" for op, count, aux in plan["specs"]) +
            ",{PYZ80_TARGET_ALLOCATE_INSTANCE,1,0}};\n"
            "static const uint32_t expected[][3]={" +
            ",".join("{" + ",".join(map(str, row)) + "}" for row in expected) + "};\n"
            f"#define ALLOCATE {len(plan['specs'])}\n#define ANSWER {answer_symbol}\n")
        compile_run(PRELUDE + header + r'''
int main(void) {
    PyZ80TargetNode nodes[8]; PyZ80TargetField fields[8]; PyZ80TargetContext context;
    PyZ80VM vm; PyZ80VMLimits limits={8,0,32,8};
    PyZ80VMMemoryImage memory={bytes,sizeof(bytes)};
    PyZ80VMImage image={PyZ80VM_MemoryRead,&memory,sizeof(bytes),proof};
    union {uint32_t align; uint8_t bytes[8192];} arena;
    PyZ80VMAdapter adapter; PyZ80VMValue a,b,args[2],result,callbacks[4],zero;
    uint8_t first,second,index;
    PyZ80Target_Init(&context,nodes,8,fields,8,0,0,specs,ALLOCATE+1,0,0,0,0);
    context.function_count=3; context.dispatch_functions=dispatch;
    context.dispatch_function_count=sizeof(dispatch)/sizeof(dispatch[0]);
    args[0]=integer(0); args[0].kind=PYZ80_VM_VALUE_SYMBOL; args[0].symbol=77;
    CHECK(PyZ80Target_Invoke(&context,0,ALLOCATE,0,args,1,0,&a));
    CHECK(PyZ80Target_Invoke(&context,0,ALLOCATE,0,args,1,0,&b));
    CHECK(PyZ80Target_Callable(&context,1,&a,&callbacks[0]));
    CHECK(PyZ80Target_Callable(&context,1,&b,&callbacks[1]));
    CHECK(PyZ80Target_Callable(&context,2,&a,&callbacks[2]));
    CHECK(PyZ80Target_Callable(&context,2,&b,&callbacks[3]));
    adapter=PyZ80Target_VMAdapter(&context);
    CHECK(PyZ80VM_Init(&vm,&image,&adapter,arena.bytes,sizeof(arena.bytes),&limits)==PYZ80_VM_IDLE);
    zero=integer(0); index=0;
    for(first=0;first<4;++first) for(second=0;second<4;++second) {
        CHECK(PyZ80Target_StoreField(&context,&a,ANSWER,&zero));
        CHECK(PyZ80Target_StoreField(&context,&b,ANSWER,&zero));
        args[0]=callbacks[first]; args[1]=callbacks[second];
        CHECK(PyZ80VM_StartArgs(&vm,0,args,2)==PYZ80_VM_RUNNING);
        CHECK(PyZ80VM_Run(&vm,1000,&result)==PYZ80_VM_RETURNED);
        CHECK(result.kind==PYZ80_VM_VALUE_I32 && result.payload==expected[index][0]);
        CHECK(PyZ80Target_LoadField(&context,&a,ANSWER,&result) && result.payload==expected[index][1]);
        CHECK(PyZ80Target_LoadField(&context,&b,ANSWER,&result) && result.payload==expected[index][2]);
        CHECK(context.node_used==6 && context.field_used==2);
        ++index;
    }
    return 0;
}
''')


if __name__ == "__main__":
    unittest.main()
