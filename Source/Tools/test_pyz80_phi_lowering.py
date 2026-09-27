"""Source AST -> compact bytecode -> actual C VM, with Python as oracle."""
from __future__ import annotations

import ast
import copy
import itertools
import operator
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from generate_pzvt_target_adapters import build_adapter_specs
from pyz80_compiler.frontend import lower_object_expression
from pyz80_compiler.phi_lowering import PhiLoweringError, lower_phi_units
from pyz80_compiler.whole_program_vm_backend import (
    CompactTargetVMOracle, build_whole_program_vm,
)
from test_pyz80_whole_program_vm_backend import (
    ROOT, TCC, block, instruction, terminator, function_cfg, _resign,
)

SOURCES = (
    "x and y", "x or y", "x if y else z", "(x and y) or z",
    "x and (y or z)", "x if y < z else z", "x < y < z",
    "x and (1 // y)", "(x or y) if z else (y and x)",
    "0 and missing", "1 or missing", "'%expr_0' if x else '%unknown'",
)


def expression_artifact():
    rows = []
    for index, source in enumerate(SOURCES):
        program = lower_object_expression(
            ast.parse(source, mode="eval").body, source_path=Path("synthetic.py"),
            source_text=source, program_id=f"case_{index}:expr").to_json()
        cfg = function_cfg(f"case_{index}", index + 1, [block("entry", [
            instruction(0, "execute-expression-cfg", [program["program_id"]], "%result")
        ], terminator("return", ["%result"], []))], expressions=[program])
        cfg["signature"]["parameters"] = [
            {"name": name, "kind": "positional-or-keyword", "default": None}
            for name in ("x", "y", "z")]
        _resign(cfg)
        rows.append({"callable_id": f"m::case_{index}@{index+1}", "module": "m",
                     "qualname": f"case_{index}", "cfg": cfg})
    graph = {"format": "synthetic.active-call-graph.v1",
             "call_graph": {"proven_reachable_callable_ids": [row["callable_id"] for row in rows],
                            "call_sites": [], "exact_internal_edge_count": 0},
             "callable_inventory": {"callables": rows}}
    _resign(graph)
    return build_whole_program_vm(graph)


def loop_unit():
    return {"name": "parallel_loop", "entry": "entry", "blocks": [
        block("entry", [instruction(0, "constant", [1], "%a0"),
                        instruction(1, "constant", [2], "%b0"),
                        instruction(2, "constant", [7], "%n0")],
              terminator("jump", [], ["header"])),
        block("header", [
            instruction(3, "phi", ["entry", "%a0", "step", "%b"], "%a", incoming_count=2),
            instruction(4, "phi", ["entry", "%b0", "step", "%a"], "%b", incoming_count=2),
            instruction(5, "phi", ["entry", "%n0", "step", "%next"], "%n", incoming_count=2)
        ], terminator("branch-truth", ["%n"], ["step", "done"])),
        block("step", [instruction(6, "vm-binary-i32", ["sub", "%n", 1], "%next")],
              terminator("jump", [], ["header"])),
        block("done", [instruction(7, "vm-binary-i32", ["mul", "%a", 10], "%ten"),
                       instruction(8, "vm-binary-i32", ["add", "%ten", "%b"], "%result")],
              terminator("return", ["%result"], [])),
    ]}


def loop_artifact():
    unit = loop_unit()
    cfg = function_cfg("loop", 1, unit["blocks"])
    graph = {"format": "synthetic.active-call-graph.v1",
             "call_graph": {"proven_reachable_callable_ids": ["m::loop@1"],
                            "call_sites": [], "exact_internal_edge_count": 0},
             "callable_inventory": {"callables": [
                 {"callable_id": "m::loop@1", "module": "m", "qualname": "loop", "cfg": cfg}]}}
    _resign(graph)
    return build_whole_program_vm(graph)


