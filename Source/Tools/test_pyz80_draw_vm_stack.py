from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from check_pyz80_draw_vm_stack import (
    CALLBACK_CONTRACT_FORMAT,
    DrawVMStackError,
    StackAnalyzer,
    _load_callback_contracts,
    parse_sdcc_assembly,
    probe,
)


ROOT = Path(__file__).resolve().parents[2]


def _synthetic_assembly(object_body: str) -> str:
    return f"""
_rtype_python_draw_vm_object_field:
{object_body}
_rtype_python_draw_vm_transient_field:
    ret
_rtype_python_draw_vm_eval:
    call ___sdcc_call_iy
    ret
_rtype_python_draw_vm_conditions:
    ret
_rtype_python_draw_vm_input_valid:
    ret
_rtype_python_draw_vm_walk:
    call ___sdcc_call_iy
    call ___sdcc_call_iy
    call ___sdcc_call_iy
    ret
_rtype_python_draw_vm_emit_to_buffer:
    ret
_rtype_python_draw_vm_produce::
    ret
_rtype_python_draw_vm_stream::
    ret
"""


class DrawVMStackUnitTests(unittest.TestCase):
    def test_growing_stack_cycle_fails_closed(self) -> None:
        functions = parse_sdcc_assembly(_synthetic_assembly("""
00100$:
    push af
    jr 00100$
"""))
        analyzer = StackAnalyzer(functions, 4)
        with self.assertRaisesRegex(DrawVMStackError, "cycle|unbounded"):
            analyzer.summary("_rtype_python_draw_vm_object_field")

    def test_unknown_direct_call_fails_closed(self) -> None:
        functions = parse_sdcc_assembly(_synthetic_assembly("""
    call _not_certified
    ret
"""))
        analyzer = StackAnalyzer(functions, 4)
        with self.assertRaisesRegex(DrawVMStackError, "unresolved direct call"):
            analyzer.summary("_rtype_python_draw_vm_object_field")

    def test_callback_contract_must_match_abi(self) -> None:
        callbacks = {}
        for name, argument_bytes in (
            ("resolve_resource_type", 0),
            ("load_object", 2),
            ("resolve_bank_key", 2),
            ("emit_record", 0),
        ):
            callbacks[name] = {
                "maximum_additional_stack_bytes_from_entry_sp": 8,
                "abi_stack_argument_bytes": argument_bytes,
                "return_address_bytes": 2,
                "callee_cleans_stack_arguments": True,
                "evidence": {"test": True},
            }
        callbacks["load_object"]["abi_stack_argument_bytes"] = 0
        value = {"format": CALLBACK_CONTRACT_FORMAT, "callbacks": callbacks}
        with tempfile.TemporaryDirectory(prefix="draw-vm-contract-") as temp:
            path = Path(temp) / "callbacks.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(DrawVMStackError, "load_object"):
                _load_callback_contracts(path)


class DrawVMStackPinnedSDCCTests(unittest.TestCase):
    def test_active_python_vm_internal_stack_certificate(self) -> None:
        report = probe(ROOT)
        self.assertEqual(
            report["status"],
            "INTERNAL_STACK_BOUND_PASS_EXTERNAL_CALLBACKS_BLOCKED")
        self.assertEqual(
            report["expression_dag"][
                "maximum_simultaneous_eval_invocations"], 4)
        self.assertTrue(
            report["expression_dag"][
                "logical_depth_is_not_used_as_a_byte_count"])

        functions = report["functions"]
        self.assertEqual(
            functions["rtype_python_draw_vm_eval"][
                "maximum_depth_from_function_entry_sp"], 92)
        self.assertEqual(
            functions["rtype_python_draw_vm_walk"][
                "maximum_depth_from_function_entry_sp"], 214)

        public = report["public_entries"]
        produce = public["rtype_python_draw_vm_produce"]
        stream = public["rtype_python_draw_vm_stream"]
        self.assertEqual(produce["public_stack_argument_bytes"], 4)
        self.assertEqual(stream["public_stack_argument_bytes"], 4)
        self.assertEqual(
            produce[
                "maximum_internal_bytes_including_public_stack_arguments"],
            241)
        self.assertEqual(
            stream[
                "maximum_internal_bytes_including_public_stack_arguments"],
            239)
        self.assertEqual(
            report["result"][
                "maximum_internal_stack_bytes_including_public_arguments"],
            241)

        expected_callbacks = {
            "resolve_resource_type", "load_object",
            "resolve_bank_key", "emit_record",
        }
        self.assertEqual(
            set(report["result"]["missing_external_callback_bounds"]),
            expected_callbacks)
        self.assertTrue(
            report["result"]["internal_vm_stack_bound_certified"])
        self.assertFalse(
            report["result"][
                "complete_vm_plus_callbacks_stack_bound_certified"])
        self.assertIsNone(
            report["result"]["complete_vm_plus_callbacks_stack_bytes"])
        self.assertFalse(report["result"]["live_target_use_certified"])

        boundaries = report["callback_contracts"]
        self.assertEqual(
            boundaries["resolve_resource_type"][
                "maximum_internal_bytes_to_entry_including_public_arguments"],
            214)
        self.assertEqual(
            boundaries["load_object"][
                "maximum_internal_bytes_to_entry_including_public_arguments"],
            133)
        self.assertEqual(
            boundaries["resolve_bank_key"][
                "maximum_internal_bytes_to_entry_including_public_arguments"],
            133)
        self.assertEqual(
            boundaries["emit_record"][
                "maximum_internal_bytes_to_entry_including_public_arguments"],
            131)
        for row in boundaries.values():
            self.assertEqual(row["status"], "MISSING_EXTERNAL_STACK_BOUND")
            self.assertIsNone(
                row["maximum_additional_stack_bytes_from_entry_sp"])

    def test_explicit_callback_bounds_are_composed_not_assumed(self) -> None:
        additions = {
            "resolve_resource_type": 40,
            "load_object": 10,
            "resolve_bank_key": 20,
            "emit_record": 30,
        }
        argument_bytes = {
            "resolve_resource_type": 0,
            "load_object": 2,
            "resolve_bank_key": 2,
            "emit_record": 0,
        }
        value = {
            "format": CALLBACK_CONTRACT_FORMAT,
            "callbacks": {
                name: {
                    "maximum_additional_stack_bytes_from_entry_sp": extra,
                    "abi_stack_argument_bytes": argument_bytes[name],
                    "return_address_bytes": 2,
                    "callee_cleans_stack_arguments": True,
                    "evidence": {"fixture": name},
                }
                for name, extra in additions.items()
            },
        }
        with tempfile.TemporaryDirectory(prefix="draw-vm-contract-") as temp:
            path = Path(temp) / "callbacks.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            report = probe(ROOT, path)
        self.assertEqual(
            report["status"],
            "VM_PLUS_CALLBACK_STACK_BOUND_PASS_LIVE_INTEGRATION_BLOCKED")
        self.assertEqual(
            report["result"]["complete_vm_plus_callbacks_stack_bytes"],
            254)
        self.assertTrue(
            report["result"][
                "complete_vm_plus_callbacks_stack_bound_certified"])
        self.assertFalse(report["result"]["live_target_use_certified"])


if __name__ == "__main__":
    unittest.main()
