"""Source AST -> real C VM: retained lexical cells, not callback snapshots."""
from __future__ import annotations

import ast
import copy
import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
import unittest

from generate_pzvt_target_adapters import build_adapter_specs
from pyz80_compiler.function_cfg import lower_python_function_cfg
from pyz80_compiler.whole_program_vm_backend import build_whole_program_vm, _sha256_json
from test_pyz80_callable_runtime import compile_run, PRELUDE
from test_pyz80_whole_program_vm_backend import (
    _resign, TCC, guarded_lexical_dispatch_abi_graph, instruction, terminator,
)
from test_pyz80_target_object_runtime import RUNTIME, SDCC

SOURCE = '''def factory(seed):
    x = seed
    def inner(y):
        return x + y
    x = seed + 3
    return inner
'''


def source_artifact(source=SOURCE):
    parsed = ast.parse(source)
    top_functions = [node for node in parsed.body if isinstance(node, ast.FunctionDef)]
    outer = top_functions[0]
    owner_id = "m::factory@1"
    rows = []
    def visit(node, identity, parent):
        cfg = lower_python_function_cfg(node, class_name=None, source_path=Path("fixture.py"),
                                        source_text=source).to_json()
        rows.append({"callable_id": identity, "module": "m", "qualname": identity.split("::")[1].split("@")[0],
                     "lexical_parent_id": parent,
                     "ast_sha256": hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest(),
                     "cfg": cfg})
        for child in node.body:
            if isinstance(child, ast.FunctionDef):
                visit(child, identity.rsplit("@", 1)[0] + f".<locals>.{child.name}@{child.lineno}", identity)
    visit(outer, owner_id, None)
    for other in top_functions[1:]:
        visit(other, f"m::{other.name}@{other.lineno}", None)
    graph = {"format": "synthetic.active-call-graph.v1",
             "call_graph": {"proven_reachable_callable_ids": [row["callable_id"] for row in rows], "call_sites": [],
                            "exact_internal_edge_count": 0},
             "callable_inventory": {"callables": rows}}
    graph["semantic_sha256"] = _sha256_json(graph)
    return build_whole_program_vm(graph)