HARNESS = r'''
#include <stdint.h>
#include <stdio.h>
#include "pyz80_whole_program_vm.h"
#include "pyz80_target_object_runtime.h"
#include "fixture.h"
int main(void) {
    PyZ80TargetContext context;
    PyZ80TargetNode nodes[8];
    PyZ80TargetField fields[64];
    PyZ80VMAdapter adapter;
    PyZ80VMMemoryImage memory = {image_bytes, sizeof(image_bytes)};
    PyZ80VMImage image = {PyZ80VM_MemoryRead, &memory, sizeof(image_bytes), proof};
    PyZ80VMLimits limits = {2, 0, FRAME_SLOTS, 3};
    union {uint32_t align; uint8_t bytes[ARENA_BYTES];} arena;
    PyZ80VM vm;
    PyZ80VMValue args[3], result;
    unsigned index, function, argc, k[3], status;
    long v[3];
    PyZ80Target_Init(&context, nodes, 8, fields, 64, 0, 0,
                     specs, ADAPTER_COUNT, ops, OPERATOR_COUNT, 0, 0);
    adapter = PyZ80Target_VMAdapter(&context);
    if (PyZ80VM_Init(&vm, &image, &adapter, arena.bytes, sizeof(arena.bytes), &limits)
        != PYZ80_VM_IDLE) return 1;
    while (scanf("%u %u %u %ld %u %ld %u %ld", &function, &argc,
                 &k[0], &v[0], &k[1], &v[1], &k[2], &v[2]) == 8) {
        PyZ80Target_Init(&context, nodes, 8, fields, 64, 0, 0,
                         specs, ADAPTER_COUNT, ops, OPERATOR_COUNT, 0, 0);
        context.field_keys = field_keys;
        context.field_key_count = FIELD_KEY_COUNT;
        for (index=0; index<3; ++index) {
            args[index].kind = k[index] ? PYZ80_VM_VALUE_BOOL : PYZ80_VM_VALUE_I32;
            args[index].reserved = 0;
            args[index].symbol = PYZ80_VM_NO_SYMBOL;
            args[index].payload = (uint32_t)v[index];
        }
        status = PyZ80VM_StartArgs(&vm, (uint16_t)function, args, (uint8_t)argc);
        if (status == PYZ80_VM_RUNNING) status = PyZ80VM_Run(&vm, 5000, &result);
        if (status != PYZ80_VM_RETURNED) {
            printf("%u %u 0 0\n", status, PyZ80VM_LastError(&vm)); continue;
        }
        printf("%u %u %ld %u\n", status, result.kind,
               (long)(int32_t)result.payload, result.symbol);
    }
    return 0;
}
'''


def run_c(artifact, lines):
    constants = artifact.compact_document["constants"]
    function_ids = (artifact.function_ids if hasattr(artifact, "function_ids") else
                    [*artifact.document["proven_reachable_callable_ids"],
                     *artifact.document.get("guarded_callable_ids", ())])
    plan = build_adapter_specs(list(artifact.adapter_table), constants, function_ids)
    specs, operators, keys = plan["specs"], plan["operators"], plan["field_keys"]
    slots = max(u["frame_slot_count"] for u in artifact.compact_document["units"])
    header = (
        "static const uint8_t image_bytes[] = {" + ",".join(map(str, artifact.target_bytecode)) + "};\n"
        "static const uint8_t proof[] = {" + ",".join(map(str, bytes.fromhex(artifact.semantic_sha256))) + "};\n"
        f"#define FRAME_SLOTS {slots}\n#define ARENA_BYTES {2*18+2*slots*10+3*8+64}\n"
        f"#define ADAPTER_COUNT {len(specs)}\n#define OPERATOR_COUNT {len(operators)}\n"
        f"#define FIELD_KEY_COUNT {len(keys)}\n"
        "static const uint16_t field_keys[] = {" + ",".join(map(str, keys or [0])) + "};\n"
        "static const PyZ80TargetAdapterSpec specs[] = {" +
        (",".join(f"{{{op},{count},{aux}}}" for op, count, aux in specs) or "{0,0,0}") + "};\n"
        "static const PyZ80TargetOperatorSpec ops[] = {" +
        (",".join(f"{{{symbol},{op},0}}" for symbol, op in operators) or "{0,0,0}") + "};\n")
    with tempfile.TemporaryDirectory(prefix="pyz80-phi-c-") as raw:
        directory = Path(raw)
        for name in ("pyz80_whole_program_vm.c", "pyz80_whole_program_vm.h",
                     "pyz80_target_object_runtime.c", "pyz80_target_object_runtime.h",
                     "pyz80_target_deque.c", "pyz80_target_deque.h", "pyz80_target_buffers.c", "pyz80_target_buffers.h"):
            shutil.copy2(ROOT / "Source/C/python_vm" / name, directory / name)
        (directory / "fixture.h").write_text(header)
        (directory / "check.c").write_text(HARNESS)
        built = subprocess.run([str(TCC), "-std=c11", "-Wall", "-Werror", "-o", "check.exe",
                                "check.c", "pyz80_whole_program_vm.c", "pyz80_target_object_runtime.c", "pyz80_target_deque.c", "pyz80_target_buffers.c"],
                               cwd=directory, capture_output=True, text=True, timeout=120)
        if built.returncode:
            raise AssertionError(built.stdout + built.stderr)
        run = subprocess.run([str(directory / "check.exe")], cwd=directory,
                             input="\n".join(lines) + "\n", capture_output=True, text=True, timeout=60)
        if run.returncode:
            raise AssertionError(f"C runner failed: {run.returncode}: {run.stderr}")
    return [tuple(map(int, row.split())) for row in run.stdout.splitlines()]


