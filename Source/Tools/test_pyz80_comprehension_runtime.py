"""List-comprehension lowering contracts and bounded mutable list storage."""
import copy
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest

from generate_pzvt_target_adapters import build_adapter_specs
from pyz80_compiler.comprehension_lowering import materialize_list_comprehensions
from pyz80_compiler.whole_program_vm_backend import _unit_specs
from pyz80_compiler.whole_program_vm_stack_bound import _unit_labels, _compact_core_proof
from test_pyz80_scope_runtime import source_artifact
from test_pyz80_callable_runtime import compile_run, PRELUDE, TCC


class ComprehensionRuntimeTests(unittest.TestCase):
    @unittest.skipUnless(TCC, "host C compiler unavailable")
    def test_actual_boss_hit_flash_filter_matches_python_object_order(self):
        game = Path(__file__).resolve().parents[1] / "Python/rtype_port/game.py"
        parsed = ast.parse(game.read_text(encoding="utf-8"))
        method = next(n for n in ast.walk(parsed) if isinstance(n, ast.FunctionDef)
                      and n.name == "_sync_boss_hit_flash")
        expression = next(n for n in ast.walk(method) if isinstance(n, ast.ListComp))
        source = "def factory(self):\n    return " + ast.unparse(expression) + "\n"
        namespace = {}
        exec(source, namespace)
        enemies = [SimpleNamespace(kind=value) for value in ("dobkeratops_body", "enemy_world", "dobkeratops_body")]
        expected = namespace["factory"](SimpleNamespace(enemy_world=SimpleNamespace(enemies=enemies)))
        self.assertEqual([i for i,e in enumerate(enemies) if any(e is v for v in expected)], [0,2])
        artifact = source_artifact(source)
        constants = artifact.compact_document["constants"]
        ids = artifact.target_coverage["function_id_table"]
        plan = build_adapter_specs(artifact.adapter_table, constants, ids)
        self.assertEqual(set(plan["unsupported"]), {"python-call"})
        header = (
            "static const uint8_t bytes[]={" + ",".join(map(str, artifact.target_bytecode)) + "};\n"
            "static const uint8_t proof[]={" + ",".join(map(str, bytes.fromhex(artifact.semantic_sha256))) + "};\n"
            "static const uint16_t keys[]={" + ",".join(map(str, plan["field_keys"])) + "};\n"
            "static const uint16_t arities[]={" + ",".join(map(str, artifact.target_coverage["positional_call_arities"])) + "};\n"
            "static const PyZ80TargetAdapterSpec specs[]={" +
            ",".join(f"{{{op},{count},{aux}}}" for op,count,aux in plan["specs"]) +
            ",{PYZ80_TARGET_ALLOCATE_INSTANCE,1,0},{PYZ80_TARGET_BUILD_LIST,3,0}};\n"
            "static const PyZ80TargetOperatorSpec ops[]={" +
            ",".join(f"{{{key},{op},0}}" for key,op in plan["operators"]) + "};\n"
            f"#define ALLOCATE {len(plan['specs'])}\n#define OP_COUNT {len(plan['operators'])}\n" +
            "".join(f"#define {macro} {constants.index(name)}\n" for macro,name in
                    (("WORLD","enemy_world"),("ENEMIES","enemies"),("KIND","kind"),("BOSS","dobkeratops_body"))))
        compile_run(PRELUDE + '#include "pyz80_target_scope_runtime.h"\n' + header + r'''
int main(void) {
    PyZ80TargetContext objects;PyZ80TargetScopes scopes;
    PyZ80TargetNode nodes[16];PyZ80TargetField fields[16];
    PyZ80VMValue items[32],frames[8],globals[2],values[6],list,arg,result;
    PyZ80VM vm;PyZ80VMAdapter adapter;PyZ80VMLimits limits={8,0,64,12};
    PyZ80VMMemoryImage memory={bytes,sizeof(bytes)};
    PyZ80VMImage image={PyZ80VM_MemoryRead,&memory,sizeof(bytes),proof};
    union {uint32_t align;uint8_t bytes[8192];} arena;
    unsigned i;PyZ80TargetNode *returned;
    PyZ80Target_Init(&objects,nodes,16,fields,16,items,32,specs,ALLOCATE+2,ops,OP_COUNT,0,0);
    objects.field_keys=keys;objects.field_key_count=sizeof(keys)/sizeof(keys[0]);objects.function_count=2;
    objects.positional_call_arities=arities;
    arg=integer(0);arg.kind=PYZ80_VM_VALUE_SYMBOL;arg.symbol=0;
    for(i=0;i<6;++i)CHECK(PyZ80Target_Invoke(&objects,0,ALLOCATE,0,&arg,1,0,&values[i]));
    globals[0]=globals[1]=values[0];
    CHECK(PyZ80Target_Invoke(&objects,0,ALLOCATE+1,0,&values[3],3,0,&list));
    CHECK(PyZ80Target_StoreField(&objects,&values[1],WORLD,&values[2]));
    CHECK(PyZ80Target_StoreField(&objects,&values[2],ENEMIES,&list));
    for(i=3;i<6;++i) {
        arg.symbol=i==4?WORLD:BOSS;
        CHECK(PyZ80Target_StoreField(&objects,&values[i],KIND,&arg));
    }
    adapter=PyZ80Target_VMAdapter(&objects);
    CHECK(PyZ80VM_Init(&vm,&image,&adapter,arena.bytes,sizeof(arena.bytes),&limits)==PYZ80_VM_IDLE);
    CHECK(PyZ80Target_AttachScopes(&scopes,&objects,&vm,frames,8,globals,2));
    CHECK(PyZ80VM_StartArgs(&vm,0,&values[1],1)==PYZ80_VM_RUNNING);
    CHECK(PyZ80VM_Run(&vm,10000,&result)==PYZ80_VM_RETURNED);
    returned=&nodes[(uint16_t)result.payload-1];
    CHECK(returned->kind==PYZ80_TARGET_NODE_LIST && returned->item_count==2);
    CHECK(items[returned->item_start].payload==values[3].payload);
    CHECK(items[returned->item_start+1].payload==values[5].payload);
    return 0;
}
''', scopes=True)

    def test_sealed_definitions_are_reconstructed_by_stack_verifier(self):
        artifact = source_artifact('def factory(seed):\n    return [x + seed for x in [1,2] if x]\n')
        self.assertEqual(artifact.document["proven_reachable_callable_ids"], ["m::factory@1"])
        self.assertEqual(artifact.target_coverage["definition_only_function_count"], 1)
        labels, functions = _unit_labels(artifact.document)
        self.assertEqual(list(functions), artifact.compact_document["functions"])
        proof = _compact_core_proof(artifact.document, artifact.compact_document, "m::factory@1",
            compact_unit_labels=artifact.target_coverage["compact_unit_labels"])
        self.assertEqual(proof["definition_only_function_count"], 1)
        self.assertEqual(len(labels), len(artifact.compact_document["units"]))
        self.assertFalse(proof["finite_core_call_depth_proved"])
        for field, value in (("source", "x - seed"), ("ast_sha256", "0" * 64)):
            functions, units = _unit_specs(copy.deepcopy(artifact.document))
            item = next(i for u in units for b in u["blocks"] for i in b["instructions"]
                        if i["op"] == "run-eager-comprehension")
            item["attributes"]["plan"]["production"]["element"][field] = value
            with self.assertRaisesRegex(ValueError, "seal mismatch"):
                materialize_list_comprehensions(functions, units)

    def test_unimplemented_collection_and_nested_scopes_stay_explicit(self):
        for expression in ('{(lambda: x) for x in [1,2]}', '{x:lambda: x for x in [1,2]}',
                           '[lambda: x for x in [1,2]]'):
            with self.subTest(expression=expression):
                artifact = source_artifact('def factory(seed):\n    return ' + expression + '\n')
                self.assertEqual(artifact.target_coverage["definition_only_function_count"], 0)
                self.assertIn("run-eager-comprehension", [r["op"] for r in artifact.adapter_table])

    @unittest.skipUnless(TCC, "host C compiler unavailable")
    def test_list_growth_preserves_iterators_and_capacity_failure_is_atomic(self):
        compile_run(PRELUDE + r'''
int main(void) {
    PyZ80TargetContext context;
    PyZ80TargetNode nodes[8], before;
    PyZ80TargetField fields[1];
    PyZ80VMValue items[64], snapshot[64], args[2], list, iterator, same, result;
    const PyZ80TargetAdapterSpec specs[] = {
        {PYZ80_TARGET_BUILD_LIST,0,0}, {PYZ80_TARGET_LIST_APPEND,2,0},
        {PYZ80_TARGET_GET_ITERATOR,1,0}, {PYZ80_TARGET_ITER_NEXT,1,0},
        {PYZ80_TARGET_ITER_VALUE,1,0}, {PYZ80_TARGET_ITER_HAS_VALUE,1,0},
        {PYZ80_TARGET_LOAD_SUBSCRIPT,2,0}
    };
    unsigned i;
    PyZ80Target_Init(&context,nodes,8,fields,1,items,64,specs,7,0,0,0,0);
    CHECK(PyZ80Target_Invoke(&context,0,0,0,0,0,0,&list));
    args[0]=list;
    for(i=0;i<4;++i) {
        args[1]=integer(i);
        CHECK(PyZ80Target_Invoke(&context,0,1,0,args,2,0,&result));
        CHECK(result.kind==PYZ80_VM_VALUE_NONE);
    }
    CHECK(PyZ80Target_Invoke(&context,0,2,0,&list,1,0,&iterator));
    CHECK(PyZ80Target_Invoke(&context,0,3,0,&iterator,1,0,&result));
    CHECK(PyZ80Target_Invoke(&context,0,4,0,&iterator,1,0,&result) && result.payload==0);
    CHECK(PyZ80Target_Invoke(&context,0,2,0,&iterator,1,0,&same) && same.payload==iterator.payload);
    before=nodes[0];memcpy(snapshot,items,sizeof(items));
    context.item_capacity=context.item_used;
    args[1]=integer(4);
    CHECK(!PyZ80Target_Invoke(&context,0,1,0,args,2,0,&result));
    CHECK(!memcmp(&before,&nodes[0],sizeof(before)) && !memcmp(snapshot,items,sizeof(items)));
    context.item_capacity=64;
    CHECK(PyZ80Target_Invoke(&context,0,1,0,args,2,0,&result));
    CHECK(nodes[0].item_start!=before.item_start);
    for(i=1;i<5;++i) {
        CHECK(PyZ80Target_Invoke(&context,0,3,0,&iterator,1,0,&result));
        CHECK(PyZ80Target_Invoke(&context,0,4,0,&iterator,1,0,&result) && result.payload==i);
    }
    CHECK(PyZ80Target_Invoke(&context,0,3,0,&iterator,1,0,&result));
    CHECK(PyZ80Target_Invoke(&context,0,5,0,&iterator,1,0,&result) && result.payload==0);
    args[1]=integer(5);CHECK(PyZ80Target_Invoke(&context,0,1,0,args,2,0,&result));
    CHECK(PyZ80Target_Invoke(&context,0,3,0,&iterator,1,0,&result));
    CHECK(PyZ80Target_Invoke(&context,0,5,0,&iterator,1,0,&result) && result.payload==0);
    nodes[0].item_start=context.item_used+1;
    args[1]=integer(0);CHECK(!PyZ80Target_Invoke(&context,0,6,0,args,2,0,&result));
    CHECK(!PyZ80Target_Invoke(&context,0,1,0,args,2,0,&result));
    CHECK(!PyZ80Target_Invoke(&context,0,3,0,&iterator,1,0,&result));
    return 0;
}
''')


if __name__ == "__main__":
    unittest.main()
