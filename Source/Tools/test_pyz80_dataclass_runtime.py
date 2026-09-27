"""Generated field schema -> PZVT -> real C object storage and post-init."""
from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
import unittest

from generate_pzvt_target_adapters import build_adapter_specs
from pyz80_compiler.whole_program_vm_backend import build_compact_target_vm, build_whole_program_vm
from test_pyz80_phi_lowering import expression_artifact, run_c
from test_pyz80_whole_program_vm_backend import block, instruction, terminator, function_cfg, semantic, TCC


def dataclass_artifact():
    document = expression_artifact().document
    main = document["functions"][0]["row"]["cfg"]
    post = document["functions"][1]
    post_id = post["callable_id"]
    post_cfg = function_cfg("post", 2, [block("entry", [
        instruction(0, "load-name", ["self"], "%self"),
        instruction(1, "load-attribute", ["%self", "a"], "%a"),
        instruction(2, "load-attribute", ["%self", "b"], "%b"),
        instruction(3, "python-binary", ["add", "%a", "%b"], "%sum"),
        instruction(4, "store-attribute", ["%self", "total", "%sum"]),
    ], terminator("return", [], []))])
    post_cfg["signature"]["parameters"] = [{"name": "self", "kind": "positional-or-keyword"}]
    post["row"]["cfg"] = post_cfg
    schema = {"format": "pyz80.generated-dataclass-init.v1", "class_id": "m::Record@1",
              "fields": [{"name": "a"}, {"name": "b"}], "post_init_target": post_id}
    schema["semantic_sha256"] = semantic(schema)
    init = instruction(2, "python-call", ["%unused", "%a"], "%initialized")
    init["_target_direct_function"] = post_id
    init["_target_call_arguments"] = ["%self", "%a", 7]
    init["_target_call_abi"] = {"binding_mode": "generated-dataclass-init", "target": post_id,
                               "generated_dataclass_init": schema,
                               "call_argument_operands": ["%self", "%a", 7]}
    main["blocks"] = [block("entry", [
        instruction(0, "allocate-instance", ["m::Record@1"], "%self"),
        instruction(1, "load-name", ["a"], "%a"), init,
        instruction(3, "load-attribute", ["%self", "total"], "%result")
    ], terminator("return", ["%result"], []))]
    main["entry"] = "entry"
    main["expression_programs"] = []
    main["signature"]["parameters"] = [{"name": "a", "kind": "positional-or-keyword"}]
    # Remove unrelated fixture functions; their old parameterized AST is irrelevant.
    document["functions"] = document["functions"][:2]
    document["proven_reachable_callable_ids"] = [row["callable_id"] for row in document["functions"]]
    image, decoded, adapters, info = build_compact_target_vm(document)
    return SimpleNamespace(target_bytecode=image, compact_document=decoded, adapter_table=adapters,
                           function_ids=info["manifest"]["function_id_table"],
                           semantic_sha256=info["manifest"]["proof_document_semantic_sha256"])


class DataclassRuntimeTests(unittest.TestCase):
    def test_field_keys_are_source_named_shared_and_fail_closed(self):
        row = {"op": "store-generated-dataclass-fields", "argument_count": 3,
               "field_names": ["a", "b"]}
        plan = build_adapter_specs([row, row], [None, "b", "a"])
        self.assertEqual(plan["field_keys"], [2, 1])
        self.assertEqual([spec[2] for spec in plan["specs"]], [0, 0])
        for changed in ({**row, "field_names": ["a", "a"]},
                        {**row, "field_names": ["a", "absent"]},
                        {**row, "argument_count": 2}):
            with self.assertRaises(RuntimeError): build_adapter_specs([changed], ["a", "b"])

    @unittest.skipUnless(TCC, "TCC unavailable")
    def test_initializer_and_post_init_execute_in_c_without_custom_adapter(self):
        @dataclass
        class Record:
            a: int
            b: int = 7

            def __post_init__(self):
                self.total = self.a + self.b

        values = list(range(-20, 21))
        result = run_c(dataclass_artifact(), [f"0 1 0 {value} 0 0 0 0" for value in values])
        self.assertEqual(len(result), len(values))
        for value, row in zip(values, result):
            with self.subTest(value=value):
                self.assertEqual(row[:3], (2, 2, Record(value).total))


if __name__ == "__main__":
    unittest.main()