class PhiLoweringTests(unittest.TestCase):
    def test_parallel_loop_copies_preserve_old_values(self):
        original = loop_unit()
        before = copy.deepcopy(original)
        _, proof = lower_phi_units([original])
        self.assertEqual(original, before)
        self.assertEqual(proof["scratch_local_count"], 1)
        self.assertEqual(CompactTargetVMOracle(loop_artifact()).run(0), 21)

    def test_invalid_phi_is_rejected(self):
        for mutation in ("missing", "duplicate", "non_predecessor", "wrong_definition",
                         "late_phi", "entry_phi", "exception"):
            with self.subTest(mutation=mutation):
                unit = loop_unit()
                item = unit["blocks"][1]["instructions"][0]
                if mutation == "missing": item["arguments"] = item["arguments"][:2]
                if mutation == "duplicate": item["arguments"][2] = "entry"
                if mutation == "non_predecessor": item["arguments"][0] = "done"
                if mutation == "wrong_definition": item["arguments"][1] = "%next"
                if mutation == "late_phi":
                    unit["blocks"][1]["instructions"].insert(0, instruction(0, "constant", [0], "%fresh"))
                if mutation == "entry_phi": unit["entry"] = "header"
                if mutation == "exception": unit["blocks"][3]["exception_target"] = "header"
                with self.assertRaises(PhiLoweringError): lower_phi_units([unit])

    def test_short_circuit_preserves_object_identity_and_skips_missing_name(self):
        artifact = expression_artifact()
        self.assertFalse(any(row["op"] == "phi" for row in artifact.adapter_table))
        oracle = CompactTargetVMOracle(artifact)
        x, y, z = [1], [2], []
        for index in (0, 1, 2, 3, 4, 8):
            self.assertIs(oracle.run(index, [x, y, z]), eval(SOURCES[index], {}, {"x": x, "y": y, "z": z}))
        self.assertEqual(oracle.run(9, [0, 0, 0]), 0)
        self.assertEqual(oracle.run(10, [0, 0, 0]), 1)
        self.assertEqual(oracle.run(11, [1, 0, 0]), "%expr_0")

    def test_rich_comparison_returns_original_object_without_extra_truth_calls(self):
        artifact = expression_artifact()
        events = []

        class Comparison:
            def __init__(self, label, truth): self.label, self.truth = label, truth
            def __bool__(self):
                events.append(("bool", self.label))
                return self.truth

        class Operand:
            def __init__(self, label, result): self.label, self.result = label, result
            def __lt__(self, other):
                events.append(("lt", self.label, other.label))
                return self.result

        def adapter(_id, args, desc):
            self.assertEqual(desc["op"], "python-compare")
            self.assertEqual(args[0], "lt")
            return operator.lt(args[1], args[2])

        oracle = CompactTargetVMOracle(artifact, adapter=adapter)
        for truth in (False, True):
            first, final = Comparison("first", truth), Comparison("last", False)
            x, y, z = Operand("x", first), Operand("y", final), Operand("z", None)
            events.clear()
            expected = x < y < z
            expected_events = list(events)
            events.clear()
            actual = oracle.run(6, [x, y, z])
            self.assertIs(actual, expected)
            self.assertEqual(events, expected_events)

    @unittest.skipUnless(TCC, "TCC unavailable")
    def test_ast_to_c_vm_matches_python(self):
        artifact = expression_artifact()
        cases = [(index, values) for index in range(len(SOURCES))
                 for values in itertools.product((-7, 0, 1, 9, False, True), repeat=3)]
        lines = [f"{index} 3 " + " ".join(f"{int(type(v) is bool)} {int(v)}" for v in values)
                 for index, values in cases]
        rows = run_c(artifact, lines)
        self.assertEqual(len(rows), len(cases))
        for (index, values), row in zip(cases, rows):
            with self.subTest(expression=SOURCES[index], values=values):
                try:
                    expected = eval(SOURCES[index], {}, dict(zip(("x", "y", "z"), values)))
                except ZeroDivisionError:
                    self.assertEqual(row[:2], (4, 10))  # Exact arithmetic provider is absent.
                    continue
                self.assertEqual(row[0], 2)
                if isinstance(expected, str):
                    self.assertEqual(row[1], 3)
                    self.assertEqual(artifact.compact_document["constants"][row[3]], expected)
                else:
                    self.assertEqual(row[1], 1 if type(expected) is bool else 2)
                    self.assertEqual(row[2], expected)
        self.assertEqual(run_c(loop_artifact(), ["0 0 0 0 0 0 0 0"])[0][:3], (2, 2, 21))
        print(f"AST/PZVT/C/Python phi cases: {len(cases)} + cyclic parallel-copy loop")


if __name__ == "__main__":
    unittest.main()