class ScopeRuntimeTests(unittest.TestCase):
    @unittest.skipUnless(TCC, "host compiler unavailable")
    def test_source_calls_native_closures_without_provider_or_c_recursion(self):
        sources = [
            'def factory(seed):\n    f = lambda y: seed + y\n    return f(3) + f(5)\n',
            'def factory(seed):\n    def f(y):\n        return seed + y\n    return f(3) + f(5)\n',
            'def factory(seed):\n    f = lambda y: seed + y\n    return f()\n',
            'def factory(seed):\n    result = [x + seed for x in [-2, 0, 1, 3] if x > 0]\n    return result[0] + result[1]\n',
            'def factory(seed):\n    result = [x for x in []]\n    return 99 if result else seed\n',
            'def factory(seed):\n    x = 100\n    result = [x * 2 for x in [1, 2, 3]]\n    return x + result[2]\n',
            'def factory(seed):\n    result = [x * 10 + y for x in [1, 2, 3] if x > 1 for y in [4, 5] if y != x]\n    return result[0] + result[3]\n',
            'def factory(seed):\n    result = [x + y + seed for x, y in [(1, 2), (3, 4)]]\n    return result[0] + result[1]\n',
            'def factory(seed):\n    result = [x + seed for x in [0,1,2,3,4,5,6,7,8,9,10,11]]\n    return result[11]\n',
            'def factory(seed):\n    f = lambda y: seed + y\n    result = [f(x) for x in [1,2,3]]\n    return result[0] + result[2]\n',
            'def factory(seed):\n    def values():\n        return [seed, seed + 1]\n    result = [x * 2 for x in values()]\n    return result[0] + result[1]\n',
            'def factory(seed):\n    _pz_result = seed\n    result = [x + _pz_result for x in [1,2]]\n    return result[1]\n',
            'def factory(seed):\n    result = [x for x in ["dobkeratops_body", "other", "dobkeratops_body"] if x == "dobkeratops_body"]\n    return seed if result[1] == "dobkeratops_body" else 0\n',
            'def factory(seed):\n    seen = [0]\n    def accept(x):\n        seen[0] = seen[0] + 1\n        return x > 1\n    result = [x for x in [1,2,3] if accept(x)]\n    return seen[0] * 10 + result[1]\n',
            'def factory(seed):\n    seen = [0]\n    def values():\n        seen[0] = seen[0] + 1\n        return [1,2,3]\n    def accept(x):\n        seen[0] = seen[0] + 10\n        return x > 1\n    result = [x for x in values() if accept(x)]\n    return seen[0] * 10 + result[1]\n',
        ]
        for source in sources:
            with self.subTest(source=source):
                artifact = source_artifact(source)
                ids = artifact.target_coverage["function_id_table"]
                plan = build_adapter_specs(artifact.adapter_table, artifact.compact_document["constants"], ids)
                self.assertEqual(set(plan["unsupported"]), {"python-call"})
                namespace = {}
                exec(source, namespace)
                try:
                    expected = namespace["factory"](7)
                    error = False
                except TypeError:
                    expected = 0
                    error = True
                header = (
                    "static const uint8_t bytes[]={" + ",".join(map(str, artifact.target_bytecode)) + "};\n"
                    "static const uint8_t proof[]={" + ",".join(map(str, bytes.fromhex(artifact.semantic_sha256))) + "};\n"
                    "static const uint16_t keys[]={" + ",".join(map(str, plan["field_keys"])) + "};\n"
                    "static const uint16_t arities[]={" + ",".join(map(str, artifact.target_coverage["positional_call_arities"])) + "};\n"
                    "static const PyZ80TargetAdapterSpec specs[]={" +
                    ",".join(f"{{{op},{count},{aux}}}" for op,count,aux in plan["specs"]) +
                    ",{PYZ80_TARGET_ALLOCATE_INSTANCE,1,0}};\n"
                    "static const PyZ80TargetOperatorSpec ops[]={" +
                    ",".join(f"{{{key},{op},0}}" for key,op in plan["operators"]) + "};\n"
                    f"#define ALLOCATE {len(plan['specs'])}\n#define OP_COUNT {len(plan['operators'])}\n"
                    f"#define EXPECTED {expected}\n#define EXPECT_ERROR {int(error)}\n#define FUNCTION_COUNT {len(ids)}\n")
                compile_run(PRELUDE + '#include "pyz80_target_scope_runtime.h"\n' + header + r'''
static unsigned fallbacks;
static uint8_t external(void *c, PyZ80VM *vm, uint16_t a, uint16_t d,
    const PyZ80VMValue *args, uint8_t n, uint32_t off, PyZ80VMValue *result) {
    (void)c;(void)vm;(void)a;(void)d;(void)args;(void)n;(void)off;
    ++fallbacks;*result=integer(999);return 1;
}
int main(void) {
    PyZ80TargetContext objects; PyZ80TargetScopes scopes;
    PyZ80TargetNode nodes[64]; PyZ80TargetField fields[8];
    PyZ80VMValue items[256],frames[8],globals[FUNCTION_COUNT],arg,result;
    PyZ80VM vm; PyZ80VMAdapter adapter; PyZ80VMLimits limits={8,0,64,12};
    PyZ80VMMemoryImage memory={bytes,sizeof(bytes)};
    PyZ80VMImage image={PyZ80VM_MemoryRead,&memory,sizeof(bytes),proof};
    union {uint32_t align; uint8_t bytes[8192];} arena;
    uint8_t status;
    uint16_t i;
    PyZ80Target_Init(&objects,nodes,64,fields,8,items,256,specs,ALLOCATE+1,ops,OP_COUNT,external,0);
    objects.field_keys=keys;objects.field_key_count=sizeof(keys)/sizeof(keys[0]);objects.function_count=FUNCTION_COUNT;
    objects.positional_call_arities=arities;
    arg=integer(0);arg.kind=PYZ80_VM_VALUE_SYMBOL;arg.symbol=77;
    CHECK(PyZ80Target_Invoke(&objects,0,ALLOCATE,0,&arg,1,0,&globals[0]));
    for(i=1;i<FUNCTION_COUNT;++i)globals[i]=globals[0];
    adapter=PyZ80Target_VMAdapter(&objects);
    CHECK(PyZ80VM_Init(&vm,&image,&adapter,arena.bytes,sizeof(arena.bytes),&limits)==PYZ80_VM_IDLE);
    CHECK(PyZ80Target_AttachScopes(&scopes,&objects,&vm,frames,8,globals,FUNCTION_COUNT));
    arg=integer(7);CHECK(PyZ80VM_StartArgs(&vm,0,&arg,1)==PYZ80_VM_RUNNING);
    status=PyZ80VM_Run(&vm,1000,&result);
    CHECK(EXPECT_ERROR ? status==PYZ80_VM_ERROR : status==PYZ80_VM_RETURNED && result.payload==EXPECTED);
    CHECK(fallbacks==0);
    return 0;
}
''', scopes=True)

    def test_lambda_definitions_do_not_become_reachability_edges(self):
        from pyz80_compiler.whole_program_vm_stack_bound import _unit_labels, _compact_core_proof
        source = 'def factory(seed):\n    a = lambda y: seed + y\n    b = lambda y: seed + y\n    return a\n'
        artifact = source_artifact(source)
        self.assertEqual(artifact.document["proven_reachable_callable_ids"], ["m::factory@1"])
        self.assertEqual(artifact.target_coverage["definition_only_function_count"], 2)
        ids = artifact.target_coverage["function_id_table"]
        self.assertEqual(len(set(ids)), 3)
        labels, functions = _unit_labels(artifact.document)
        self.assertEqual(list(functions), artifact.compact_document["functions"])
        proof = _compact_core_proof(artifact.document, artifact.compact_document, "m::factory@1",
                                   compact_unit_labels=artifact.target_coverage["compact_unit_labels"])
        self.assertEqual(proof["definition_only_function_count"], 2)
        self.assertEqual(proof["guarded_callable_function_count"], 0)
        self.assertEqual(len(labels), len(artifact.compact_document["units"]))

    def test_lambda_seals_are_checked_and_defaults_are_not_discarded(self):
        from pyz80_compiler.whole_program_vm_backend import _unit_specs
        from pyz80_compiler.lambda_lowering import materialize_lambda_definitions
        artifact = source_artifact('def factory(seed):\n    return lambda y: seed + y\n')
        for field, value in (("source", "seed - y"), ("ast_sha256", "0" * 64)):
            functions, units = _unit_specs(copy.deepcopy(artifact.document))
            item = next(item for unit in units for block in unit["blocks"]
                        for item in block["instructions"] if item["op"] == "make-lambda-function")
            item["attributes"]["body"][field] = value
            with self.assertRaisesRegex(ValueError, "seal mismatch"):
                materialize_lambda_definitions(functions, units)
        defaulted = source_artifact('def factory(seed):\n    return lambda y=seed: y\n')
        self.assertEqual(defaulted.target_coverage["definition_only_function_count"], 1)
        self.assertIn("make-source-function-defaults", [item["op"] for item in defaulted.adapter_table])
        functions, units = _unit_specs(copy.deepcopy(defaulted.document))
        item = next(item for unit in units for block in unit["blocks"]
                    for item in block["instructions"] if item["op"] == "make-lambda-function")
        item["attributes"]["default_expressions"][0][1]["source"] = "seed + 1"
        from pyz80_compiler.lambda_lowering import _hash
        item["attributes"]["scope_semantic_sha256"] = _hash({k:v for k,v in item["attributes"].items() if k != "scope_semantic_sha256"})
        with self.assertRaisesRegex(ValueError, "default expression seal mismatch"):
            materialize_lambda_definitions(functions, units)

    @unittest.skipUnless(TCC, "host compiler unavailable")
    def test_finite_dispatch_uses_callable_environment_not_same_named_active_owner(self):
        graph, lowering, abi = guarded_lexical_dispatch_abi_graph()
        rows = graph["callable_inventory"]["callables"]
        rows[0]["cfg"]["signature"]["parameters"] += [
            {"name": name, "kind": "positional-or-keyword", "default": None}
            for name in ("callback_a", "callback_b")]
        for row in rows[1:]:
            target = row["cfg"]["blocks"][0]
            # Remove the unrelated external-call sentinel from the shared ABI
            # fixture; this test must execute solely through native runtimes.
            target["instructions"] = [item for item in target["instructions"]
                                      if item.get("destination") not in {"%guard_ref", "%guard_ignored"}]
            target["instructions"].append(instruction(6, "vm-binary-i32", ["add", "%value", "%captured"], "%answer"))
            target["terminator"] = terminator("return", ["%answer"], [])
        for row in rows:
            _resign(row["cfg"])
        _resign(graph)
        lowering["active_call_graph_semantic_sha256"] = graph["semantic_sha256"]
        _resign(lowering)
        abi["active_call_graph_semantic_sha256"] = graph["semantic_sha256"]
        abi["call_site_lowering_semantic_sha256"] = lowering["semantic_sha256"]
        _resign(abi)
        artifact = build_whole_program_vm(graph, active_call_site_lowering=lowering, whole_program_vm_call_abi=abi)
        ids = [*artifact.document["proven_reachable_callable_ids"], *artifact.document["guarded_callable_ids"]]
        adapters = list(artifact.adapter_table)
        count = len(adapters)
        for identity in ids[1:]:
            adapters.append({"op": "make-source-function", "argument_count": 2,
                             "attributes": {"source_callable_id": identity, "closure_names": ["captured"]}})
        plan = build_adapter_specs(adapters, artifact.compact_document["constants"], ids)
        self.assertFalse(plan["unsupported"])
        header = (
            "static const uint8_t bytes[]={" + ",".join(map(str, artifact.target_bytecode)) + "};\n"
            "static const uint8_t proof[]={" + ",".join(map(str, bytes.fromhex(artifact.semantic_sha256))) + "};\n"
            "static const uint16_t keys[]={" + ",".join(map(str, plan["field_keys"])) + "};\n"
            "static const uint16_t dispatch[]={" + ",".join(map(str, plan["dispatch_functions"])) + "};\n"
            "static const PyZ80TargetAdapterSpec specs[]={" +
            ",".join(f"{{{op},{count},{aux}}}" for op,count,aux in plan["specs"]) +
            ",{PYZ80_TARGET_ALLOCATE_INSTANCE,1,0}};\n"
            f"#define ALLOCATE {len(plan['specs'])}\n#define MAKE_A {count}\n#define MAKE_B {count+1}\n")
        compile_run(PRELUDE + '#include "pyz80_target_scope_runtime.h"\n' + header + r'''
int main(void) {
    PyZ80TargetContext objects; PyZ80TargetScopes scopes;
    PyZ80TargetNode nodes[12]; PyZ80TargetField fields[8];
    PyZ80VMValue items[12],frames[8],globals[3],args[3],prepared[2],result,a,b;
    PyZ80VM vm; PyZ80VMAdapter adapter; PyZ80VMLimits limits={8,0,64,12};
    PyZ80VMMemoryImage memory={bytes,sizeof(bytes)};
    PyZ80VMImage image={PyZ80VM_MemoryRead,&memory,sizeof(bytes),proof};
    union {uint32_t align; uint8_t bytes[8192];} arena;
    PyZ80Target_Init(&objects,nodes,12,fields,8,items,12,specs,ALLOCATE+1,0,0,0,0);
    objects.field_keys=keys; objects.field_key_count=sizeof(keys)/sizeof(keys[0]); objects.function_count=3;
    objects.dispatch_functions=dispatch; objects.dispatch_function_count=sizeof(dispatch)/sizeof(dispatch[0]);
    args[0]=integer(0);args[0].kind=PYZ80_VM_VALUE_SYMBOL;args[0].symbol=77;
    CHECK(PyZ80Target_Invoke(&objects,0,ALLOCATE,0,args,1,0,&globals[0])); globals[1]=globals[2]=globals[0];
    adapter=PyZ80Target_VMAdapter(&objects);
    CHECK(PyZ80VM_Init(&vm,&image,&adapter,arena.bytes,sizeof(arena.bytes),&limits)==PYZ80_VM_IDLE);
    CHECK(PyZ80Target_AttachScopes(&scopes,&objects,&vm,frames,8,globals,3));
    prepared[0]=globals[0]; args[0]=integer(7);
    CHECK(scopes.hooks.cell(&scopes,PYZ80_VM_CELL_CREATE,0,args,&prepared[1]));
    CHECK(PyZ80Target_Invoke(&objects,&vm,MAKE_A,0,prepared,2,0,&a));
    args[0]=integer(11);
    CHECK(scopes.hooks.cell(&scopes,PYZ80_VM_CELL_CREATE,0,args,&prepared[1]));
    CHECK(PyZ80Target_Invoke(&objects,&vm,MAKE_B,0,prepared,2,0,&b));
    args[0]=integer(999); args[1]=a; args[2]=b;
    CHECK(PyZ80VM_StartArgs(&vm,0,args,3)==PYZ80_VM_RUNNING);
    CHECK(PyZ80VM_Run(&vm,1000,&result)==PYZ80_VM_RETURNED);
    CHECK(result.payload==36); /* (7-2)+7 + (9+4)+11; not the caller's 999. */
    CHECK(objects.node_used==5);
    return 0;
}
''', scopes=True)

    @unittest.skipUnless(TCC, "host compiler unavailable")
    def test_recapture_from_returned_environment_preserves_cell_identity(self):
        source = '''def factory(seed):
    x = seed
    def inner(y):
        def leaf(z):
            return x + y + z
        return leaf
    x = seed + 3
    return inner
'''
        artifact = source_artifact(source)
        plan = build_adapter_specs(list(artifact.adapter_table), artifact.compact_document["constants"],
                                   artifact.document["proven_reachable_callable_ids"])
        self.assertFalse(plan["unsupported"])
        namespace = {}
        exec(source, namespace)
        inner = namespace["factory"](7)
        expected = [inner(y)(5) for y in (2, 20)]
        header = (
            "static const uint8_t bytes[]={" + ",".join(map(str, artifact.target_bytecode)) + "};\n"
            "static const uint8_t proof[]={" + ",".join(map(str, bytes.fromhex(artifact.semantic_sha256))) + "};\n"
            "static const uint16_t keys[]={" + ",".join(map(str, plan["field_keys"])) + "};\n"
            "static const PyZ80TargetAdapterSpec specs[]={" +
            ",".join(f"{{{op},{count},{aux}}}" for op,count,aux in plan["specs"]) +
            ",{PYZ80_TARGET_ALLOCATE_INSTANCE,1,0}};\n"
            "static const PyZ80TargetOperatorSpec ops[]={" +
            ",".join(f"{{{key},{op},0}}" for key,op in plan["operators"]) + "};\n"
            f"#define ALLOCATE {len(plan['specs'])}\n#define OP_COUNT {len(plan['operators'])}\n"
            f"#define EXPECTED_A {expected[0]}\n#define EXPECTED_B {expected[1]}\n")
        compile_run(PRELUDE + '#include "pyz80_target_scope_runtime.h"\n' + header + r'''
int main(void) {
    PyZ80TargetContext objects; PyZ80TargetScopes scopes;
    PyZ80TargetNode nodes[24]; PyZ80TargetField fields[8];
    PyZ80VMValue items[24],frames[8],globals[3],arg,result,outer,a,b;
    PyZ80VM vm; PyZ80VMAdapter adapter; PyZ80VMLimits limits={8,0,64,12};
    PyZ80VMMemoryImage memory={bytes,sizeof(bytes)};
    PyZ80VMImage image={PyZ80VM_MemoryRead,&memory,sizeof(bytes),proof};
    union {uint32_t align; uint8_t bytes[8192];} arena;
    PyZ80Target_Init(&objects,nodes,24,fields,8,items,24,specs,ALLOCATE+1,ops,OP_COUNT,0,0);
    objects.field_keys=keys; objects.field_key_count=sizeof(keys)/sizeof(keys[0]); objects.function_count=3;
    arg=integer(0);arg.kind=PYZ80_VM_VALUE_SYMBOL;arg.symbol=77;
    CHECK(PyZ80Target_Invoke(&objects,0,ALLOCATE,0,&arg,1,0,&globals[0])); globals[1]=globals[2]=globals[0];
    adapter=PyZ80Target_VMAdapter(&objects);
    CHECK(PyZ80VM_Init(&vm,&image,&adapter,arena.bytes,sizeof(arena.bytes),&limits)==PYZ80_VM_IDLE);
    CHECK(PyZ80Target_AttachScopes(&scopes,&objects,&vm,frames,8,globals,3));
    arg=integer(7);CHECK(PyZ80VM_StartArgs(&vm,0,&arg,1)==PYZ80_VM_RUNNING);
    CHECK(PyZ80VM_Run(&vm,1000,&outer)==PYZ80_VM_RETURNED);
    arg=integer(2);CHECK(PyZ80VM_StartClosure(&vm,1,&outer,&arg,1)==PYZ80_VM_RUNNING);
    CHECK(PyZ80VM_Run(&vm,1000,&a)==PYZ80_VM_RETURNED);
    arg=integer(20);CHECK(PyZ80VM_StartClosure(&vm,1,&outer,&arg,1)==PYZ80_VM_RUNNING);
    CHECK(PyZ80VM_Run(&vm,1000,&b)==PYZ80_VM_RETURNED);
    arg=integer(5);CHECK(PyZ80VM_StartClosure(&vm,2,&a,&arg,1)==PYZ80_VM_RUNNING);
    CHECK(PyZ80VM_Run(&vm,1000,&result)==PYZ80_VM_RETURNED && result.payload==EXPECTED_A);
    CHECK(PyZ80VM_StartClosure(&vm,2,&b,&arg,1)==PYZ80_VM_RUNNING);
    CHECK(PyZ80VM_Run(&vm,1000,&result)==PYZ80_VM_RETURNED && result.payload==EXPECTED_B);
    CHECK(objects.node_used==7 && objects.item_used==10);
    CHECK(items[1].payload==items[3].payload && items[1].payload==items[7].payload);
    CHECK(items[5].payload!=items[9].payload);
    return 0;
}
''', scopes=True)

    def test_definition_defaults_retain_source_operands_for_runtime_binding(self):
        artifact = source_artifact(SOURCE.replace("inner(y)", "inner(y=4)"))
        operations = [row["op"] for row in artifact.adapter_table]
        self.assertNotIn("make-function", operations)
        self.assertIn("make-source-function-defaults", operations)
        row = next(row for row in artifact.adapter_table if row["op"] == "make-source-function-defaults")
        self.assertEqual(row["attributes"]["default_names"], ["y"])
        self.assertEqual(row["attributes"]["closure_names"], ["x"])
        self.assertEqual(row["argument_count"], 3)

    @unittest.skipUnless(SDCC, "Z80 compiler unavailable")
    def test_scope_runtime_compiles_for_z80_with_no_static_scratch(self):
        with tempfile.TemporaryDirectory(prefix="pz-scope-z80-") as raw:
            directory = Path(raw)
            for name in ("pyz80_whole_program_vm.h", "pyz80_target_object_runtime.h",
                         "pyz80_target_scope_runtime.h", "pyz80_target_scope_runtime.c"):
                shutil.copy2(RUNTIME / name, directory / name)
            environment = os.environ.copy()
            environment["PATH"] = str(SDCC.parent) + os.pathsep + environment.get("PATH", "")
            run = subprocess.run([str(SDCC), "-mz80", "--std-c11", "--sdcccall", "1",
                                  "--stack-auto", "--opt-code-speed", "-c", "pyz80_target_scope_runtime.c"],
                                 cwd=directory, env=environment, capture_output=True, text=True, timeout=120)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn("A _DATA size 0 ", (directory / "pyz80_target_scope_runtime.rel").read_text())

    @unittest.skipUnless(TCC, "host compiler unavailable")
    def test_returned_closures_keep_separate_cells_and_late_parent_assignments(self):
        self.check_returned_closure(SOURCE)

    @unittest.skipUnless(TCC, "host compiler unavailable")
    def test_lambda_keeps_separate_cells_and_late_parent_assignments(self):
        self.check_returned_closure(SOURCE.replace(
            "    def inner(y):\n        return x + y", "    inner = lambda y: x + y"))

    def check_returned_closure(self, source):
        artifact = source_artifact(source)
        ids = artifact.target_coverage["function_id_table"]
        plan = build_adapter_specs(list(artifact.adapter_table), artifact.compact_document["constants"], ids)
        self.assertFalse(plan["unsupported"], plan["unsupported"])
        self.assertEqual(plan["supported"]["make-source-function"], 1)
        namespace = {}
        exec(source, namespace)
        expected = [namespace["factory"](seed)(y) for seed, y in ((7, 2), (100, 2), (7, -4), (100, 9))]
        header = (
            "static const uint8_t bytes[]={" + ",".join(map(str, artifact.target_bytecode)) + "};\n"
            "static const uint8_t proof[]={" + ",".join(map(str, bytes.fromhex(artifact.semantic_sha256))) + "};\n"
            "static const uint16_t keys[]={" + ",".join(map(str, plan["field_keys"])) + "};\n"
            "static const PyZ80TargetAdapterSpec specs[]={" +
            ",".join(f"{{{op},{count},{aux}}}" for op,count,aux in plan["specs"]) +
            ",{PYZ80_TARGET_ALLOCATE_INSTANCE,1,0}};\n"
            "static const PyZ80TargetOperatorSpec ops[]={" +
            ",".join(f"{{{key},{op},0}}" for key,op in plan["operators"]) + "};\n"
            f"#define ALLOCATE {len(plan['specs'])}\n#define OP_COUNT {len(plan['operators'])}\n"
            "static const uint32_t expected[]={" + ",".join(map(str, expected)) + "};\n")
        compile_run(PRELUDE + '#include "pyz80_target_scope_runtime.h"\n' + header + r'''
static unsigned fallbacks;
static uint8_t permissive(void *context, PyZ80VM *vm, uint16_t adapter, uint16_t dest,
    const PyZ80VMValue *args, uint8_t count, uint32_t offset, PyZ80VMValue *result) {
    (void)context;(void)vm;(void)adapter;(void)dest;(void)args;(void)count;(void)offset;
    ++fallbacks; *result=integer(999); return 1;
}
int main(void) {
    PyZ80TargetContext objects; PyZ80TargetScopes scopes;
    PyZ80TargetNode nodes[24]; PyZ80TargetField fields[8];
    PyZ80VMValue items[24],frames[8],globals[2],arg,result,a,b;
    PyZ80VM vm; PyZ80VMAdapter adapter; PyZ80VMLimits limits={8,0,64,12};
    PyZ80VMMemoryImage memory={bytes,sizeof(bytes)};
    PyZ80VMImage image={PyZ80VM_MemoryRead,&memory,sizeof(bytes),proof};
    union {uint32_t align; uint8_t bytes[8192];} arena;
    PyZ80Target_Init(&objects,nodes,24,fields,8,items,24,specs,ALLOCATE+1,ops,OP_COUNT,0,0);
    objects.field_keys=keys; objects.field_key_count=sizeof(keys)/sizeof(keys[0]); objects.function_count=2;
    arg=integer(0);arg.kind=PYZ80_VM_VALUE_SYMBOL;arg.symbol=77;
    CHECK(PyZ80Target_Invoke(&objects,0,ALLOCATE,0,&arg,1,0,&globals[0])); globals[1]=globals[0];
    adapter=PyZ80Target_VMAdapter(&objects);
    CHECK(PyZ80VM_Init(&vm,&image,&adapter,arena.bytes,sizeof(arena.bytes),&limits)==PYZ80_VM_IDLE);
    CHECK(PyZ80Target_AttachScopes(&scopes,&objects,&vm,frames,8,globals,2));
    arg=integer(7);
    CHECK(PyZ80VM_StartArgs(&vm,0,&arg,1)==PYZ80_VM_RUNNING);
    CHECK(PyZ80VM_Run(&vm,1000,&a)==PYZ80_VM_RETURNED);
    arg=integer(100);
    CHECK(PyZ80VM_StartArgs(&vm,0,&arg,1)==PYZ80_VM_RUNNING);
    CHECK(PyZ80VM_Run(&vm,1000,&b)==PYZ80_VM_RETURNED);
    CHECK(a.payload!=b.payload);
    arg=integer(2);
    CHECK(PyZ80VM_StartClosure(&vm,1,&a,&arg,1)==PYZ80_VM_RUNNING);
    CHECK(PyZ80VM_Run(&vm,1000,&result)==PYZ80_VM_RETURNED && result.payload==expected[0]);
    CHECK(PyZ80VM_StartClosure(&vm,1,&b,&arg,1)==PYZ80_VM_RUNNING);
    CHECK(PyZ80VM_Run(&vm,1000,&result)==PYZ80_VM_RETURNED && result.payload==expected[1]);
    arg=integer((uint32_t)-4);
    CHECK(PyZ80VM_StartClosure(&vm,1,&a,&arg,1)==PYZ80_VM_RUNNING);
    CHECK(PyZ80VM_Run(&vm,1000,&result)==PYZ80_VM_RETURNED && result.payload==expected[2]);
    arg=integer(9);
    CHECK(PyZ80VM_StartClosure(&vm,1,&b,&arg,1)==PYZ80_VM_RUNNING);
    CHECK(PyZ80VM_Run(&vm,1000,&result)==PYZ80_VM_RETURNED && result.payload==expected[3]);
    CHECK(objects.node_used==5 && objects.item_used==4);
    /* A corrupt retained cell must fail, even if an external provider would
       happily invent a global value for the same name. */
    objects.provider=permissive;
    items[1].payload^=0x10000UL;
    CHECK(PyZ80VM_StartClosure(&vm,1,&a,&arg,1)==PYZ80_VM_RUNNING);
    CHECK(PyZ80VM_Run(&vm,1000,&result)==PYZ80_VM_ERROR && fallbacks==0);
    items[1].payload^=0x10000UL;
    objects.provider=0;
    /* Insufficient scope slots must not replace the attached valid hooks. */
    CHECK(!PyZ80Target_AttachScopes(&scopes,&objects,&vm,frames,1,globals,2));
    CHECK(vm.scope_hooks==&scopes.hooks);
    a.payload^=0x10000UL;
    CHECK(PyZ80VM_StartClosure(&vm,1,&a,&arg,1)==PYZ80_VM_ERROR);
    return 0;
}
''', scopes=True)


if __name__ == "__main__":
    unittest.main()
