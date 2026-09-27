from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import zlib

from pyz80_compiler.whole_program_vm_backend import (
    CompactTargetVMOracle,
    WholeProgramVMError,
    WholeProgramVMOracle,
    _expand_object_store_units,
    build_compact_target_vm,
    build_whole_program_vm,
    decode_compact_target_vm,
    decode_whole_program_vm,
    render_whole_program_vm_status,
    whole_program_vm_status,
)
from pyz80_compiler.active_call_site_lowering import (
    ACTIVE_CALL_SITE_LOWERING_FORMAT,
    ACTIVE_CALL_SITE_LOWERING_STATUS,
)
from pyz80_compiler.whole_program_vm_call_abi import (
    WHOLE_PROGRAM_VM_CALL_ABI_FORMAT,
    WHOLE_PROGRAM_VM_CALL_ABI_STATUS,
)


ROOT = Path(__file__).resolve().parents[2]
PYTHON = Path(__file__).resolve()
RUNTIME_C = ROOT / "Source/C/python_vm/pyz80_whole_program_vm.c"
RUNTIME_H = ROOT / "Source/C/python_vm/pyz80_whole_program_vm.h"
TCC_CANDIDATES = (
    ROOT.parent / "tcc-0.9.27/tcc/tcc.exe",
    Path("E:/zx/tcc-0.9.27/tcc/tcc.exe"),
)
SDCC_CANDIDATES = (
    Path("E:/zx/sdcc/bin/sdcc.exe"),
    Path("C:/Program Files/SDCC/bin/sdcc.exe"),
)
TCC = next((path for path in TCC_CANDIDATES if path.is_file()), None)
SDCC = next((path for path in SDCC_CANDIDATES if path.is_file()), None)


SPAN = {"path": "synthetic.py", "line": 1, "column": 0,
        "end_line": 1, "end_column": 1}


def semantic(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def instruction(sequence: int, op: str, arguments: list[object],
                destination: str | None = None,
                **attributes: object) -> dict[str, object]:
    result: dict[str, object] = {
        "sequence": sequence, "op": op, "arguments": arguments,
        "span": dict(SPAN),
    }
    if destination is not None:
        result["destination"] = destination
        result["value_kind"] = "py-value"
    if attributes:
        result["attributes"] = attributes
    return result


def terminator(op: str, arguments: list[object],
               targets: list[str]) -> dict[str, object]:
    return {"op": op, "arguments": arguments, "targets": targets,
            "span": dict(SPAN)}


def block(name: str, instructions: list[dict[str, object]],
          term: dict[str, object]) -> dict[str, object]:
    return {"name": name, "instructions": instructions, "terminator": term}


def function_cfg(name: str, line: int, blocks: list[dict[str, object]],
                 *, expressions: list[dict[str, object]] | None = None
                 ) -> dict[str, object]:
    result: dict[str, object] = {
        "function_id": f"{name}@{line}", "class": None, "function": name,
        "definition_line": line, "ast_sha256": semantic([name, line]),
        "signature": {"async": False, "decorators": [], "parameters": [],
                      "returns": "object"},
        "entry": blocks[0]["name"], "blocks": blocks,
        "expression_programs": expressions or [], "mutation_site_ids": [],
        "spliced_store_fragments": [], "blockers": [],
    }
    result["semantic_sha256"] = semantic(result)
    return result


def expression(name: str, value: int) -> dict[str, object]:
    result: dict[str, object] = {
        "program_id": name, "entry": "expr_entry", "result": "%expr_value",
        "result_kind": "py-int", "blocks": [block(
            "expr_entry", [instruction(0, "constant", [value], "%expr_value")],
            terminator("return-expression", ["%expr_value"], []))],
        "source": str(value), "ast_sha256": semantic(["constant", value]),
    }
    result["semantic_sha256"] = semantic(result)
    return result


def synthetic_graph() -> dict[str, object]:
    main_expression = expression("main@1:expression:0000", 4)
    main = function_cfg("main", 1, [
        block("entry", [
            instruction(0, "constant", [2], "%two"),
            instruction(1, "store-name", ["x", "%two"]),
            instruction(2, "load-name", ["x"], "%loaded"),
            instruction(3, "vm-call", ["m::helper@2"], "%five"),
            instruction(4, "vm-binary-i32",
                        ["add", "%loaded", "%five"], "%seven"),
        ], terminator("branch-truth", ["%seven"], ["yes", "no"])),
        block("yes", [
            instruction(5, "execute-expression-cfg",
                        ["main@1:expression:0000"], "%four"),
            instruction(6, "vm-binary-i32",
                        ["add", "%seven", "%four"], "%answer"),
        ], terminator("return", ["%answer"], [])),
        block("no", [instruction(7, "constant", [0], "%zero")],
              terminator("return", ["%zero"], [])),
    ], expressions=[main_expression])
    helper = function_cfg("helper", 2, [block(
        "entry", [instruction(0, "constant", [5], "%five")],
        terminator("return", ["%five"], []))])
    recurse = function_cfg("recurse", 3, [block(
        "entry", [instruction(0, "vm-call", ["m::recurse@3"], "%again")],
        terminator("return", ["%again"], []))])
    generator = function_cfg("generator", 4, [
        block("first", [instruction(0, "constant", [10], "%ten")],
              terminator("yield", ["%ten"], ["second"])),
        block("second", [instruction(1, "constant", [20], "%twenty")],
              terminator("yield", ["%twenty"], ["done"])),
        block("done", [instruction(2, "constant", [30], "%thirty")],
              terminator("return", ["%thirty"], [])),
    ])
    host = function_cfg("host", 5, [block(
        "entry", [instruction(0, "python-magic", [7], "%result")],
        terminator("return", ["%result"], []))])
    active_generator = function_cfg("active_generator", 6, [
        block("entry", [
            instruction(0, "generator-save-frame", ["frame", 0], "%saved"),
            instruction(1, "generator-restore-frame", ["%saved"], "%restored"),
            instruction(2, "generator-resume-value", ["%restored"], "%value"),
        ], terminator("suspend-yield", ["%value"], ["resume"])),
        block("resume", [], terminator("suspend-yield-from", [], ["entry"])),
    ])
    scope_caller = function_cfg("scope_caller", 7, [block(
        "entry", [
            instruction(0, "constant", [99], "%caller_value"),
            instruction(1, "store-name", ["shadow", "%caller_value"]),
            instruction(2, "store-name", ["shadow", "%caller_value"]),
            instruction(3, "vm-call", ["m::scope_callee@8"], "%callee_value"),
        ], terminator("return", ["%callee_value"], []))])
    scope_callee = function_cfg("scope_callee", 8, [block(
        "entry", [instruction(0, "load-name", ["shadow"], "%global_value")],
        terminator("return", ["%global_value"], []))])
    inner_expression = expression("nested_scope@9:expression:inner", 0)
    inner_expression["blocks"][0]["instructions"] = [
        instruction(0, "load-name", ["nested_name"], "%expr_value")]
    inner_expression["semantic_sha256"] = semantic({
        key: value for key, value in inner_expression.items()
        if key != "semantic_sha256"})
    outer_expression = expression("nested_scope@9:expression:outer", 0)
    outer_expression["blocks"][0]["instructions"] = [instruction(
        0, "execute-expression-cfg",
        ["nested_scope@9:expression:inner"], "%expr_value")]
    outer_expression["semantic_sha256"] = semantic({
        key: value for key, value in outer_expression.items()
        if key != "semantic_sha256"})
    nested_scope = function_cfg("nested_scope", 9, [block(
        "entry", [
            instruction(0, "constant", [42], "%nested_value"),
            instruction(1, "store-name", ["nested_name", "%nested_value"]),
            instruction(2, "execute-expression-cfg",
                        ["nested_scope@9:expression:outer"], "%result"),
        ], terminator("return", ["%result"], []))],
        expressions=[outer_expression, inner_expression])
    direct_python = function_cfg("direct_python", 10, [block(
        "entry", [
            instruction(0, "constant", ["helper-ref"], "%callable"),
            instruction(1, "python-call", ["%callable"], "%result",
                        argument_count=0, argument_layout=[], keywords=False),
        ], terminator("return", ["%result"], []))])
    large_frame_instructions = [
        instruction(index, "constant", [index], f"%wide_{index}")
        for index in range(260)]
    large_frame_instructions.extend(
        instruction(260 + index, "store-name",
                    [f"bound_{index}", "%wide_259"])
        for index in range(20))
    large_frame = function_cfg("large_frame", 11, [block(
        "entry", large_frame_instructions,
        terminator("return", ["%wide_259"], []))])
    unsafe_first = instruction(
        1, "python-call", ["%unsafe_ref_1"], "%unsafe_result_1",
        argument_count=0, argument_layout=[], keywords=False)
    unsafe_first["span"] = {**SPAN, "line": 2, "end_line": 2}
    unsafe_second = instruction(
        3, "python-call", ["%unsafe_ref_2"], "%unsafe_result_2",
        argument_count=0, argument_layout=[], keywords=False)
    unsafe_second["span"] = {**SPAN, "line": 3, "end_line": 3}
    unsafe_calls = function_cfg("unsafe_calls", 12, [block(
        "entry", [
            instruction(0, "constant", ["host-ref"], "%unsafe_ref_1"),
            unsafe_first,
            instruction(2, "constant", ["host-ref"], "%unsafe_ref_2"),
            unsafe_second,
        ], terminator("return", ["%unsafe_result_2"], []))])
    entry_argument = function_cfg("entry_argument", 13, [block(
        "entry", [instruction(0, "load-name", ["value"], "%value")],
        terminator("return", ["%value"], []))])
    entry_argument["signature"]["parameters"] = [{
        "name": "value", "kind": "positional-or-keyword", "default": None,
    }]
    _resign(entry_argument)
    unreachable = function_cfg("unreachable", 14, [block(
        "entry", [instruction(0, "constant", [0], "%zero")],
        terminator("return", ["%zero"], []))])
    rows = []
    identifiers = ["m::main@1", "m::helper@2", "m::recurse@3",
                   "m::generator@4", "m::host@5", "m::active_generator@6",
                    "m::scope_caller@7", "m::scope_callee@8",
                    "m::nested_scope@9", "m::direct_python@10",
                    "m::large_frame@11", "m::unsafe_calls@12",
                    "m::entry_argument@13"]
    for identifier, cfg in zip(
            identifiers, [main, helper, recurse, generator, host, active_generator,
                           scope_caller, scope_callee, nested_scope, direct_python,
                           large_frame, unsafe_calls, entry_argument]):
        rows.append({"callable_id": identifier, "module": "m",
                     "qualname": cfg["function"], "cfg": cfg})
    rows.append({"callable_id": "m::unreachable@14", "module": "m",
                  "qualname": "unreachable", "cfg": unreachable})
    direct_site = {
        "call_site_id": "direct-python-site", "caller": "m::direct_python@10",
        "line": 1, "column": 0, "end_line": 1, "end_column": 1,
        "resolution": {"kind": "exact-internal-function", "proven": True,
                       "targets": ["m::helper@2"]},
    }
    unreachable_site = {
        "call_site_id": "unreachable-site", "caller": "m::unreachable@14",
        "line": 1, "column": 0, "end_line": 1, "end_column": 1,
        "resolution": {"kind": "exact-internal-function", "proven": True,
                       "targets": ["m::helper@2"]},
    }
    unsafe_sites = [{
        "call_site_id": f"unsafe-site-{line}", "caller": "m::unsafe_calls@12",
        "line": line, "column": 0, "end_line": line, "end_column": 1,
        "resolution": {"kind": "host-boundary", "proven": False,
                       "targets": []},
    } for line in (2, 3)]
    graph: dict[str, object] = {
        "format": "synthetic.active-call-graph.v1",
        "call_graph": {
            "proven_reachable_callable_ids": identifiers,
            "call_sites": [direct_site, unreachable_site, *unsafe_sites],
            "exact_internal_edge_count": 2,
        },
        "callable_inventory": {"callables": rows},
    }
    graph["semantic_sha256"] = semantic(graph)
    return graph


def _resign(value: dict[str, object]) -> None:
    value["semantic_sha256"] = semantic({
        key: item for key, item in value.items()
        if key != "semantic_sha256"})


def _instruction_proof(row: dict[str, object]) -> dict[str, object]:
    return {
        "op": row.get("op"), "sequence": row.get("sequence"),
        "destination": row.get("destination"),
        "arguments": list(row.get("arguments", [])),
        "span": dict(row.get("span", {})),
    }


def abi_bound_keyword_graph() -> tuple[
        dict[str, object], dict[str, object], dict[str, object]]:
    """Two exact duplicate-site calls whose keyword order differs from ABI order."""
    caller_instructions = [
        instruction(0, "constant", ["receiver-A"], "%receiver_a"),
        instruction(1, "load-attribute",
                    ["%receiver_a", "difference"], "%source_a"),
        instruction(2, "require-callable", ["%source_a"], "%callable_a"),
        instruction(3, "constant", [2], "%right_a"),
        instruction(4, "constant", [7], "%left_a"),
        instruction(5, "python-call",
                    ["%callable_a", "%right_a", "%left_a"], "%result_a",
                    argument_count=2,
                    argument_layout=[["keyword", "right"],
                                     ["keyword", "left"]],
                    evaluation_order=["callable", "right", "left"],
                    keywords=True),
        instruction(6, "constant", ["receiver-B"], "%receiver_b"),
        instruction(7, "load-attribute",
                    ["%receiver_b", "difference"], "%source_b"),
        instruction(8, "require-callable", ["%source_b"], "%callable_b"),
        instruction(9, "constant", [4], "%right_b"),
        instruction(10, "constant", [9], "%left_b"),
        instruction(11, "python-call",
                    ["%callable_b", "%right_b", "%left_b"], "%result_b",
                    argument_count=2,
                    argument_layout=[["keyword", "right"],
                                     ["keyword", "left"]],
                    evaluation_order=["callable", "right", "left"],
                    keywords=True),
        instruction(12, "vm-binary-i32",
                    ["add", "%result_a", "%result_b"], "%total"),
    ]
    caller = function_cfg("abi_caller", 20, [block(
        "entry", caller_instructions,
        terminator("return", ["%total"], []))])
    target = function_cfg("difference", 21, [block(
        "entry", [
            instruction(0, "load-name", ["left"], "%loaded_left"),
            instruction(1, "load-name", ["right"], "%loaded_right"),
            instruction(2, "vm-binary-i32",
                        ["sub", "%loaded_left", "%loaded_right"], "%value"),
        ],
        terminator("return", ["%value"], []))])
    target["class"] = "Worker"
    target["signature"] = {
        "async": False, "decorators": [],
        "parameters": [
            {"name": "self", "kind": "positional-or-keyword",
             "default": None},
            {"name": "left", "kind": "positional-or-keyword",
             "default": None},
            {"name": "right", "kind": "positional-or-keyword",
             "default": None},
        ],
        "returns": "int",
    }
    _resign(target)
    decoy = function_cfg("decoy_difference", 22, [block(
        "entry", [
            instruction(0, "load-name", ["left"], "%loaded_left"),
            instruction(1, "load-name", ["right"], "%loaded_right"),
            instruction(2, "vm-binary-i32",
                        ["add", "%loaded_left", "%loaded_right"], "%value"),
        ],
        terminator("return", ["%value"], []))])
    decoy["class"] = "Worker"
    decoy["signature"] = copy.deepcopy(target["signature"])
    _resign(decoy)
    caller_id = "m::abi_caller@20"
    target_id = "m::Worker.difference@21"
    decoy_id = "m::Worker.decoy_difference@22"
    site_id = "abi-bound-duplicate-site"
    unrepresented_site_id = "abi-unrepresented-site"
    later_unrepresented_site_id = "abi-unrepresented-site-later"
    graph: dict[str, object] = {
        "format": "synthetic.active-call-graph.v1",
        "entrypoint": {"callable_id": caller_id},
        "call_graph": {
            "proven_reachable_callable_ids": [
                caller_id, target_id, decoy_id],
            "call_sites": [{
                "call_site_id": site_id, "caller": caller_id,
                "line": 1, "column": 0, "end_line": 1,
                "end_column": 1,
                "resolution": {
                    "kind": "exact-internal-method", "proven": True,
                    "targets": [target_id],
                },
            }, {
                "call_site_id": later_unrepresented_site_id,
                "caller": caller_id,
                "line": 3, "column": 0, "end_line": 3,
                "end_column": 1,
                "resolution": {
                    "kind": "exact-internal-method", "proven": True,
                    "targets": [decoy_id],
                },
            }, {
                "call_site_id": unrepresented_site_id, "caller": caller_id,
                "line": 2, "column": 0, "end_line": 2,
                "end_column": 1,
                "resolution": {
                    "kind": "exact-internal-method", "proven": True,
                    "targets": [decoy_id],
                },
            }],
            "exact_internal_edge_count": 3,
        },
        "callable_inventory": {"callables": [
            {"callable_id": caller_id, "module": "m",
             "qualname": "abi_caller", "cfg": caller},
            {"callable_id": target_id, "module": "m",
             "qualname": "Worker.difference", "cfg": target},
            {"callable_id": decoy_id, "module": "m",
             "qualname": "Worker.decoy_difference", "cfg": decoy},
        ]},
    }
    _resign(graph)

    signature = {
        "parameters": [
            {"name": name, "kind": "positional-or-keyword",
             "has_default": False, "default_ast_sha256": None}
            for name in ("self", "left", "right")
        ],
        "is_async": False, "is_classmethod": False,
        "is_staticmethod": False, "has_var_positional": False,
        "has_var_keyword": False,
    }
    occurrences: list[dict[str, object]] = []
    for occurrence_index, (instruction_index, suffix) in enumerate(
            ((5, "a"), (11, "b"))):
        occurrences.append({
            "cfg_occurrence_index": occurrence_index,
            "numeric_call_site_id": 1,
            "call_site_id": site_id,
            "caller": caller_id,
            "cfg_path": ["blocks", 0, "instructions", instruction_index],
            "program_id": None,
            "block_name": "entry",
            "instruction_sequence": instruction_index,
            "span": dict(SPAN),
            "callable_value": f"%callable_{suffix}",
            "argument_layout": [
                {"argument_index": 0, "kind": "keyword",
                 "keyword": "right", "value": f"%right_{suffix}"},
                {"argument_index": 1, "kind": "keyword",
                 "keyword": "left", "value": f"%left_{suffix}"},
            ],
            "destination": f"%result_{suffix}",
            "evaluation_order": ["callable", "right", "left"],
        })
    represented_site = {
        "source_order_index": 0,
        "numeric_call_site_id": 1,
        "call_site_id": site_id,
        "caller": caller_id,
        "span": dict(SPAN),
        "classification": "proven-single-internal",
        "binding_mode": "bound-method",
        "resolution_kind": "exact-internal-method",
        "proven": True,
        "targets": [target_id],
        "resolution_evidence": "synthetic-exact",
        "cfg_occurrence_count": 2,
        "cfg_occurrence_indexes": [0, 1],
    }
    unrepresented_site = {
        "source_order_index": 1,
        "numeric_call_site_id": 2,
        "call_site_id": unrepresented_site_id,
        "caller": caller_id,
        "span": {**SPAN, "line": 2, "end_line": 2},
        "classification": "proven-single-internal",
        "binding_mode": "bound-method",
        "resolution_kind": "exact-internal-method",
        "proven": True,
        "targets": [decoy_id],
        "resolution_evidence": "synthetic-exact",
        "reason": "no reachable CFG python-call has this full span",
    }
    later_unrepresented_site = {
        **copy.deepcopy(unrepresented_site),
        "source_order_index": 2,
        "numeric_call_site_id": 3,
        "call_site_id": later_unrepresented_site_id,
        "span": {**SPAN, "line": 3, "end_line": 3},
    }
    lowering: dict[str, object] = {
        "format": ACTIVE_CALL_SITE_LOWERING_FORMAT,
        "status": ACTIVE_CALL_SITE_LOWERING_STATUS,
        "live": False,
        "active_call_graph_semantic_sha256": graph["semantic_sha256"],
        "mapping": {
            "reachable_graph_call_site_count": 3,
            "represented_graph_call_site_count": 1,
            "unrepresented_graph_call_site_count": 2,
            "cfg_python_call_occurrence_count": 2,
        },
        "sites_in_source_order": [represented_site],
        "cfg_occurrences_in_cfg_order": occurrences,
        "unrepresented_graph_sites_in_source_order": [
            unrepresented_site, later_unrepresented_site],
        "target_signatures": {
            target_id: signature,
            decoy_id: copy.deepcopy(signature),
        },
    }
    _resign(lowering)

    descriptors: list[dict[str, object]] = []
    for occurrence, suffix, require_index, source_index, receiver_index in zip(
            occurrences, ("a", "b"), (2, 8), (1, 7), (0, 6)):
        receiver = f"%receiver_{suffix}"
        require = caller_instructions[require_index]
        source = caller_instructions[source_index]
        receiver_definition = caller_instructions[receiver_index]
        provenance = {
            "status": "exact",
            "callable_value": f"%callable_{suffix}",
            "require_callable": _instruction_proof(require),
            "callable_source_value": f"%source_{suffix}",
            "callable_source": _instruction_proof(source),
            "source_operation": "load-attribute",
            "source_kind": "attribute",
            "receiver_value": receiver,
            "attribute_name": "difference",
            "receiver_provenance": {
                "value": receiver,
                "kind": "ssa-definition",
                "definition": _instruction_proof(receiver_definition),
                "inputs": [],
            },
            "receiver_status": "exact",
        }
        descriptors.append({
            "numeric_abi_descriptor_id": occurrence["cfg_occurrence_index"],
            "numeric_call_site_id": 1,
            "cfg_occurrence_index": occurrence["cfg_occurrence_index"],
            "call_site_id": site_id,
            "caller": caller_id,
            "caller_numeric_function_id": 0,
            "span": dict(SPAN),
            "classification": "proven-single-internal",
            "proven": True,
            "resolution_kind": "exact-internal-method",
            "resolution_evidence": "synthetic-exact",
            "binding_mode": "bound-method",
            "callable_ssa_provenance": provenance,
            "receiver_value": receiver,
            "argument_evaluation_order": [
                {"evaluation_index": 0, "kind": "keyword",
                 "keyword": "right", "source_value": f"%right_{suffix}"},
                {"evaluation_index": 1, "kind": "keyword",
                 "keyword": "left", "source_value": f"%left_{suffix}"},
            ],
            "target_descriptors": [{
                "callable_id": target_id,
                "numeric_function_id": 1,
                "current_pzvt_function_id": 1,
                "proven_reachable": True,
                "binding_mode": "bound-method",
                "parameter_destination_map": [
                    {"evaluation_index": -1,
                     "destination_parameter": "self",
                     "destination_kind": "positional-or-keyword",
                     "source_kind": "receiver", "source_value": receiver},
                    {"evaluation_index": 0,
                     "destination_parameter": "right",
                     "destination_kind": "positional-or-keyword",
                     "keyword": "right", "source_kind": "argument",
                     "source_value": f"%right_{suffix}"},
                    {"evaluation_index": 1,
                     "destination_parameter": "left",
                     "destination_kind": "positional-or-keyword",
                     "keyword": "left", "source_kind": "argument",
                     "source_value": f"%left_{suffix}"},
                ],
                "explicit_argument_evaluation_order": [
                    f"%right_{suffix}", f"%left_{suffix}"],
                "lexical_owner": None,
                "blocker_codes": [],
            }],
            "target_numeric_function_ids": [1],
            "finite_dispatch_table": None,
            "constructor_sequence": None,
            "blocker_codes": [],
        })
    call_abi: dict[str, object] = {
        "format": WHOLE_PROGRAM_VM_CALL_ABI_FORMAT,
        "status": WHOLE_PROGRAM_VM_CALL_ABI_STATUS,
        "live": False,
        "active_call_graph_semantic_sha256": graph["semantic_sha256"],
        "call_site_lowering_semantic_sha256": lowering["semantic_sha256"],
        "function_id_contract": {
            "width_bits": 16,
            "first_id": 0,
            "proven_reachable_prefix_matches_current_pzvt_order": True,
            "candidate_only_functions_are_not_current_pzvt_functions": True,
            "function_count": 3,
        },
        "function_id_table": [
            {"numeric_function_id": 0, "callable_id": caller_id,
             "proven_reachable": True, "current_pzvt_function_id": 0},
            {"numeric_function_id": 1, "callable_id": target_id,
             "proven_reachable": True, "current_pzvt_function_id": 1},
            {"numeric_function_id": 2, "callable_id": decoy_id,
             "proven_reachable": True, "current_pzvt_function_id": 2},
        ],
        "call_site_lowering_prerequisites": {
            "unrepresented_graph_call_site_count": 2,
            "unrepresented_numeric_call_site_ids_in_source_order": [2, 3],
            "unrepresented_call_site_ids_in_source_order": [
                unrepresented_site_id, later_unrepresented_site_id],
            "unrepresented_classification_counts": {
                "proven-single-internal": 2},
            "unrepresented_graph_sites_in_source_order": [
                copy.deepcopy(unrepresented_site),
                copy.deepcopy(later_unrepresented_site)],
        },
        "census": {
            "represented_call_site_count": 1,
            "unrepresented_graph_call_site_count": 2,
            "call_occurrence_descriptor_count": 2,
            "duplicate_occurrence_descriptor_count": 1,
            "classification_counts": {"proven-single-internal": 2},
            "unrepresented_graph_call_site_classification_counts": {
                "proven-single-internal": 2},
            "binding_mode_counts": {"bound-method": 2},
            "blocker_descriptor_counts": {},
            "prerequisite_blocker_counts": {"PZCABI215": 2},
            "exact_callable_ssa_provenance_count": 2,
            "ambiguous_callable_ssa_provenance_count": 0,
        },
        "site_abi_descriptors_in_source_order": [{
            "numeric_call_site_id": 1,
            "call_site_id": site_id,
            "source_order_index": 0,
            "classification": "proven-single-internal",
            "proven": True,
            "target_numeric_function_ids": [1],
            "numeric_abi_descriptor_ids": [0, 1],
        }],
        "occurrence_abi_descriptors_in_cfg_order": descriptors,
        "live_blockers": [{
            "code": "PZCABI213", "count": 1,
            "detail": "the current VM/backend does not consume this ABI inventory",
        }, {
            "code": "PZCABI215", "count": 2,
            "detail": (
                "call-site lowering has reachable graph sites without "
                "CFG occurrences"),
        }],
        "proof": {
            "active_call_graph_and_lowering_validated_in_memory": True,
            "one_numeric_descriptor_per_represented_cfg_occurrence": True,
            "callable_ssa_chain_is_traced_without_receiver_invention": True,
            "finite_dispatch_tables_remain_non_proven": True,
            "constructor_sequence_is_allocate_bind_init_return": True,
            "argument_evaluation_order_is_not_reordered": True,
            "parameter_destination_map_is_per_occurrence_and_target": True,
            "nested_lexical_owner_is_explicit": True,
            "unrepresented_graph_sites_are_explicit_lowering_prerequisites":
                True,
            "backend_must_address_numeric_abi_descriptor_id_and_cfg_occurrence":
                True,
            "numeric_call_site_id_alone_is_not_backend_dispatch_identity": True,
            "current_vm_backend_consumes_call_abi": False,
        },
    }
    _resign(call_abi)
    return graph, lowering, call_abi


def defaulted_abi_bound_keyword_graph() -> tuple[
        dict[str, object], dict[str, object], dict[str, object]]:
    """Return the ABI fixture with ``right`` defaulted but supplied at calls."""
    graph, lowering, call_abi = abi_bound_keyword_graph()
    default_sha256 = semantic(["constant-default", 99])
    for callable_row in graph["callable_inventory"]["callables"][1:]:
        target_cfg = callable_row["cfg"]
        target_cfg["signature"]["parameters"][2]["default"] = {
            "kind": "constant", "value": 99}
        _resign(target_cfg)
    _resign(graph)
    for signature in lowering["target_signatures"].values():
        signature["parameters"][2]["has_default"] = True
        signature["parameters"][2]["default_ast_sha256"] = default_sha256
    lowering["active_call_graph_semantic_sha256"] = graph["semantic_sha256"]
    _resign(lowering)
    call_abi["active_call_graph_semantic_sha256"] = graph["semantic_sha256"]
    call_abi["call_site_lowering_semantic_sha256"] = lowering[
        "semantic_sha256"]
    _resign(call_abi)
    return graph, lowering, call_abi


def static_common_dispatch_abi_graph() -> tuple[
        dict[str, object], dict[str, object], dict[str, object]]:
    """Exact ``obj.static_method`` calls keep lookup but bind no receiver."""
    graph, lowering, call_abi = abi_bound_keyword_graph()
    target_id = "m::Worker.difference@21"

    target = graph["callable_inventory"]["callables"][1]["cfg"]
    target["signature"]["decorators"] = ["staticmethod"]
    target["signature"]["parameters"] = target["signature"]["parameters"][1:]
    _resign(target)
    graph["call_graph"]["call_sites"][0]["resolution"]["kind"] = (
        "exact-common-dispatch")
    _resign(graph)

    signature = lowering["target_signatures"][target_id]
    signature["parameters"] = signature["parameters"][1:]
    signature["is_staticmethod"] = True
    lowering["sites_in_source_order"][0]["binding_mode"] = "common-dispatch"
    lowering["sites_in_source_order"][0]["resolution_kind"] = (
        "exact-common-dispatch")
    lowering["active_call_graph_semantic_sha256"] = graph["semantic_sha256"]
    _resign(lowering)

    for descriptor in call_abi["occurrence_abi_descriptors_in_cfg_order"]:
        descriptor["resolution_kind"] = "exact-common-dispatch"
        descriptor["binding_mode"] = "common-dispatch"
        target_descriptor = descriptor["target_descriptors"][0]
        target_descriptor["binding_mode"] = "common-dispatch"
        target_descriptor["parameter_destination_map"] = (
            target_descriptor["parameter_destination_map"][1:])
    call_abi["census"]["binding_mode_counts"] = {"common-dispatch": 2}
    call_abi["active_call_graph_semantic_sha256"] = graph["semantic_sha256"]
    call_abi["call_site_lowering_semantic_sha256"] = lowering[
        "semantic_sha256"]
    _resign(call_abi)
    return graph, lowering, call_abi


def finite_dispatch_abi_graph() -> tuple[
        dict[str, object], dict[str, object], dict[str, object]]:
    """Two occurrences selecting different members of one finite table."""
    graph, lowering, call_abi = abi_bound_keyword_graph()
    target_id = "m::Worker.difference@21"
    decoy_id = "m::Worker.decoy_difference@22"
    graph_site = graph["call_graph"]["call_sites"][0]
    graph_site["resolution"] = {
        "kind": "finite-dynamic-dispatch", "proven": False,
        "targets": [target_id, decoy_id],
    }
    graph["call_graph"]["exact_internal_edge_count"] = 2
    _resign(graph)

    represented = lowering["sites_in_source_order"][0]
    represented.update({
        "classification": "finite-non-proven",
        "resolution_kind": "finite-dynamic-dispatch",
        "proven": False,
        "targets": [target_id, decoy_id],
        "resolution_evidence": "synthetic-finite",
    })
    lowering["active_call_graph_semantic_sha256"] = graph["semantic_sha256"]
    _resign(lowering)

    for descriptor in call_abi["occurrence_abi_descriptors_in_cfg_order"]:
        first = descriptor["target_descriptors"][0]
        second = copy.deepcopy(first)
        second.update({
            "callable_id": decoy_id,
            "numeric_function_id": 2,
            "current_pzvt_function_id": 2,
        })
        descriptor.update({
            "classification": "finite-non-proven",
            "proven": False,
            "resolution_kind": "finite-dynamic-dispatch",
            "resolution_evidence": "synthetic-finite",
            "target_descriptors": [first, second],
            "target_numeric_function_ids": [1, 2],
            "finite_dispatch_table": {
                "proven": False,
                "runtime_identity_guard_required": True,
                "candidate_set_is_not_a_reachability_edge": True,
                "entries": [{
                    "callable_id": row["callable_id"],
                    "numeric_function_id": row["numeric_function_id"],
                    "current_pzvt_function_id": row[
                        "current_pzvt_function_id"],
                } for row in (first, second)],
            },
            "blocker_codes": ["PZCABI204"],
        })
    site_descriptor = call_abi["site_abi_descriptors_in_source_order"][0]
    site_descriptor.update({
        "classification": "finite-non-proven", "proven": False,
        "target_numeric_function_ids": [1, 2],
    })
    call_abi["census"]["classification_counts"] = {
        "finite-non-proven": 2}
    call_abi["census"]["blocker_descriptor_counts"] = {"PZCABI204": 2}
    call_abi["live_blockers"].append({
        "code": "PZCABI204", "count": 2,
        "detail": "finite dispatch remains runtime guarded and non-proven",
    })
    call_abi["active_call_graph_semantic_sha256"] = graph["semantic_sha256"]
    call_abi["call_site_lowering_semantic_sha256"] = lowering[
        "semantic_sha256"]
    _resign(call_abi)
    return graph, lowering, call_abi


def finite_bound_callback_abi_graph() -> tuple[
        dict[str, object], dict[str, object], dict[str, object]]:
    """Finite methods passed through local callback parameters.

    The caller has no SSA receiver: Python keeps it inside each bound method
    object.  The guarded target identity and receiver extraction are therefore
    both runtime operations, while explicit argument binding stays static.
    """
    graph, lowering, call_abi = finite_dispatch_abi_graph()
    caller = graph["callable_inventory"]["callables"][0]["cfg"]
    instructions = caller["blocks"][0]["instructions"]
    for source_index, loaded_name in ((1, "callback_a"), (7, "callback_b")):
        instructions[source_index]["op"] = "load-name"
        instructions[source_index]["arguments"] = [loaded_name]
    _resign(caller)
    _resign(graph)

    lowering["sites_in_source_order"][0]["binding_mode"] = "free"
    lowering["active_call_graph_semantic_sha256"] = graph["semantic_sha256"]
    _resign(lowering)

    for descriptor, source_index, require_index, loaded_name in zip(
            call_abi["occurrence_abi_descriptors_in_cfg_order"],
            (1, 7), (2, 8), ("callback_a", "callback_b")):
        source = instructions[source_index]
        require = instructions[require_index]
        descriptor["binding_mode"] = "free"
        descriptor["receiver_value"] = None
        descriptor["callable_ssa_provenance"] = {
            "status": "exact",
            "callable_value": require["destination"],
            "require_callable": _instruction_proof(require),
            "callable_source_value": source["destination"],
            "callable_source": _instruction_proof(source),
            "source_operation": "load-name",
            "source_kind": "name",
            "loaded_name": loaded_name,
        }
        for target in descriptor["target_descriptors"]:
            target["binding_mode"] = "free"
            target["parameter_destination_map"] = [{
                "evaluation_index": 0,
                "destination_parameter": "right",
                "destination_kind": "positional-or-keyword",
                "keyword": "right",
                "source_kind": "argument",
                "source_value": descriptor["argument_evaluation_order"][0][
                    "source_value"],
            }, {
                "evaluation_index": 1,
                "destination_parameter": "left",
                "destination_kind": "positional-or-keyword",
                "keyword": "left",
                "source_kind": "argument",
                "source_value": descriptor["argument_evaluation_order"][1][
                    "source_value"],
            }, {
                "evaluation_index": None,
                "destination_parameter": "self",
                "destination_kind": "positional-or-keyword",
                "source_kind": "missing-required",
                "source_value": None,
            }]
            target["blocker_codes"] = ["PZCABI208"]
        descriptor["blocker_codes"] = ["PZCABI204", "PZCABI208"]
    call_abi["census"]["binding_mode_counts"] = {"free": 2}
    call_abi["census"]["blocker_descriptor_counts"] = {
        "PZCABI204": 2, "PZCABI208": 2}
    call_abi["live_blockers"].append({
        "code": "PZCABI208", "count": 2,
        "detail": "parameter binding can raise or is not statically complete",
    })
    call_abi["active_call_graph_semantic_sha256"] = graph["semantic_sha256"]
    call_abi["call_site_lowering_semantic_sha256"] = lowering[
        "semantic_sha256"]
    _resign(call_abi)
    return graph, lowering, call_abi


def guarded_only_finite_dispatch_abi_graph() -> tuple[
        dict[str, object], dict[str, object], dict[str, object]]:
    """Finite bound methods emitted outside the proven reachable prefix."""
    graph, lowering, call_abi = finite_dispatch_abi_graph()
    caller_id = "m::abi_caller@20"
    target_ids = [
        "m::Worker.difference@21",
        "m::Worker.decoy_difference@22",
    ]
    graph["call_graph"]["proven_reachable_callable_ids"] = [caller_id]

    # A call inside a guard-only body has no proven-reachable ABI occurrence;
    # it must remain a distinct adapter, never become an inferred edge.
    target_cfg = graph["callable_inventory"]["callables"][1]["cfg"]
    target_cfg["blocks"][0]["instructions"].extend([
        instruction(3, "constant", ["guard-body-callback"], "%guard_ref"),
        instruction(
            4, "python-call", ["%guard_ref"], "%guard_ignored",
            argument_count=0, argument_layout=[], keywords=False),
    ])
    _resign(target_cfg)
    _resign(graph)
    lowering["active_call_graph_semantic_sha256"] = graph["semantic_sha256"]
    _resign(lowering)

    for row in call_abi["function_id_table"][1:]:
        row["proven_reachable"] = False
        row["current_pzvt_function_id"] = None
    for descriptor in call_abi["occurrence_abi_descriptors_in_cfg_order"]:
        descriptor["blocker_codes"] = ["PZCABI204", "PZCABI212"]
        for target in descriptor["target_descriptors"]:
            self_id = target["callable_id"]
            assert self_id in target_ids
            target["proven_reachable"] = False
            target["current_pzvt_function_id"] = None
        for entry in descriptor["finite_dispatch_table"]["entries"]:
            entry["current_pzvt_function_id"] = None
    call_abi["census"]["blocker_descriptor_counts"] = {
        "PZCABI204": 2, "PZCABI212": 2}
    call_abi["live_blockers"].append({
        "code": "PZCABI212", "count": 2,
        "detail": "finite candidates are outside proven reachability",
    })
    call_abi["active_call_graph_semantic_sha256"] = graph["semantic_sha256"]
    call_abi["call_site_lowering_semantic_sha256"] = lowering[
        "semantic_sha256"]
    _resign(call_abi)
    return graph, lowering, call_abi


def guarded_lexical_dispatch_abi_graph() -> tuple[
        dict[str, object], dict[str, object], dict[str, object]]:
    """Guard-only nested functions with one exact active lexical owner."""
    graph, lowering, call_abi = guarded_only_finite_dispatch_abi_graph()
    caller_id = "m::abi_caller@20"
    caller = graph["callable_inventory"]["callables"][0]["cfg"]
    caller["signature"]["parameters"] = [{
        "name": "captured", "kind": "positional-or-keyword",
        "default": None,
    }]
    instructions = caller["blocks"][0]["instructions"]
    for source_index, loaded_name in ((1, "callback_a"), (7, "callback_b")):
        instructions[source_index]["op"] = "load-name"
        instructions[source_index]["arguments"] = [loaded_name]
    _resign(caller)

    for target_row in graph["callable_inventory"]["callables"][1:]:
        target_row["lexical_parent_id"] = caller_id
        target_cfg = target_row["cfg"]
        target_cfg["class"] = None
        target_cfg["signature"]["parameters"] = target_cfg[
            "signature"]["parameters"][1:]
        target_cfg["blocks"][0]["instructions"].append(
            instruction(5, "load-name", ["captured"], "%captured"))
        _resign(target_cfg)
    _resign(graph)

    lowering["sites_in_source_order"][0]["binding_mode"] = "free"
    for signature in lowering["target_signatures"].values():
        signature["parameters"] = signature["parameters"][1:]
    lowering["active_call_graph_semantic_sha256"] = graph["semantic_sha256"]
    _resign(lowering)

    for descriptor, source_index, require_index, loaded_name in zip(
            call_abi["occurrence_abi_descriptors_in_cfg_order"],
            (1, 7), (2, 8), ("callback_a", "callback_b")):
        source = instructions[source_index]
        require = instructions[require_index]
        descriptor["binding_mode"] = "free"
        descriptor["receiver_value"] = None
        descriptor["callable_ssa_provenance"] = {
            "status": "exact",
            "callable_value": require["destination"],
            "require_callable": _instruction_proof(require),
            "callable_source_value": source["destination"],
            "callable_source": _instruction_proof(source),
            "source_operation": "load-name",
            "source_kind": "name",
            "loaded_name": loaded_name,
        }
        for target in descriptor["target_descriptors"]:
            target["binding_mode"] = "free"
            target["parameter_destination_map"] = [
                row for row in target["parameter_destination_map"]
                if row["destination_parameter"] != "self"]
            target["lexical_owner"] = {
                "callable_id": caller_id,
                "numeric_function_id": 0,
                "current_pzvt_function_id": 0,
            }
    call_abi["census"]["binding_mode_counts"] = {"free": 2}
    call_abi["active_call_graph_semantic_sha256"] = graph["semantic_sha256"]
    call_abi["call_site_lowering_semantic_sha256"] = lowering[
        "semantic_sha256"]
    _resign(call_abi)
    return graph, lowering, call_abi


def constructor_abi_graph() -> tuple[
        dict[str, object], dict[str, object], dict[str, object]]:
    """Two exact constructors with keyword evaluation/parameter reordering."""
    graph, lowering, call_abi = abi_bound_keyword_graph()
    old_target = "m::Worker.difference@21"
    target_id = "m::Widget.__init__@21"
    class_id = "m::Widget@21"
    caller_cfg = graph["callable_inventory"]["callables"][0]["cfg"]
    instructions = caller_cfg["blocks"][0]["instructions"]
    for source_index in (1, 7):
        instructions[source_index]["op"] = "load-name"
        instructions[source_index]["arguments"] = ["Widget"]
    caller_cfg["blocks"][0]["instructions"] = instructions[:12]
    caller_cfg["blocks"][0]["terminator"] = terminator(
        "return", ["%result_b"], [])
    _resign(caller_cfg)

    target_row = graph["callable_inventory"]["callables"][1]
    target_row["callable_id"] = target_id
    target_row["qualname"] = "Widget.__init__"
    target_cfg = target_row["cfg"]
    target_cfg["function_id"] = "__init__@21"
    target_cfg["function"] = "__init__"
    target_cfg["class"] = "Widget"
    target_cfg["signature"]["returns"] = "None"
    target_cfg["blocks"] = [block("entry", [
        instruction(0, "load-name", ["self"], "%loaded_self"),
        instruction(1, "load-name", ["left"], "%loaded_left"),
        instruction(2, "load-name", ["right"], "%loaded_right"),
        instruction(3, "record-init", [
            "%loaded_self", "%loaded_left", "%loaded_right"], "%ignored"),
    ], terminator("return", [], []))]
    _resign(target_cfg)

    graph["call_graph"]["proven_reachable_callable_ids"][1] = target_id
    for site in graph["call_graph"]["call_sites"]:
        if site["resolution"]["targets"] == [old_target]:
            site["resolution"] = {
                "kind": "exact-internal-constructor", "proven": True,
                "constructed_class": class_id, "targets": [target_id],
            }
    _resign(graph)

    represented = lowering["sites_in_source_order"][0]
    represented.update({
        "binding_mode": "constructor",
        "resolution_kind": "exact-internal-constructor",
        "targets": [target_id],
    })
    lowering["target_signatures"][target_id] = lowering[
        "target_signatures"].pop(old_target)
    lowering["active_call_graph_semantic_sha256"] = graph["semantic_sha256"]
    _resign(lowering)

    call_abi["active_call_graph_semantic_sha256"] = graph["semantic_sha256"]
    call_abi["call_site_lowering_semantic_sha256"] = lowering[
        "semantic_sha256"]
    call_abi["function_id_table"][1]["callable_id"] = target_id
    call_abi["census"]["binding_mode_counts"] = {"constructor": 2}
    call_abi["site_abi_descriptors_in_source_order"][0][
        "target_numeric_function_ids"] = [1]
    for descriptor, source_index in zip(
            call_abi["occurrence_abi_descriptors_in_cfg_order"], (1, 7)):
        source = instructions[source_index]
        provenance = descriptor["callable_ssa_provenance"]
        provenance.update({
            "callable_source": _instruction_proof(source),
            "source_operation": "load-name", "source_kind": "name",
            "loaded_name": "Widget",
        })
        for key in ("receiver_value", "attribute_name", "receiver_provenance",
                    "receiver_status"):
            provenance.pop(key, None)
        descriptor.update({
            "resolution_kind": "exact-internal-constructor",
            "binding_mode": "constructor", "receiver_value": None,
            "constructor_sequence": [
                {"step": 0, "operation": "allocate-instance",
                 "constructed_class": class_id,
                 "result": "$allocated-object"},
                {"step": 1, "operation": "bind-init-self",
                 "value": "$allocated-object"},
                {"step": 2, "operation": "invoke-__init__",
                 "required_return": None,
                 "target_numeric_function_ids": [1]},
                {"step": 3, "operation": "return-allocated-instance",
                 "value": "$allocated-object"},
            ],
        })
        target = descriptor["target_descriptors"][0]
        target.update({"callable_id": target_id, "binding_mode": "constructor"})
        target["parameter_destination_map"][0].update({
            "source_kind": "allocated-object",
            "source_value": "$allocated-object",
        })
    _resign(call_abi)
    return graph, lowering, call_abi


def generated_dataclass_compact_fixture(
        document: dict[str, object]) -> tuple[bytes, dict[str, object], int]:
    """Build one compact generated-dataclass init with a consumed super chain."""
    document = copy.deepcopy(document)
    schema_payload = {
        "format": "pyz80.generated-dataclass-init.v1",
        "class_id": "m::Base@1",
        "parameters": [
            {"name": "self", "kind": "positional-or-keyword"},
            {"name": "required", "kind": "positional-or-keyword"},
            {"name": "optional", "kind": "positional-or-keyword",
             "has_default": True, "default_value_proven": True,
             "default_value": 29},
        ],
        "fields": [{"name": "required"}, {"name": "optional"}],
        "post_init_target": None,
    }
    schema = {**schema_payload, "semantic_sha256": semantic(schema_payload)}
    elision = {"kind": "generated-dataclass-super-preparation",
               "consumer_cfg_occurrence_index": 1}
    rows = [
        instruction(0, "constant", [{"record": 1}], "%self"),
        {**instruction(1, "load-name", ["super"], "%super_name"),
         "_target_elided": copy.deepcopy(elision)},
        {**instruction(2, "require-callable", ["%super_name"],
                       "%super_callable"),
         "_target_elided": copy.deepcopy(elision)},
        {**instruction(3, "python-call", ["%super_callable"],
                       "%super_proxy", argument_count=0,
                       argument_layout=[], evaluation_order=["callable"]),
         "_target_elided": copy.deepcopy(elision)},
        {**instruction(4, "load-attribute", ["%super_proxy", "__init__"],
                       "%init_source"),
         "_target_elided": copy.deepcopy(elision)},
        {**instruction(5, "require-callable", ["%init_source"],
                       "%init_callable"),
         "_target_elided": copy.deepcopy(elision)},
        instruction(6, "constant", [17], "%required"),
        instruction(7, "python-call", ["%init_callable", "%required"],
                    "%init_result", argument_count=1,
                    argument_layout=[["positional", None]],
                    evaluation_order=["callable", "argument:0"]),
    ]
    rows[-1]["_target_direct_function"] = None
    rows[-1]["_target_call_arguments"] = ["%self", "%required", 29]
    rows[-1]["_target_call_abi"] = {
        "target": None,
        "binding_mode": "generated-dataclass-init",
        "generated_dataclass_init": schema,
        "call_argument_operands": ["%self", "%required", 29],
    }
    main_cfg = document["functions"][0]["row"]["cfg"]
    main_cfg["blocks"] = [block(
        "entry", rows, terminator("return", ["%self"], []))]
    main_cfg["entry"] = "entry"
    main_cfg["expression_programs"] = []
    image, decoded, adapters, _result = build_compact_target_vm(document)
    adapter = next(row["adapter_id"] for row in adapters
                   if row["kind"] == "generated-dataclass-init")
    return image, decoded, adapter


class WholeProgramVMBackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.graph = synthetic_graph()
        cls.artifact = build_whole_program_vm(cls.graph)

    def test_deterministic_lossless_round_trip(self) -> None:
        second = build_whole_program_vm(copy.deepcopy(self.graph))
        self.assertEqual(second.bytecode, self.artifact.bytecode)
        self.assertEqual(second.semantic_sha256, self.artifact.semantic_sha256)
        self.assertEqual(decode_whole_program_vm(self.artifact.proof_bytecode),
                         self.artifact.document)

    def test_exact_object_store_reference_expands_to_effect_ssa(self) -> None:
        store_expression = expression("store-site-0007-rhs", 9)
        fragment_semantic = semantic(["store", 7])
        units = [{
            "kind": 1, "owner": 0, "name": "m::C.update@1",
            "result": None, "entry": "entry", "meta": {},
            "blocks": [block("entry", [{
                "sequence": 4,
                "op": "execute-object-store-fragment",
                "arguments": [7, fragment_semantic],
                "span": dict(SPAN),
            }], terminator("return", [], []))],
        }]
        report = {
            "semantic_sha256": "1" * 64,
            "fragments": [{
                "site_id": 7,
                "semantic_sha256": fragment_semantic,
                "expression": store_expression,
                "instructions": [
                    instruction(0, "execute-expression-cfg",
                                ["store-site-0007-rhs"], "%value"),
                    instruction(1, "eval-receiver", ["self"], "%receiver"),
                    instruction(2, "store-attribute",
                                ["%receiver", "x", "%value"]),
                    instruction(3, "draw-sync-if-bound",
                                ["%receiver", 11, "%value", 7]),
                ],
            }],
        }
        expanded, proof = _expand_object_store_units(units, report)
        self.assertEqual(proof["expanded_fragment_ids"], [7])
        self.assertEqual(len(expanded), 2)
        operations = [row["op"] for row in expanded[0]["blocks"][0]
                      ["instructions"]]
        self.assertEqual(operations, [
            "execute-expression-cfg", "load-name", "store-attribute",
            "draw-sync-if-bound"])
        self.assertEqual(
            expanded[0]["blocks"][0]["instructions"][2]["arguments"],
            ["%pzstore_0007_receiver", "x", "%pzstore_0007_value"])
        self.assertEqual(expanded[1]["name"],
                         store_expression["program_id"])

    def test_in_memory_analyzer_tuples_are_json_normalized(self) -> None:
        graph = copy.deepcopy(self.graph)
        graph["call_graph"]["proven_reachable_callable_ids"] = tuple(
            graph["call_graph"]["proven_reachable_callable_ids"])
        cfg = graph["callable_inventory"]["callables"][0]["cfg"]
        # json.dumps signs tuples as arrays, so this remains the same valid
        # analyzer report while exercising the in-memory representation that
        # previously failed PZWV048 after decoding the proof image.
        cfg["signature"]["decorators"] = tuple(
            cfg["signature"]["decorators"])
        cfg["mutation_site_ids"] = tuple(cfg["mutation_site_ids"])
        artifact = build_whole_program_vm(graph)
        decoded = decode_whole_program_vm(artifact.proof_bytecode)
        self.assertEqual(decoded, artifact.document)
        normalized_cfg = artifact.document["functions"][0]["row"]["cfg"]
        self.assertIsInstance(normalized_cfg["signature"]["decorators"], list)
        self.assertIsInstance(normalized_cfg["mutation_site_ids"], list)

    def test_compact_entry_arguments_match_lossless_oracle(self) -> None:
        function = "m::entry_argument@13"
        self.assertEqual(WholeProgramVMOracle(
            self.artifact).run(function, [123]), 123)
        compact = CompactTargetVMOracle(self.artifact)
        self.assertEqual(compact.run(function, [123]), 123)
        with self.assertRaisesRegex(WholeProgramVMError, "PZWV262"):
            compact.run(function)
        self.assertEqual(decode_compact_target_vm(self.artifact.target_bytecode),
                         self.artifact.compact_document)
        self.assertLess(len(self.artifact.target_bytecode),
                        len(self.artifact.proof_bytecode) // 4)
        self.assertFalse(self.artifact.live)
        self.assertEqual(len(self.artifact.live_blockers), 5)

    def test_compact_generated_dataclass_init_and_elided_super_chain(self) -> None:
        image, decoded, adapter_id = generated_dataclass_compact_fixture(
            self.artifact.document)
        opcodes = [item["opcode"] for item in
                   decoded["units"][decoded["functions"][0]]["blocks"][0][
                       "instructions"]]
        self.assertEqual(opcodes.count(8), 5)
        self.assertEqual(opcodes.count(9), 1)
        calls: list[list[object]] = []

        def adapter(current: int, arguments: list[object],
                    _descriptor: dict[str, object]) -> object:
            self.assertEqual(current, adapter_id)
            calls.append(arguments)
            instance = arguments[0]
            assert isinstance(instance, dict)
            instance["required"] = arguments[1]
            instance["optional"] = arguments[2]
            return None

        result = CompactTargetVMOracle(image, adapter=adapter).run(0)
        self.assertEqual(result, {
            "record": 1, "required": 17, "optional": 29})
        self.assertEqual(len(calls), 1)

    def test_active_graph_semantic_tamper_is_rejected(self) -> None:
        graph = copy.deepcopy(self.graph)
        graph["semantic_sha256"] = "0" * 64
        with self.assertRaisesRegex(
                WholeProgramVMError, "active call graph semantic hash mismatch"):
            build_whole_program_vm(graph)

    def test_public_status_binds_runtime_sources_without_writes(self) -> None:
        before = {path: hashlib.sha256(path.read_bytes()).hexdigest()
                  for path in (RUNTIME_C, RUNTIME_H)}
        first = whole_program_vm_status(self.artifact, project_root=ROOT)
        second = whole_program_vm_status(self.artifact, project_root=ROOT)
        self.assertEqual(first, second)
        self.assertEqual(render_whole_program_vm_status(
            self.artifact, project_root=ROOT),
            render_whole_program_vm_status(self.artifact, project_root=ROOT))
        self.assertEqual(first["target_bytecode"]["sha256"],
                         self.artifact.bytecode_sha256)
        self.assertFalse(first["execution_contract"][
            "active_suspend_yield_protocol_executable"])
        self.assertEqual(before, {
            path: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (RUNTIME_C, RUNTIME_H)})

    def test_active_generator_protocol_is_lossless_but_fail_closed(self) -> None:
        decoded = decode_whole_program_vm(self.artifact.proof_bytecode)
        cfg = next(item["row"]["cfg"] for item in decoded["functions"]
                   if item["callable_id"] == "m::active_generator@6")
        self.assertEqual(
            [item["op"] for item in cfg["blocks"][0]["instructions"]],
            ["generator-save-frame", "generator-restore-frame",
             "generator-resume-value"])
        self.assertEqual(cfg["blocks"][0]["terminator"]["op"],
                         "suspend-yield")
        self.assertEqual(cfg["blocks"][1]["terminator"]["op"],
                         "suspend-yield-from")
        with self.assertRaisesRegex(WholeProgramVMError, "PZWV104"):
            WholeProgramVMOracle(self.artifact).run("m::active_generator@6")
        with self.assertRaisesRegex(WholeProgramVMError, "PZWV254"):
            CompactTargetVMOracle(self.artifact).run("m::active_generator@6")

    def test_tamper_and_malformed_image_fail_closed(self) -> None:
        damaged = bytearray(self.artifact.bytecode)
        damaged[-1] ^= 0x80
        with self.assertRaisesRegex(WholeProgramVMError, "PZWV222"):
            decode_compact_target_vm(damaged)
        with self.assertRaisesRegex(WholeProgramVMError, "PZWV020"):
            decode_whole_program_vm(b"PZVM")
        hash_tampered = bytearray(self.artifact.bytecode)
        hash_tampered[16] ^= 1
        replacement = dataclasses.replace(
            self.artifact, target_bytecode=bytes(hash_tampered),
            target_bytecode_sha256=hashlib.sha256(hash_tampered).hexdigest())
        with self.assertRaisesRegex(WholeProgramVMError, "PZWV246"):
            CompactTargetVMOracle(replacement)
        malformed = bytearray(self.artifact.bytecode)
        unit_data = int.from_bytes(malformed[72:76], "little")
        malformed[unit_data:unit_data + 5] = b"\x80" * 5
        malformed[12:16] = (zlib.crc32(malformed[80:]) & 0xFFFFFFFF).to_bytes(
            4, "little")
        with self.assertRaises(WholeProgramVMError):
            decode_compact_target_vm(malformed)

    def test_minimal_cfg_executes_store_load_binary_branch_call_return(self) -> None:
        oracle = WholeProgramVMOracle(self.artifact, max_call_depth=8)
        self.assertEqual(oracle.run("m::main@1"), 11)
        self.assertEqual(CompactTargetVMOracle(
            self.artifact, max_call_depth=8).run("m::main@1"), 11)

    def test_call_site_lowering_is_reachable_exact_and_main_cfg_aware(self) -> None:
        coverage = self.artifact.target_coverage
        self.assertEqual(coverage["active_exact_internal_call_site_count"], 1)
        self.assertEqual(coverage["active_internal_call_sites_lowered"], 1)
        self.assertEqual(coverage["active_internal_call_sites_unlowered"], 0)
        self.assertEqual(coverage["active_python_call_instruction_count"], 3)
        self.assertEqual(coverage["active_python_call_instructions_lowered"], 1)
        self.assertTrue(coverage["active_interprocedural_execution_closed"])
        self.assertEqual(CompactTargetVMOracle(self.artifact).run(
            "m::direct_python@10"), 5)
        call_adapters = [row for row in self.artifact.adapter_table
                         if row["op"] == "python-call"]
        self.assertEqual(len(call_adapters), 2)
        self.assertEqual(
            {row["call_site_id"] for row in call_adapters},
            {"unsafe-site-2", "unsafe-site-3"})
        self.assertEqual(len({row["adapter_id"] for row in call_adapters}), 2)

    def test_call_abi_lowers_exact_bound_receiver_and_keyword_order(self) -> None:
        graph, lowering, call_abi = abi_bound_keyword_graph()
        artifact = build_whole_program_vm(
            graph, active_call_site_lowering=lowering,
            whole_program_vm_call_abi=call_abi)
        second = build_whole_program_vm(
            copy.deepcopy(graph),
            active_call_site_lowering=copy.deepcopy(lowering),
            whole_program_vm_call_abi=copy.deepcopy(call_abi))
        self.assertEqual(artifact.proof_bytecode, second.proof_bytecode)
        self.assertEqual(artifact.target_bytecode, second.target_bytecode)
        self.assertEqual(
            artifact.document["active_call_site_lowering_semantic_sha256"],
            lowering["semantic_sha256"])
        self.assertEqual(
            artifact.document["whole_program_vm_call_abi_semantic_sha256"],
            call_abi["semantic_sha256"])
        coverage = artifact.target_coverage
        self.assertTrue(coverage["call_abi_input_enabled"])
        self.assertEqual(coverage["abi_exact_internal_occurrence_count"], 2)
        self.assertEqual(coverage["abi_eligible_call_instruction_count"], 2)
        self.assertEqual(coverage["abi_lowered_call_instruction_count"], 2)
        self.assertEqual(coverage["abi_unlowered_call_instruction_count"], 0)
        self.assertEqual(coverage["abi_lowered_call_site_count"], 1)
        self.assertEqual(coverage["abi_unlowered_call_site_count"], 0)
        self.assertEqual(coverage["legacy_direct_call_instruction_count"], 0)
        self.assertEqual(coverage["legacy_direct_call_site_count"], 0)
        self.assertFalse(any(row["op"] == "python-call"
                             for row in artifact.adapter_table))

        adapter_calls: list[tuple[str, list[object]]] = []

        def adapter(_adapter_id: int, args: list[object],
                    descriptor: dict[str, object]) -> object:
            op = str(descriptor["op"])
            adapter_calls.append((op, list(args)))
            if op == "load-attribute":
                return f"bound:{args[0]}:{args[1]}"
            if op == "require-callable":
                return args[0]
            self.fail(f"unexpected adapter operation {op}")

        # Target computes left-right.  The source evaluates right then left;
        # the ABI CALL must push receiver,left,right without re-evaluation.
        self.assertEqual(CompactTargetVMOracle(
            artifact, adapter=adapter).run("m::abi_caller@20"), 10)
        self.assertEqual([row[0] for row in adapter_calls], [
            "load-attribute", "require-callable",
            "load-attribute", "require-callable",
        ])
        self.assertEqual(adapter_calls[0][1], ["receiver-A", "difference"])
        self.assertEqual(adapter_calls[2][1], ["receiver-B", "difference"])

        _image, _decoded, _adapters, compact = build_compact_target_vm(
            artifact.document, active_call_site_lowering=lowering,
            whole_program_vm_call_abi=call_abi)
        rows = compact["manifest"]["call_site_lowering"]
        self.assertEqual([row["cfg_occurrence_index"] for row in rows], [0, 1])
        self.assertEqual([row["cfg_path"][-1] for row in rows], [5, 11])
        self.assertEqual([row["direct_call_plan"]["call_argument_operands"]
                          for row in rows], [
            ["%receiver_a", "%left_a", "%right_a"],
            ["%receiver_b", "%left_b", "%right_b"],
        ])
        self.assertEqual(len({row["semantic_sha256"] for row in rows}), 2)

    def test_call_abi_lowers_explicit_call_to_defaulted_target(self) -> None:
        graph, lowering, call_abi = defaulted_abi_bound_keyword_graph()
        artifact = build_whole_program_vm(
            graph, active_call_site_lowering=lowering,
            whole_program_vm_call_abi=call_abi)
        coverage = artifact.target_coverage
        self.assertEqual(coverage["abi_lowered_call_instruction_count"], 2)
        self.assertEqual(coverage["abi_unlowered_call_instruction_count"], 0)
        self.assertNotIn(
            "target-signature-has-default",
            coverage["abi_unlowered_reason_counts"])

        def adapter(_adapter_id: int, args: list[object],
                    descriptor: dict[str, object]) -> object:
            if descriptor["op"] == "load-attribute":
                return f"bound:{args[0]}:{args[1]}"
            if descriptor["op"] == "require-callable":
                return args[0]
            self.fail(f"unexpected adapter operation {descriptor['op']}")

        # The declared default is irrelevant because both call occurrences
        # explicitly populate every destination parameter.
        self.assertEqual(CompactTargetVMOracle(
            artifact, adapter=adapter).run("m::abi_caller@20"), 10)

    def test_call_abi_lowers_staticmethod_common_dispatch_without_receiver(
            self) -> None:
        graph, lowering, call_abi = static_common_dispatch_abi_graph()
        artifact = build_whole_program_vm(
            graph, active_call_site_lowering=lowering,
            whole_program_vm_call_abi=call_abi)
        coverage = artifact.target_coverage
        self.assertEqual(coverage["abi_lowered_call_instruction_count"], 2)
        self.assertEqual(coverage["abi_unlowered_call_instruction_count"], 0)
        _image, _decoded, _adapters, compact = build_compact_target_vm(
            artifact.document, active_call_site_lowering=lowering,
            whole_program_vm_call_abi=call_abi)
        rows = compact["manifest"]["call_site_lowering"]
        self.assertEqual([row["direct_call_plan"]["binding_mode"]
                          for row in rows], ["common-dispatch"] * 2)
        self.assertEqual([row["direct_call_plan"]["call_argument_operands"]
                          for row in rows], [
            ["%left_a", "%right_a"],
            ["%left_b", "%right_b"],
        ])

        def adapter(_adapter_id: int, args: list[object],
                    descriptor: dict[str, object]) -> object:
            if descriptor["op"] == "load-attribute":
                return f"static:{args[1]}"
            if descriptor["op"] == "require-callable":
                return args[0]
            self.fail(f"unexpected adapter operation {descriptor['op']}")

        self.assertEqual(CompactTargetVMOracle(
            artifact, adapter=adapter).run("m::abi_caller@20"), 10)

    def test_call_abi_guarded_finite_dispatch_selects_exact_candidate(
            self) -> None:
        graph, lowering, call_abi = finite_dispatch_abi_graph()
        artifact = build_whole_program_vm(
            graph, active_call_site_lowering=lowering,
            whole_program_vm_call_abi=call_abi)
        coverage = artifact.target_coverage
        self.assertEqual(coverage["abi_finite_dispatch_instruction_count"], 2)
        self.assertEqual(
            coverage["abi_finite_bound_dispatch_instruction_count"], 0)
        self.assertEqual(
            coverage["abi_finite_bound_dispatch_site_count"], 0)
        self.assertEqual(coverage["abi_finite_dispatch_site_count"], 1)
        self.assertEqual(coverage["abi_lowered_call_instruction_count"], 2)
        self.assertEqual(coverage["abi_unlowered_call_instruction_count"], 0)
        self.assertEqual(sum(
            item["opcode"] == 10
            for unit in artifact.compact_document["units"]
            for cfg_block in unit["blocks"]
            for item in cfg_block["instructions"]), 2)
        guards = [row for row in artifact.adapter_table
                  if row["op"] == "resolve-finite-callable-identity"]
        self.assertEqual(len(guards), 1)
        self.assertEqual(guards[0]["candidate_callable_ids"], [
            "m::Worker.difference@21",
            "m::Worker.decoy_difference@22",
        ])

        def adapter(_adapter_id: int, args: list[object],
                    descriptor: dict[str, object]) -> object:
            op = descriptor["op"]
            if op == "load-attribute":
                return f"bound:{args[0]}:{args[1]}"
            if op == "require-callable":
                return args[0]
            if op == "resolve-finite-callable-identity":
                return 0 if "receiver-A" in str(args[0]) else 1
            self.fail(f"unexpected adapter operation {op}")

        self.assertEqual(CompactTargetVMOracle(
            artifact, adapter=adapter).run("m::abi_caller@20"), 18)

        def invalid_guard(_adapter_id: int, args: list[object],
                          descriptor: dict[str, object]) -> object:
            if descriptor["op"] == "load-attribute":
                return f"bound:{args[0]}:{args[1]}"
            if descriptor["op"] == "require-callable":
                return args[0]
            return 2

        with self.assertRaisesRegex(WholeProgramVMError, "PZWV270"):
            CompactTargetVMOracle(
                artifact, adapter=invalid_guard).run("m::abi_caller@20")

        tampered = copy.deepcopy(call_abi)
        tampered["occurrence_abi_descriptors_in_cfg_order"][0][
            "finite_dispatch_table"]["entries"][0][
                "current_pzvt_function_id"] = 2
        _resign(tampered)
        with self.assertRaisesRegex(WholeProgramVMError, "PZWV268"):
            build_whole_program_vm(
                graph, active_call_site_lowering=lowering,
                whole_program_vm_call_abi=tampered)

    def test_call_abi_guarded_bound_callback_extracts_runtime_receiver(
            self) -> None:
        graph, lowering, call_abi = finite_bound_callback_abi_graph()
        artifact = build_whole_program_vm(
            graph, active_call_site_lowering=lowering,
            whole_program_vm_call_abi=call_abi)
        coverage = artifact.target_coverage
        self.assertEqual(coverage["abi_finite_dispatch_instruction_count"], 2)
        self.assertEqual(
            coverage["abi_finite_bound_dispatch_instruction_count"], 2)
        self.assertEqual(
            coverage["abi_finite_bound_dispatch_site_count"], 1)
        self.assertEqual(coverage["abi_lowered_call_instruction_count"], 2)
        self.assertEqual(coverage["abi_unlowered_call_instruction_count"], 0)
        guarded = [
            item
            for unit in artifact.compact_document["units"]
            for cfg_block in unit["blocks"]
            for item in cfg_block["instructions"]
            if item["opcode"] == 11]
        self.assertEqual(len(guarded), 2)
        self.assertTrue(all(
            len(candidate["arguments"]) == 2 and
            candidate["runtime_bound_receiver_required"] is True
            for item in guarded for candidate in item["candidates"]))
        receivers = [row for row in artifact.adapter_table
                     if row["op"] ==
                     "extract-finite-bound-callable-receiver"]
        self.assertEqual(len(receivers), 1)
        extracted: list[tuple[object, int]] = []

        def adapter(_adapter_id: int, args: list[object],
                    descriptor: dict[str, object]) -> object:
            op = descriptor["op"]
            if op == "load-name":
                return (("receiver-A", 0) if args[0] == "callback_a" else
                        ("receiver-B", 1))
            if op == "require-callable":
                return args[0]
            if op == "resolve-finite-callable-identity":
                return args[0][1]
            if op == "extract-finite-bound-callable-receiver":
                callable_value, selected = args
                self.assertEqual(callable_value[1], selected)
                extracted.append((callable_value, selected))
                return callable_value[0]
            self.fail(f"unexpected adapter operation {op}")

        self.assertEqual(CompactTargetVMOracle(
            artifact, adapter=adapter).run("m::abi_caller@20"), 18)
        self.assertEqual(extracted, [
            (("receiver-A", 0), 0), (("receiver-B", 1), 1)])

        tampered = copy.deepcopy(call_abi)
        tampered["occurrence_abi_descriptors_in_cfg_order"][0][
            "target_descriptors"][0]["parameter_destination_map"][2][
                "source_kind"] = "argument"
        _resign(tampered)
        rejected = build_whole_program_vm(
            graph, active_call_site_lowering=lowering,
            whole_program_vm_call_abi=tampered)
        self.assertEqual(
            rejected.target_coverage["abi_finite_dispatch_instruction_count"],
            1)
        self.assertEqual(
            rejected.target_coverage["abi_unlowered_call_instruction_count"],
            1)

    def test_guarded_only_candidate_bodies_do_not_promote_reachability(
            self) -> None:
        graph, lowering, call_abi = guarded_only_finite_dispatch_abi_graph()
        artifact = build_whole_program_vm(
            graph, active_call_site_lowering=lowering,
            whole_program_vm_call_abi=call_abi)
        self.assertEqual(
            artifact.document["proven_reachable_callable_ids"],
            ["m::abi_caller@20"])
        self.assertEqual(artifact.document["guarded_callable_ids"], [
            "m::Worker.difference@21",
            "m::Worker.decoy_difference@22",
        ])
        self.assertTrue(all(
            row["admission"] == "runtime-identity-guard-only" and
            row["static_reachability_edge"] is False
            for row in artifact.document["guarded_callable_table"]))
        coverage = artifact.target_coverage
        self.assertEqual(coverage["function_count"], 3)
        self.assertEqual(coverage["proven_reachable_function_count"], 1)
        self.assertEqual(coverage["guarded_callable_function_count"], 2)
        self.assertEqual(coverage["abi_finite_dispatch_instruction_count"], 2)
        self.assertEqual(coverage["guarded_body_adapter_instruction_count"], 1)
        self.assertEqual(coverage["guarded_body_adapter_site_count"], 1)
        guarded_body_adapters = [
            row for row in artifact.adapter_table
            if row.get("resolution_kind") == "guarded-body-adapter"]
        self.assertEqual(len(guarded_body_adapters), 1)

        def adapter(_adapter_id: int, args: list[object],
                    descriptor: dict[str, object]) -> object:
            op = descriptor["op"]
            if op == "load-attribute":
                return f"bound:{args[0]}:{args[1]}"
            if op == "require-callable":
                return args[0]
            if op == "resolve-finite-callable-identity":
                return 0 if "receiver-A" in str(args[0]) else 1
            if op == "python-call" and descriptor.get(
                    "resolution_kind") == "guarded-body-adapter":
                return None
            self.fail(f"unexpected adapter operation {op}")

        self.assertEqual(CompactTargetVMOracle(
            artifact, adapter=adapter).run("m::abi_caller@20"), 18)

    def test_guarded_lexical_dispatch_requires_exact_active_owner(
            self) -> None:
        graph, lowering, call_abi = guarded_lexical_dispatch_abi_graph()
        artifact = build_whole_program_vm(
            graph, active_call_site_lowering=lowering,
            whole_program_vm_call_abi=call_abi)
        self.assertEqual(
            artifact.target_coverage[
                "abi_finite_lexical_dispatch_instruction_count"], 2)
        self.assertEqual(
            artifact.target_coverage[
                "abi_finite_lexical_dispatch_site_count"], 1)
        self.assertTrue(all(
            row["admission"] ==
            "runtime-identity-and-lexical-owner-guard-only" and
            row["lexical_owner_callable_id"] == "m::abi_caller@20"
            for row in artifact.document["guarded_callable_table"]))
        guarded = [
            item for unit in artifact.compact_document["units"]
            for cfg_block in unit["blocks"]
            for item in cfg_block["instructions"]
            if item["opcode"] == 12]
        self.assertEqual(len(guarded), 2)
        self.assertTrue(all(
            candidate["lexical_owner_function"] == 0
            for item in guarded for candidate in item["candidates"]))

        def adapter(_adapter_id: int, args: list[object],
                    descriptor: dict[str, object]) -> object:
            op = descriptor["op"]
            if op == "load-name":
                return "target-A" if args[0] == "callback_a" else "target-B"
            if op == "require-callable":
                return args[0]
            if op == "resolve-finite-callable-identity":
                return 0 if args[0] == "target-A" else 1
            if op == "python-call" and descriptor.get(
                    "resolution_kind") == "guarded-body-adapter":
                return None
            self.fail(f"unexpected adapter operation {op}")

        oracle = CompactTargetVMOracle(artifact, adapter=adapter)
        self.assertEqual(oracle.run("m::abi_caller@20", [100]), 18)
        with self.assertRaisesRegex(WholeProgramVMError, "PZWV272"):
            oracle.run("m::Worker.difference@21", [7, 2])

    def test_call_abi_constructor_allocates_binds_init_and_returns_object(
            self) -> None:
        graph, lowering, call_abi = constructor_abi_graph()
        artifact = build_whole_program_vm(
            graph, active_call_site_lowering=lowering,
            whole_program_vm_call_abi=call_abi)
        coverage = artifact.target_coverage
        self.assertEqual(coverage["abi_constructor_call_instruction_count"], 2)
        self.assertEqual(coverage["abi_unlowered_call_instruction_count"], 0)
        allocation_adapters = [
            row for row in artifact.adapter_table
            if row["op"] == "allocate-instance"]
        self.assertEqual(len(allocation_adapters), 1)
        self.assertEqual(sum(
            item["opcode"] == 7
            for unit in artifact.compact_document["units"]
            for cfg_block in unit["blocks"]
            for item in cfg_block["instructions"]), 2)

        events: list[tuple[str, list[object]]] = []

        def adapter(_adapter_id: int, args: list[object],
                    descriptor: dict[str, object]) -> object:
            op = str(descriptor["op"])
            events.append((op, list(args)))
            if op == "load-name":
                return "Widget"
            if op == "require-callable":
                return args[0]
            if op == "allocate-instance":
                return {"class": args[0]}
            if op == "record-init":
                instance = args[0]
                assert isinstance(instance, dict)
                instance["init"] = (args[1], args[2])
                return None
            self.fail(f"unexpected adapter operation {op}")

        result = CompactTargetVMOracle(
            artifact, adapter=adapter).run("m::abi_caller@20")
        self.assertEqual(result, {"class": "m::Widget@21", "init": (9, 4)})
        self.assertEqual([op for op, _args in events].count(
            "allocate-instance"), 2)
        self.assertEqual([op for op, _args in events].count("record-init"), 2)
        first_init = next(args for op, args in events if op == "record-init")
        self.assertEqual(first_init[1:], [7, 2])

    def test_call_abi_constructor_tamper_and_non_none_init_fail_closed(
            self) -> None:
        graph, lowering, call_abi = constructor_abi_graph()
        mutations = []
        wrong_sequence = copy.deepcopy(call_abi)
        wrong_sequence["occurrence_abi_descriptors_in_cfg_order"][0][
            "constructor_sequence"][2]["required_return"] = 0
        mutations.append(wrong_sequence)
        wrong_self = copy.deepcopy(call_abi)
        mapping = wrong_self["occurrence_abi_descriptors_in_cfg_order"][0][
            "target_descriptors"][0]["parameter_destination_map"]
        mapping[0], mapping[1] = mapping[1], mapping[0]
        mutations.append(wrong_self)
        for tampered in mutations:
            _resign(tampered)
            with self.assertRaisesRegex(WholeProgramVMError, "PZWV265"):
                build_whole_program_vm(
                    graph, active_call_site_lowering=lowering,
                    whole_program_vm_call_abi=tampered)

        target_cfg = graph["callable_inventory"]["callables"][1]["cfg"]
        target_cfg["blocks"][0]["terminator"]["arguments"] = ["%ignored"]
        _resign(target_cfg)
        _resign(graph)
        lowering["active_call_graph_semantic_sha256"] = graph["semantic_sha256"]
        _resign(lowering)
        call_abi["active_call_graph_semantic_sha256"] = graph["semantic_sha256"]
        call_abi["call_site_lowering_semantic_sha256"] = lowering[
            "semantic_sha256"]
        _resign(call_abi)
        artifact = build_whole_program_vm(
            graph, active_call_site_lowering=lowering,
            whole_program_vm_call_abi=call_abi)

        def adapter(_adapter_id: int, args: list[object],
                    descriptor: dict[str, object]) -> object:
            op = descriptor["op"]
            if op == "load-name":
                return "Widget"
            if op == "require-callable":
                return args[0]
            if op == "allocate-instance":
                return {"class": args[0]}
            if op == "record-init":
                return 1
            self.fail(f"unexpected adapter operation {op}")

        with self.assertRaisesRegex(WholeProgramVMError, "PZWV267"):
            CompactTargetVMOracle(
                artifact, adapter=adapter).run("m::abi_caller@20")

    def test_call_abi_keeps_omitted_default_on_adapter_path(self) -> None:
        graph, lowering, call_abi = defaulted_abi_bound_keyword_graph()
        descriptor = call_abi[
            "occurrence_abi_descriptors_in_cfg_order"][0]
        descriptor["blocker_codes"] = ["PZCABI209"]
        descriptor["target_descriptors"][0]["blocker_codes"] = ["PZCABI209"]
        call_abi["census"]["blocker_descriptor_counts"] = {"PZCABI209": 1}
        call_abi["live_blockers"].append({
            "code": "PZCABI209", "count": 1,
            "detail": "a default expression remains a runtime ABI input",
        })
        _resign(call_abi)
        artifact = build_whole_program_vm(
            graph, active_call_site_lowering=lowering,
            whole_program_vm_call_abi=call_abi)
        self.assertEqual(
            artifact.target_coverage["abi_lowered_call_instruction_count"], 1)
        self.assertEqual(
            artifact.target_coverage["abi_unlowered_call_instruction_count"], 1)
        self.assertEqual(
            artifact.target_coverage["abi_unlowered_reason_counts"][
                "abi-blocker:PZCABI209"], 1)

    def test_call_abi_fallback_and_tamper_fail_closed(self) -> None:
        graph, lowering, call_abi = abi_bound_keyword_graph()
        fallback = build_whole_program_vm(graph)
        self.assertFalse(fallback.target_coverage["call_abi_input_enabled"])
        self.assertEqual(
            fallback.target_coverage["abi_unlowered_call_instruction_count"],
            2)
        self.assertTrue(any(row["op"] == "python-call"
                            for row in fallback.adapter_table))
        with self.assertRaisesRegex(WholeProgramVMError, "PZWV266"):
            build_whole_program_vm(
                graph, active_call_site_lowering=lowering)

        semantic_tamper = copy.deepcopy(call_abi)
        semantic_tamper["occurrence_abi_descriptors_in_cfg_order"][0][
            "target_descriptors"][0]["parameter_destination_map"][1][
                "source_value"] = "%left_a"
        with self.assertRaisesRegex(WholeProgramVMError, "PZWV005"):
            build_whole_program_vm(
                graph, active_call_site_lowering=lowering,
                whole_program_vm_call_abi=semantic_tamper)

        bound_tamper = copy.deepcopy(call_abi)
        bound_tamper["occurrence_abi_descriptors_in_cfg_order"][0][
            "target_descriptors"][0]["parameter_destination_map"][1][
                "source_value"] = "%left_a"
        _resign(bound_tamper)
        with self.assertRaisesRegex(WholeProgramVMError, "PZWV265"):
            build_whole_program_vm(
                graph, active_call_site_lowering=lowering,
                whole_program_vm_call_abi=bound_tamper)

        path_tamper = copy.deepcopy(lowering)
        path_tamper["cfg_occurrences_in_cfg_order"][0]["cfg_path"][-1] = 11
        _resign(path_tamper)
        path_abi = copy.deepcopy(call_abi)
        path_abi["call_site_lowering_semantic_sha256"] = path_tamper[
            "semantic_sha256"]
        _resign(path_abi)
        with self.assertRaisesRegex(WholeProgramVMError, "PZWV264"):
            build_whole_program_vm(
                graph, active_call_site_lowering=path_tamper,
                whole_program_vm_call_abi=path_abi)

    def test_call_abi_resigned_receiver_and_target_forgery_fails_closed(
            self) -> None:
        graph, lowering, call_abi = abi_bound_keyword_graph()

        forged_receiver = copy.deepcopy(call_abi)
        receiver_descriptor = forged_receiver[
            "occurrence_abi_descriptors_in_cfg_order"][0]
        receiver_descriptor["receiver_value"] = "%right_a"
        provenance = receiver_descriptor["callable_ssa_provenance"]
        provenance["receiver_value"] = "%right_a"
        provenance["callable_source"]["arguments"][0] = "%right_a"
        provenance["receiver_provenance"] = {
            "value": "%right_a",
            "kind": "ssa-definition",
            "definition": _instruction_proof(instruction(
                3, "constant", [2], "%right_a")),
            "inputs": [],
        }
        receiver_map = receiver_descriptor["target_descriptors"][0][
            "parameter_destination_map"][0]
        receiver_map["source_value"] = "%right_a"
        _resign(forged_receiver)
        with self.assertRaisesRegex(
                WholeProgramVMError,
                "PZWV265: ABI callable SSA provenance differs from CFG"):
            build_whole_program_vm(
                graph, active_call_site_lowering=lowering,
                whole_program_vm_call_abi=forged_receiver)

        forged_target = copy.deepcopy(call_abi)
        target_descriptor = forged_target[
            "occurrence_abi_descriptors_in_cfg_order"][0]
        target_descriptor["target_descriptors"][0].update({
            "callable_id": "m::Worker.decoy_difference@22",
            "numeric_function_id": 2,
            "current_pzvt_function_id": 2,
        })
        target_descriptor["target_numeric_function_ids"] = [2]
        _resign(forged_target)
        with self.assertRaisesRegex(
                WholeProgramVMError,
                "PZWV265: ABI target/active-graph binding mismatch"):
            build_whole_program_vm(
                graph, active_call_site_lowering=lowering,
                whole_program_vm_call_abi=forged_target)

    def test_call_abi_required_blockers_and_prerequisite_fail_closed(
            self) -> None:
        graph, lowering, call_abi = abi_bound_keyword_graph()

        blocked_super = copy.deepcopy(call_abi)
        super_descriptor = blocked_super[
            "occurrence_abi_descriptors_in_cfg_order"][0]
        super_descriptor["binding_mode"] = "super"
        super_descriptor["target_descriptors"][0]["binding_mode"] = "super"
        super_descriptor["blocker_codes"] = ["PZCABI214"]
        blocked_super["census"]["blocker_descriptor_counts"] = {
            "PZCABI214": 1}
        blocked_super["live_blockers"].insert(1, {
            "code": "PZCABI214", "count": 1,
            "detail": (
                "a super proxy cannot be passed as the target method self "
                "receiver"),
        })
        _resign(blocked_super)
        blocked_artifact = build_whole_program_vm(
            graph, active_call_site_lowering=lowering,
            whole_program_vm_call_abi=blocked_super)
        self.assertEqual(
            blocked_artifact.target_coverage[
                "abi_unlowered_call_instruction_count"], 1)

        missing_214 = copy.deepcopy(blocked_super)
        missing_214["occurrence_abi_descriptors_in_cfg_order"][0][
            "blocker_codes"].remove("PZCABI214")
        _resign(missing_214)
        with self.assertRaisesRegex(WholeProgramVMError, "PZWV263: PZCABI214"):
            build_whole_program_vm(
                graph, active_call_site_lowering=lowering,
                whole_program_vm_call_abi=missing_214)

        missing_215 = copy.deepcopy(call_abi)
        missing_215["live_blockers"] = [
            row for row in missing_215["live_blockers"]
            if row["code"] != "PZCABI215"]
        _resign(missing_215)
        with self.assertRaisesRegex(
                WholeProgramVMError,
                "PZWV263: call ABI required live blocker census differs"):
            build_whole_program_vm(
                graph, active_call_site_lowering=lowering,
                whole_program_vm_call_abi=missing_215)

        missing_prerequisite = copy.deepcopy(call_abi)
        missing_prerequisite.pop("call_site_lowering_prerequisites")
        _resign(missing_prerequisite)
        with self.assertRaisesRegex(
                WholeProgramVMError,
                "PZWV001: call ABI lowering prerequisites is not an object"):
            build_whole_program_vm(
                graph, active_call_site_lowering=lowering,
                whole_program_vm_call_abi=missing_prerequisite)

    def test_function_names_are_not_dynamically_scoped_and_nested_expression_is(self) -> None:
        with self.assertRaisesRegex(WholeProgramVMError, "PZWV254"):
            CompactTargetVMOracle(self.artifact).run("m::scope_caller@7")
        calls: list[tuple[str, list[object]]] = []

        def adapter(_adapter_id: int, args: list[object],
                    descriptor: dict[str, object]) -> object:
            calls.append((str(descriptor["op"]), args))
            return 7

        self.assertEqual(CompactTargetVMOracle(
            self.artifact, adapter=adapter).run("m::scope_caller@7"), 7)
        self.assertEqual(calls, [("load-name", ["shadow"])])
        # Explicit expression-owner links may form a bounded lexical chain.
        self.assertEqual(CompactTargetVMOracle(self.artifact).run(
            "m::nested_scope@9"), 42)

    def test_frame_slot_count_includes_ssa_and_unique_bound_names(self) -> None:
        function_ids = {identifier: index for index, identifier in enumerate(
            self.artifact.document["proven_reachable_callable_ids"])}
        function_units = self.artifact.compact_document["functions"]
        scope_unit = self.artifact.compact_document["units"][
            function_units[function_ids["m::scope_caller@7"]]]
        self.assertEqual(scope_unit["local_count"], 2)
        self.assertEqual(scope_unit["frame_slot_count"], 3)
        large_unit = self.artifact.compact_document["units"][
            function_units[function_ids["m::large_frame@11"]]]
        self.assertEqual(large_unit["local_count"], 260)
        self.assertEqual(large_unit["frame_slot_count"], 280)
        self.assertEqual(
            self.artifact.target_coverage["max_frame_slot_count"], 280)

    def test_generator_suspend_resume_is_sticky(self) -> None:
        generator = WholeProgramVMOracle(self.artifact).generator("m::generator@4")
        self.assertEqual(generator.resume(), 10)
        self.assertEqual(generator.resume(), 20)
        with self.assertRaises(StopIteration) as finished:
            generator.resume()
        self.assertEqual(finished.exception.value, 30)
        with self.assertRaises(StopIteration):
            generator.resume()
        compact = CompactTargetVMOracle(
            self.artifact).generator("m::generator@4")
        self.assertEqual(compact.resume(), 10)
        self.assertEqual(compact.resume(), 20)
        with self.assertRaises(StopIteration) as finished_compact:
            compact.resume()
        self.assertEqual(finished_compact.exception.value, 30)

    def test_call_frame_overflow_and_missing_adapter_fail_closed(self) -> None:
        oracle = WholeProgramVMOracle(self.artifact, max_call_depth=3)
        with self.assertRaisesRegex(WholeProgramVMError, "PZWV107"):
            oracle.run("m::recurse@3")
        with self.assertRaisesRegex(WholeProgramVMError, "PZWV104"):
            oracle.run("m::host@5")
        with self.assertRaisesRegex(WholeProgramVMError, "PZWV256"):
            CompactTargetVMOracle(
                self.artifact, max_call_depth=3).run("m::recurse@3")
        with self.assertRaisesRegex(WholeProgramVMError, "PZWV254"):
            CompactTargetVMOracle(self.artifact).run("m::host@5")

    def test_adapter_is_called_once_in_source_order(self) -> None:
        calls: list[tuple[str, list[object]]] = []

        def adapter(op: str, args: list[object], _attrs: dict[str, object],
                    _span: dict[str, object]) -> object:
            calls.append((op, args))
            return args[0] + 1

        oracle = WholeProgramVMOracle(self.artifact, adapter=adapter)
        self.assertEqual(oracle.run("m::host@5"), 8)
        self.assertEqual(calls, [("python-magic", [7])])
        compact_calls: list[tuple[int, list[object], str]] = []

        def compact_adapter(adapter_id: int, args: list[object],
                            descriptor: dict[str, object]) -> object:
            compact_calls.append((adapter_id, args, str(descriptor["op"])))
            return args[0] + 1

        compact_oracle = CompactTargetVMOracle(
            self.artifact, adapter=compact_adapter)
        self.assertEqual(compact_oracle.run("m::host@5"), 8)
        self.assertEqual(len(compact_calls), 1)
        self.assertEqual(compact_calls[0][1:], ([7], "python-magic"))

    def test_current_active_graph_census_read_only(self) -> None:
        report = ROOT / "Build/rtype_python_active_call_graph_status.json"
        if not report.is_file():
            self.skipTest("current active-call-graph report is absent")
        before = hashlib.sha256(report.read_bytes()).hexdigest()
        graph = json.loads(report.read_text(encoding="utf-8"))
        artifact = build_whole_program_vm(graph)
        expected = len(graph["call_graph"]["proven_reachable_callable_ids"])
        self.assertEqual(artifact.coverage["function_count"], expected)
        self.assertEqual(
            artifact.coverage["expression_program_count"],
            sum(len(row["cfg"]["expression_programs"])
                for row in graph["callable_inventory"]["callables"]
                if row["callable_id"] in set(
                    graph["call_graph"]["proven_reachable_callable_ids"])))
        self.assertEqual(hashlib.sha256(report.read_bytes()).hexdigest(), before)

    @unittest.skipUnless(TCC is not None, "TCC host compiler unavailable")
    def test_c_runtime_executes_and_checks_all_bounds(self) -> None:
        assert TCC is not None
        with tempfile.TemporaryDirectory(prefix="pyz80-whole-vm-host-") as tmp:
            directory = Path(tmp)
            shutil.copy2(RUNTIME_C, directory / RUNTIME_C.name)
            shutil.copy2(RUNTIME_H, directory / RUNTIME_H.name)
            image = ",".join(f"0x{byte:02X}" for byte in self.artifact.bytecode)
            proof_hash = ",".join(
                f"0x{byte:02X}" for byte in bytes.fromhex(
                    self.artifact.semantic_sha256))
            main_frame_slots = self.artifact.compact_document["units"][
                self.artifact.compact_document["functions"][0]]["frame_slot_count"]
            large_frame_slots = self.artifact.compact_document["units"][
                self.artifact.compact_document["functions"][10]]["frame_slot_count"]
            harness = f'''#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "pyz80_whole_program_vm.h"
static const uint8_t image_bytes[] = {{{image}}};
static const uint8_t proof_sha256[32] = {{{proof_hash}}};
typedef union AlignedArena {{ uint32_t align; uint8_t bytes[8192]; }} AlignedArena;
static uint8_t adapter_calls;
static uint8_t adapter_value_mode;
static uint8_t invoke(void *context, struct PyZ80VM *vm, uint16_t op,
                      uint16_t destination, const PyZ80VMValue *arguments,
                      uint8_t count, uint32_t raw, PyZ80VMValue *result) {{
    (void)context; (void)vm; (void)op; (void)destination;
    (void)arguments; (void)count; (void)raw;
    ++adapter_calls;
    result->kind = adapter_value_mode ? PYZ80_VM_VALUE_I32 : PYZ80_VM_VALUE_NONE;
    result->payload = adapter_value_mode ? 7u : 0u;
    result->symbol = PYZ80_VM_NO_SYMBOL; result->reserved = 0; return 1;
}}
static int check_value(PyZ80VMValue *v, int32_t n) {{
    return v->kind == PYZ80_VM_VALUE_I32 && (int32_t)v->payload == n;
}}
int main(void) {{
    PyZ80VM vm; PyZ80VMLimits limits = {{4, 1, 16, 8}};
    PyZ80VMMemoryImage memory = {{image_bytes, sizeof(image_bytes)}};
    PyZ80VMImage image = {{PyZ80VM_MemoryRead, &memory, sizeof(image_bytes),
                           proof_sha256}};
    PyZ80VMAdapter adapter = {{invoke, 0, 0}}; AlignedArena arena;
    PyZ80VMValue result; PyZ80VMValue start_argument;
    uint16_t handle; uint16_t need;
    uint8_t broken[sizeof(image_bytes)]; PyZ80VMMemoryImage bad_memory;
    need = PyZ80VM_ArenaBytes(&limits);
    image.expected_proof_sha256 = 0;
    if (PyZ80VM_Init(&vm, &image, &adapter, arena.bytes, sizeof(arena.bytes),
                     &limits) != PYZ80_VM_ERROR ||
        PyZ80VM_LastError(&vm) != PYZ80_VM_E_ARGUMENT) return 22;
    image.expected_proof_sha256 = proof_sha256;
    if (!need || PyZ80VM_Init(&vm, &image, &adapter, arena.bytes,
                              (uint16_t)(need - 1), &limits) != PYZ80_VM_ERROR ||
        PyZ80VM_LastError(&vm) != PYZ80_VM_E_ARENA) return 1;
    if (PyZ80VM_Init(&vm, &image, &adapter, arena.bytes, sizeof(arena.bytes),
                     &limits) != PYZ80_VM_IDLE) return 2;
    if (PyZ80VM_Start(&vm, 0) != PYZ80_VM_RUNNING ||
        PyZ80VM_Run(&vm, 1000, &result) != PYZ80_VM_RETURNED ||
        !check_value(&result, 11)) return 3;
    start_argument.kind = PYZ80_VM_VALUE_I32;
    start_argument.reserved = 0u;
    start_argument.symbol = PYZ80_VM_NO_SYMBOL;
    start_argument.payload = 123u;
    if (PyZ80VM_StartArgs(&vm, 12, &start_argument, 1u) != PYZ80_VM_RUNNING ||
        PyZ80VM_Run(&vm, 100, &result) != PYZ80_VM_RETURNED ||
        !check_value(&result, 123)) return 23;
    if (PyZ80VM_Start(&vm, 12) != PYZ80_VM_ERROR ||
        PyZ80VM_LastError(&vm) != PYZ80_VM_E_ARGUMENT) return 24;
    if (PyZ80VM_StartArgs(&vm, 12, NULL, 1u) != PYZ80_VM_ERROR ||
        PyZ80VM_LastError(&vm) != PYZ80_VM_E_ARGUMENT) return 25;
    if (PyZ80VM_StartArgs(&vm, 0, &start_argument, 9u) != PYZ80_VM_ERROR ||
        PyZ80VM_LastError(&vm) != PYZ80_VM_E_ARGUMENT) return 26;
    limits.locals_per_frame = {main_frame_slots - 1}u;
    if (PyZ80VM_Init(&vm, &image, &adapter, arena.bytes, sizeof(arena.bytes),
                     &limits) != PYZ80_VM_IDLE ||
        PyZ80VM_Start(&vm, 0) != PYZ80_VM_ERROR ||
        PyZ80VM_LastError(&vm) != PYZ80_VM_E_LOCAL_OVERFLOW) return 12;
    limits.locals_per_frame = {main_frame_slots}u;
    if (PyZ80VM_Init(&vm, &image, &adapter, arena.bytes, sizeof(arena.bytes),
                     &limits) != PYZ80_VM_IDLE ||
        PyZ80VM_Start(&vm, 0) != PYZ80_VM_RUNNING ||
        PyZ80VM_Run(&vm, 1000, &result) != PYZ80_VM_RETURNED ||
        !check_value(&result, 11)) return 13;
    limits.locals_per_frame = 16u;
    if (PyZ80VM_Init(&vm, &image, &adapter, arena.bytes, sizeof(arena.bytes),
                     &limits) != PYZ80_VM_IDLE) return 14;
    adapter_calls = 0; adapter_value_mode = 1;
    if (PyZ80VM_Start(&vm, 6) != PYZ80_VM_RUNNING ||
        PyZ80VM_Run(&vm, 100, &result) != PYZ80_VM_RETURNED ||
        !check_value(&result, 7) || adapter_calls != 1) return 15;
    adapter_value_mode = 0;
    if (PyZ80VM_Start(&vm, 8) != PYZ80_VM_RUNNING ||
        PyZ80VM_Run(&vm, 100, &result) != PYZ80_VM_RETURNED ||
        !check_value(&result, 42)) return 16;
    if (PyZ80VM_Start(&vm, 9) != PYZ80_VM_RUNNING ||
        PyZ80VM_Run(&vm, 100, &result) != PYZ80_VM_RETURNED ||
        !check_value(&result, 5)) return 17;
    limits.max_call_depth = 1u; limits.max_generators = 0u;
    limits.locals_per_frame = {large_frame_slots - 1}u;
    if (PyZ80VM_Init(&vm, &image, &adapter, arena.bytes, sizeof(arena.bytes),
                     &limits) != PYZ80_VM_IDLE ||
        PyZ80VM_Start(&vm, 10) != PYZ80_VM_ERROR ||
        PyZ80VM_LastError(&vm) != PYZ80_VM_E_LOCAL_OVERFLOW) return 18;
    limits.locals_per_frame = {large_frame_slots}u;
    if (PyZ80VM_Init(&vm, &image, &adapter, arena.bytes, sizeof(arena.bytes),
                     &limits) != PYZ80_VM_IDLE ||
        PyZ80VM_Start(&vm, 10) != PYZ80_VM_RUNNING ||
        PyZ80VM_Run(&vm, 400, &result) != PYZ80_VM_RETURNED ||
        !check_value(&result, 259)) return 19;
    limits.max_call_depth = 4u; limits.max_generators = 1u;
    limits.locals_per_frame = 16u;
    if (PyZ80VM_Init(&vm, &image, &adapter, arena.bytes, sizeof(arena.bytes),
                     &limits) != PYZ80_VM_IDLE) return 20;
    if (PyZ80VM_GeneratorCreate(&vm, 3, &handle) != PYZ80_VM_IDLE) return 4;
    if (PyZ80VM_GeneratorResume(&vm, handle, 0, 100, &result) != PYZ80_VM_YIELDED ||
        !check_value(&result, 10)) return 5;
    if (PyZ80VM_GeneratorResume(&vm, handle, 0, 100, &result) != PYZ80_VM_YIELDED ||
        !check_value(&result, 20)) return 6;
    if (PyZ80VM_GeneratorResume(&vm, handle, 0, 100, &result) != PYZ80_VM_RETURNED ||
        !check_value(&result, 30)) return 7;
    if (PyZ80VM_GeneratorCreate(&vm, 3, &handle) != PYZ80_VM_ERROR ||
        PyZ80VM_LastError(&vm) != PYZ80_VM_E_GENERATOR_OVERFLOW) return 8;
    if (PyZ80VM_Start(&vm, 2) != PYZ80_VM_RUNNING ||
        PyZ80VM_Run(&vm, 100, &result) != PYZ80_VM_ERROR ||
        PyZ80VM_LastError(&vm) != PYZ80_VM_E_CALL_OVERFLOW) return 9;
    adapter_calls = 0;
    if (PyZ80VM_Start(&vm, 5) != PYZ80_VM_RUNNING ||
        PyZ80VM_Run(&vm, 100, &result) != PYZ80_VM_ERROR ||
        PyZ80VM_LastError(&vm) != PYZ80_VM_E_ADAPTER ||
        adapter_calls != 4) return 10;
    memcpy(broken, image_bytes, sizeof(broken)); broken[16] ^= 1;
    bad_memory.bytes = broken; bad_memory.size = sizeof(broken); image.context = &bad_memory;
    if (PyZ80VM_Init(&vm, &image, &adapter, arena.bytes, sizeof(arena.bytes),
                     &limits) != PYZ80_VM_ERROR ||
        PyZ80VM_LastError(&vm) != PYZ80_VM_E_PROOF_HASH) return 11;
    memcpy(broken, image_bytes, sizeof(broken)); broken[sizeof(broken)-1] ^= 1;
    if (PyZ80VM_Init(&vm, &image, &adapter, arena.bytes, sizeof(arena.bytes),
                     &limits) != PYZ80_VM_ERROR ||
        PyZ80VM_LastError(&vm) != PYZ80_VM_E_IMAGE_CRC) return 21;
    puts("PZVM_HOST_OK"); return 0;
}}
'''
            (directory / "check.c").write_text(harness, encoding="utf-8")
            command = [str(TCC), "-std=c11", "-Wall", "-Werror",
                       "pyz80_whole_program_vm.c", "check.c", "-o", "check.exe"]
            compiled = subprocess.run(
                command, cwd=directory, check=False, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding="utf-8", errors="replace", timeout=120)
            self.assertEqual(compiled.returncode, 0, compiled.stdout)
            executed = subprocess.run(
                [str(directory / "check.exe")], cwd=directory, check=False,
                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding="utf-8", errors="replace", timeout=120)
            self.assertEqual(executed.returncode, 0, executed.stdout)
            self.assertIn("PZVM_HOST_OK", executed.stdout)

    @unittest.skipUnless(TCC is not None, "TCC host compiler unavailable")
    def test_c_runtime_executes_constructor_protocol_and_checks_contracts(
            self) -> None:
        assert TCC is not None
        graph, lowering, call_abi = constructor_abi_graph()
        target_cfg = graph["callable_inventory"]["callables"][1]["cfg"]
        target_cfg["blocks"][0]["terminator"]["arguments"] = ["%ignored"]
        _resign(target_cfg)
        _resign(graph)
        lowering["active_call_graph_semantic_sha256"] = graph["semantic_sha256"]
        _resign(lowering)
        call_abi["active_call_graph_semantic_sha256"] = graph["semantic_sha256"]
        call_abi["call_site_lowering_semantic_sha256"] = lowering[
            "semantic_sha256"]
        _resign(call_abi)
        artifact = build_whole_program_vm(
            graph, active_call_site_lowering=lowering,
            whole_program_vm_call_abi=call_abi)
        adapter_ids = {row["op"]: row["adapter_id"]
                       for row in artifact.adapter_table}
        for required in ("allocate-instance", "load-name", "require-callable",
                         "record-init"):
            self.assertIn(required, adapter_ids)
        with tempfile.TemporaryDirectory(prefix="pyz80-construct-vm-host-") as tmp:
            directory = Path(tmp)
            shutil.copy2(RUNTIME_C, directory / RUNTIME_C.name)
            shutil.copy2(RUNTIME_H, directory / RUNTIME_H.name)
            image = ",".join(
                f"0x{byte:02X}" for byte in artifact.target_bytecode)
            proof_hash = ",".join(
                f"0x{byte:02X}" for byte in bytes.fromhex(
                    artifact.semantic_sha256))
            harness = f'''#include <stdint.h>
#include <stdio.h>
#include "pyz80_whole_program_vm.h"
static const uint8_t image_bytes[] = {{{image}}};
static const uint8_t proof_sha256[32] = {{{proof_hash}}};
typedef union AlignedArena {{ uint32_t align; uint8_t bytes[8192]; }} AlignedArena;
static uint8_t mode;
static uint8_t allocations;
static uint8_t initializations;
static uint8_t invoke(void *context, struct PyZ80VM *vm, uint16_t op,
                      uint16_t destination, const PyZ80VMValue *arguments,
                      uint8_t count, uint32_t raw, PyZ80VMValue *result) {{
    (void)context; (void)vm; (void)destination; (void)raw;
    result->reserved = 0u; result->symbol = PYZ80_VM_NO_SYMBOL;
    if (op == {adapter_ids['allocate-instance']}u) {{
        if (count != 1u) return 0u;
        ++allocations;
        result->kind = mode == 1u ? PYZ80_VM_VALUE_I32 : PYZ80_VM_VALUE_OPAQUE;
        result->payload = (uint32_t)(0xB000u + allocations);
        return 1u;
    }}
    if (op == {adapter_ids['record-init']}u) {{
        if (count != 3u || arguments[0].kind != PYZ80_VM_VALUE_OPAQUE ||
            arguments[1].kind != PYZ80_VM_VALUE_I32 ||
            arguments[2].kind != PYZ80_VM_VALUE_I32) return 0u;
        ++initializations;
        result->kind = mode == 2u ? PYZ80_VM_VALUE_I32 : PYZ80_VM_VALUE_NONE;
        result->payload = mode == 2u ? 1u : 0u;
        return 1u;
    }}
    if (op == {adapter_ids['load-name']}u) {{
        result->kind = PYZ80_VM_VALUE_SYMBOL; result->payload = 0u;
        return count == 1u;
    }}
    if (op == {adapter_ids['require-callable']}u) {{
        if (count != 1u) return 0u;
        *result = arguments[0]; return 1u;
    }}
    return 0u;
}}
static uint8_t reset(PyZ80VM *vm, PyZ80VMImage *image,
                     PyZ80VMAdapter *adapter, AlignedArena *arena,
                     PyZ80VMLimits *limits) {{
    allocations = 0u; initializations = 0u;
    return PyZ80VM_Init(vm, image, adapter, arena->bytes,
                        sizeof(arena->bytes), limits);
}}
int main(void) {{
    PyZ80VM vm; PyZ80VMLimits limits = {{8, 0, 32, 8}};
    PyZ80VMMemoryImage memory = {{image_bytes, sizeof(image_bytes)}};
    PyZ80VMImage image = {{PyZ80VM_MemoryRead, &memory, sizeof(image_bytes),
                           proof_sha256}};
    PyZ80VMAdapter adapter = {{invoke, 0, 0}}; AlignedArena arena;
    PyZ80VMValue result;
    mode = 0u;
    if (reset(&vm, &image, &adapter, &arena, &limits) != PYZ80_VM_IDLE ||
        PyZ80VM_Start(&vm, 0u) != PYZ80_VM_RUNNING ||
        PyZ80VM_Run(&vm, 1000u, &result) != PYZ80_VM_RETURNED ||
        result.kind != PYZ80_VM_VALUE_OPAQUE || result.payload != 0xB002u ||
        allocations != 2u || initializations != 2u) return 1;
    mode = 1u;
    if (reset(&vm, &image, &adapter, &arena, &limits) != PYZ80_VM_IDLE ||
        PyZ80VM_Start(&vm, 0u) != PYZ80_VM_RUNNING ||
        PyZ80VM_Run(&vm, 1000u, &result) != PYZ80_VM_ERROR ||
        PyZ80VM_LastError(&vm) != PYZ80_VM_E_ADAPTER ||
        allocations != 1u || initializations != 0u) return 2;
    mode = 2u;
    if (reset(&vm, &image, &adapter, &arena, &limits) != PYZ80_VM_IDLE ||
        PyZ80VM_Start(&vm, 0u) != PYZ80_VM_RUNNING ||
        PyZ80VM_Run(&vm, 1000u, &result) != PYZ80_VM_ERROR ||
        PyZ80VM_LastError(&vm) != PYZ80_VM_E_ARGUMENT ||
        allocations != 1u || initializations != 1u) return 3;
    puts("PZVM_CONSTRUCT_OK"); return 0;
}}
'''
            (directory / "check.c").write_text(harness, encoding="utf-8")
            compiled = subprocess.run(
                [str(TCC), "-std=c11", "-Wall", "-Werror",
                 "pyz80_whole_program_vm.c", "check.c", "-o", "check.exe"],
                cwd=directory, check=False, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding="utf-8", errors="replace", timeout=120)
            self.assertEqual(compiled.returncode, 0, compiled.stdout)
            executed = subprocess.run(
                [str(directory / "check.exe")], cwd=directory, check=False,
                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding="utf-8", errors="replace", timeout=120)
            self.assertEqual(executed.returncode, 0, executed.stdout)
            self.assertIn("PZVM_CONSTRUCT_OK", executed.stdout)

    @unittest.skipUnless(TCC is not None, "TCC host compiler unavailable")
    def test_c_runtime_executes_guarded_finite_dispatch(self) -> None:
        assert TCC is not None
        graph, lowering, call_abi = finite_dispatch_abi_graph()
        artifact = build_whole_program_vm(
            graph, active_call_site_lowering=lowering,
            whole_program_vm_call_abi=call_abi)
        adapter_ids = {row["op"]: row["adapter_id"]
                       for row in artifact.adapter_table}
        for required in ("load-attribute", "require-callable",
                         "resolve-finite-callable-identity"):
            self.assertIn(required, adapter_ids)
        with tempfile.TemporaryDirectory(prefix="pyz80-dispatch-vm-host-") as tmp:
            directory = Path(tmp)
            shutil.copy2(RUNTIME_C, directory / RUNTIME_C.name)
            shutil.copy2(RUNTIME_H, directory / RUNTIME_H.name)
            image = ",".join(
                f"0x{byte:02X}" for byte in artifact.target_bytecode)
            proof_hash = ",".join(
                f"0x{byte:02X}" for byte in bytes.fromhex(
                    artifact.semantic_sha256))
            harness = f'''#include <stdint.h>
#include <stdio.h>
#include "pyz80_whole_program_vm.h"
static const uint8_t image_bytes[] = {{{image}}};
static const uint8_t proof_sha256[32] = {{{proof_hash}}};
typedef union AlignedArena {{ uint32_t align; uint8_t bytes[8192]; }} AlignedArena;
static uint8_t mode;
static uint8_t loaded;
static uint8_t guards;
static uint8_t invoke(void *context, struct PyZ80VM *vm, uint16_t op,
                      uint16_t destination, const PyZ80VMValue *arguments,
                      uint8_t count, uint32_t raw, PyZ80VMValue *result) {{
    (void)context; (void)vm; (void)destination; (void)raw;
    result->reserved = 0u; result->symbol = PYZ80_VM_NO_SYMBOL;
    if (op == {adapter_ids['load-attribute']}u) {{
        if (count != 2u) return 0u;
        result->kind = PYZ80_VM_VALUE_OPAQUE;
        result->payload = loaded++;
        return 1u;
    }}
    if (op == {adapter_ids['require-callable']}u) {{
        if (count != 1u || arguments[0].kind != PYZ80_VM_VALUE_OPAQUE)
            return 0u;
        *result = arguments[0];
        return 1u;
    }}
    if (op == {adapter_ids['resolve-finite-callable-identity']}u) {{
        if (count != 1u || arguments[0].kind != PYZ80_VM_VALUE_OPAQUE)
            return 0u;
        ++guards;
        result->kind = mode == 2u ? PYZ80_VM_VALUE_BOOL : PYZ80_VM_VALUE_I32;
        result->payload = mode == 1u ? 2u : arguments[0].payload;
        return 1u;
    }}
    return 0u;
}}
static uint8_t reset(PyZ80VM *vm, PyZ80VMImage *image,
                     PyZ80VMAdapter *adapter, AlignedArena *arena,
                     PyZ80VMLimits *limits) {{
    loaded = 0u; guards = 0u;
    return PyZ80VM_Init(vm, image, adapter, arena->bytes,
                        sizeof(arena->bytes), limits);
}}
int main(void) {{
    PyZ80VM vm; PyZ80VMLimits limits = {{8, 0, 32, 8}};
    PyZ80VMMemoryImage memory = {{image_bytes, sizeof(image_bytes)}};
    PyZ80VMImage image = {{PyZ80VM_MemoryRead, &memory, sizeof(image_bytes),
                           proof_sha256}};
    PyZ80VMAdapter adapter = {{invoke, 0, 0}}; AlignedArena arena;
    PyZ80VMValue result;
    mode = 0u;
    if (reset(&vm, &image, &adapter, &arena, &limits) != PYZ80_VM_IDLE ||
        PyZ80VM_Start(&vm, 0u) != PYZ80_VM_RUNNING ||
        PyZ80VM_Run(&vm, 1000u, &result) != PYZ80_VM_RETURNED ||
        result.kind != PYZ80_VM_VALUE_I32 || result.payload != 18u ||
        guards != 2u) return 1;
    mode = 1u;
    if (reset(&vm, &image, &adapter, &arena, &limits) != PYZ80_VM_IDLE ||
        PyZ80VM_Start(&vm, 0u) != PYZ80_VM_RUNNING ||
        PyZ80VM_Run(&vm, 1000u, &result) != PYZ80_VM_ERROR ||
        PyZ80VM_LastError(&vm) != PYZ80_VM_E_ADAPTER) return 2;
    mode = 2u;
    if (reset(&vm, &image, &adapter, &arena, &limits) != PYZ80_VM_IDLE ||
        PyZ80VM_Start(&vm, 0u) != PYZ80_VM_RUNNING ||
        PyZ80VM_Run(&vm, 1000u, &result) != PYZ80_VM_ERROR ||
        PyZ80VM_LastError(&vm) != PYZ80_VM_E_ADAPTER) return 3;
    puts("PZVM_DISPATCH_OK"); return 0;
}}
'''
            (directory / "check.c").write_text(harness, encoding="utf-8")
            compiled = subprocess.run(
                [str(TCC), "-std=c11", "-Wall", "-Werror",
                 "pyz80_whole_program_vm.c", "check.c", "-o", "check.exe"],
                cwd=directory, check=False, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding="utf-8", errors="replace", timeout=120)
            self.assertEqual(compiled.returncode, 0, compiled.stdout)
            executed = subprocess.run(
                [str(directory / "check.exe")], cwd=directory, check=False,
                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding="utf-8", errors="replace", timeout=120)
            self.assertEqual(executed.returncode, 0, executed.stdout)
            self.assertIn("PZVM_DISPATCH_OK", executed.stdout)

    @unittest.skipUnless(TCC is not None, "TCC host compiler unavailable")
    def test_c_runtime_executes_guarded_bound_callback_dispatch(self) -> None:
        assert TCC is not None
        graph, lowering, call_abi = finite_bound_callback_abi_graph()
        artifact = build_whole_program_vm(
            graph, active_call_site_lowering=lowering,
            whole_program_vm_call_abi=call_abi)
        adapter_ids = {row["op"]: row["adapter_id"]
                       for row in artifact.adapter_table}
        for required in (
                "load-name", "require-callable",
                "resolve-finite-callable-identity",
                "extract-finite-bound-callable-receiver"):
            self.assertIn(required, adapter_ids)
        with tempfile.TemporaryDirectory(
                prefix="pyz80-bound-dispatch-vm-host-") as tmp:
            directory = Path(tmp)
            shutil.copy2(RUNTIME_C, directory / RUNTIME_C.name)
            shutil.copy2(RUNTIME_H, directory / RUNTIME_H.name)
            image = ",".join(
                f"0x{byte:02X}" for byte in artifact.target_bytecode)
            proof_hash = ",".join(
                f"0x{byte:02X}" for byte in bytes.fromhex(
                    artifact.semantic_sha256))
            harness = f'''#include <stdint.h>
#include <stdio.h>
#include "pyz80_whole_program_vm.h"
static const uint8_t image_bytes[] = {{{image}}};
static const uint8_t proof_sha256[32] = {{{proof_hash}}};
typedef union AlignedArena {{ uint32_t align; uint8_t bytes[8192]; }} AlignedArena;
static uint8_t mode;
static uint8_t loaded;
static uint8_t guards;
static uint8_t receivers;
static uint8_t invoke(void *context, struct PyZ80VM *vm, uint16_t op,
                      uint16_t destination, const PyZ80VMValue *arguments,
                      uint8_t count, uint32_t raw, PyZ80VMValue *result) {{
    (void)context; (void)vm; (void)destination; (void)raw;
    result->reserved = 0u; result->symbol = PYZ80_VM_NO_SYMBOL;
    if (op == {adapter_ids['load-name']}u) {{
        if (count != 1u) return 0u;
        result->kind = PYZ80_VM_VALUE_OPAQUE;
        result->payload = loaded++;
        return 1u;
    }}
    if (op == {adapter_ids['require-callable']}u) {{
        if (count != 1u || arguments[0].kind != PYZ80_VM_VALUE_OPAQUE)
            return 0u;
        *result = arguments[0];
        return 1u;
    }}
    if (op == {adapter_ids['resolve-finite-callable-identity']}u) {{
        if (count != 1u || arguments[0].kind != PYZ80_VM_VALUE_OPAQUE)
            return 0u;
        ++guards; result->kind = PYZ80_VM_VALUE_I32;
        result->payload = arguments[0].payload;
        return 1u;
    }}
    if (op == {adapter_ids['extract-finite-bound-callable-receiver']}u) {{
        if (count != 2u || arguments[0].kind != PYZ80_VM_VALUE_OPAQUE ||
            arguments[1].kind != PYZ80_VM_VALUE_I32 ||
            arguments[0].payload != arguments[1].payload) return 0u;
        ++receivers;
        result->kind = mode ? PYZ80_VM_VALUE_I32 : PYZ80_VM_VALUE_OPAQUE;
        result->payload = 100u + arguments[1].payload;
        return 1u;
    }}
    return 0u;
}}
static uint8_t reset(PyZ80VM *vm, PyZ80VMImage *image,
                     PyZ80VMAdapter *adapter, AlignedArena *arena,
                     PyZ80VMLimits *limits) {{
    loaded = 0u; guards = 0u; receivers = 0u;
    return PyZ80VM_Init(vm, image, adapter, arena->bytes,
                        sizeof(arena->bytes), limits);
}}
int main(void) {{
    PyZ80VM vm; PyZ80VMLimits limits = {{8, 0, 32, 8}};
    PyZ80VMMemoryImage memory = {{image_bytes, sizeof(image_bytes)}};
    PyZ80VMImage image = {{PyZ80VM_MemoryRead, &memory, sizeof(image_bytes),
                           proof_sha256}};
    PyZ80VMAdapter adapter = {{invoke, 0, 0}}; AlignedArena arena;
    PyZ80VMValue result;
    mode = 0u;
    if (reset(&vm, &image, &adapter, &arena, &limits) != PYZ80_VM_IDLE ||
        PyZ80VM_Start(&vm, 0u) != PYZ80_VM_RUNNING ||
        PyZ80VM_Run(&vm, 1000u, &result) != PYZ80_VM_RETURNED ||
        result.kind != PYZ80_VM_VALUE_I32 || result.payload != 18u ||
        guards != 2u || receivers != 2u) return 1;
    mode = 1u;
    if (reset(&vm, &image, &adapter, &arena, &limits) != PYZ80_VM_IDLE ||
        PyZ80VM_Start(&vm, 0u) != PYZ80_VM_RUNNING ||
        PyZ80VM_Run(&vm, 1000u, &result) != PYZ80_VM_ERROR ||
        PyZ80VM_LastError(&vm) != PYZ80_VM_E_ADAPTER ||
        guards != 1u || receivers != 1u) return 2;
    puts("PZVM_BOUND_DISPATCH_OK"); return 0;
}}
'''
            (directory / "check.c").write_text(harness, encoding="utf-8")
            compiled = subprocess.run(
                [str(TCC), "-std=c11", "-Wall", "-Werror",
                 "pyz80_whole_program_vm.c", "check.c", "-o", "check.exe"],
                cwd=directory, check=False, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding="utf-8", errors="replace", timeout=120)
            self.assertEqual(compiled.returncode, 0, compiled.stdout)
            executed = subprocess.run(
                [str(directory / "check.exe")], cwd=directory, check=False,
                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding="utf-8", errors="replace", timeout=120)
            self.assertEqual(executed.returncode, 0, executed.stdout)
            self.assertIn("PZVM_BOUND_DISPATCH_OK", executed.stdout)

    @unittest.skipUnless(TCC is not None, "TCC host compiler unavailable")
    def test_c_runtime_executes_guarded_lexical_dispatch(self) -> None:
        assert TCC is not None
        graph, lowering, call_abi = guarded_lexical_dispatch_abi_graph()
        artifact = build_whole_program_vm(
            graph, active_call_site_lowering=lowering,
            whole_program_vm_call_abi=call_abi)
        adapter_ids = {row["op"]: row["adapter_id"]
                       for row in artifact.adapter_table}
        for required in (
                "load-name", "require-callable",
                "resolve-finite-callable-identity", "python-call"):
            self.assertIn(required, adapter_ids)
        with tempfile.TemporaryDirectory(
                prefix="pyz80-lexical-dispatch-vm-host-") as tmp:
            directory = Path(tmp)
            shutil.copy2(RUNTIME_C, directory / RUNTIME_C.name)
            shutil.copy2(RUNTIME_H, directory / RUNTIME_H.name)
            image = ",".join(
                f"0x{byte:02X}" for byte in artifact.target_bytecode)
            proof_hash = ",".join(
                f"0x{byte:02X}" for byte in bytes.fromhex(
                    artifact.semantic_sha256))
            harness = f'''#include <stdint.h>
#include <stdio.h>
#include "pyz80_whole_program_vm.h"
static const uint8_t image_bytes[] = {{{image}}};
static const uint8_t proof_sha256[32] = {{{proof_hash}}};
typedef union AlignedArena {{ uint32_t align; uint8_t bytes[8192]; }} AlignedArena;
static uint8_t loaded;
static uint8_t guards;
static uint8_t invoke(void *context, struct PyZ80VM *vm, uint16_t op,
                      uint16_t destination, const PyZ80VMValue *arguments,
                      uint8_t count, uint32_t raw, PyZ80VMValue *result) {{
    (void)context; (void)vm; (void)destination; (void)raw;
    result->reserved = 0u; result->symbol = PYZ80_VM_NO_SYMBOL;
    if (op == {adapter_ids['load-name']}u) {{
        if (count != 1u) return 0u;
        result->kind = PYZ80_VM_VALUE_OPAQUE;
        result->payload = loaded++;
        return 1u;
    }}
    if (op == {adapter_ids['require-callable']}u) {{
        if (count != 1u || arguments[0].kind != PYZ80_VM_VALUE_OPAQUE)
            return 0u;
        *result = arguments[0];
        return 1u;
    }}
    if (op == {adapter_ids['resolve-finite-callable-identity']}u) {{
        if (count != 1u || arguments[0].kind != PYZ80_VM_VALUE_OPAQUE)
            return 0u;
        ++guards; result->kind = PYZ80_VM_VALUE_I32;
        result->payload = arguments[0].payload;
        return 1u;
    }}
    if (op == {adapter_ids['python-call']}u) {{
        result->kind = PYZ80_VM_VALUE_NONE; result->payload = 0u;
        return count == 1u;
    }}
    return 0u;
}}
static uint8_t reset(PyZ80VM *vm, PyZ80VMImage *image,
                     PyZ80VMAdapter *adapter, AlignedArena *arena,
                     PyZ80VMLimits *limits) {{
    loaded = 0u; guards = 0u;
    return PyZ80VM_Init(vm, image, adapter, arena->bytes,
                        sizeof(arena->bytes), limits);
}}
int main(void) {{
    PyZ80VM vm; PyZ80VMLimits limits = {{8, 0, 32, 8}};
    PyZ80VMMemoryImage memory = {{image_bytes, sizeof(image_bytes)}};
    PyZ80VMImage image = {{PyZ80VM_MemoryRead, &memory, sizeof(image_bytes),
                           proof_sha256}};
    PyZ80VMAdapter adapter = {{invoke, 0, 0}}; AlignedArena arena;
    PyZ80VMValue result;
    PyZ80VMValue captured = {{PYZ80_VM_VALUE_I32, 0u,
                              PYZ80_VM_NO_SYMBOL, 100u}};
    PyZ80VMValue target_args[2] = {{
        {{PYZ80_VM_VALUE_I32, 0u, PYZ80_VM_NO_SYMBOL, 7u}},
        {{PYZ80_VM_VALUE_I32, 0u, PYZ80_VM_NO_SYMBOL, 2u}}
    }};
    if (reset(&vm, &image, &adapter, &arena, &limits) != PYZ80_VM_IDLE ||
        PyZ80VM_StartArgs(&vm, 0u, &captured, 1u) != PYZ80_VM_RUNNING ||
        PyZ80VM_Run(&vm, 1000u, &result) != PYZ80_VM_RETURNED ||
        result.kind != PYZ80_VM_VALUE_I32 || result.payload != 18u ||
        guards != 2u) return 1;
    if (reset(&vm, &image, &adapter, &arena, &limits) != PYZ80_VM_IDLE ||
        PyZ80VM_StartArgs(&vm, 1u, target_args, 2u) != PYZ80_VM_ERROR ||
        PyZ80VM_LastError(&vm) != PYZ80_VM_E_ARGUMENT) return 2;
    puts("PZVM_LEXICAL_DISPATCH_OK"); return 0;
}}
'''
            (directory / "check.c").write_text(harness, encoding="utf-8")
            compiled = subprocess.run(
                [str(TCC), "-std=c11", "-Wall", "-Werror",
                 "pyz80_whole_program_vm.c", "check.c", "-o", "check.exe"],
                cwd=directory, check=False, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding="utf-8", errors="replace", timeout=120)
            self.assertEqual(compiled.returncode, 0, compiled.stdout)
            executed = subprocess.run(
                [str(directory / "check.exe")], cwd=directory, check=False,
                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding="utf-8", errors="replace", timeout=120)
            self.assertEqual(executed.returncode, 0, executed.stdout)
            self.assertIn("PZVM_LEXICAL_DISPATCH_OK", executed.stdout)

    @unittest.skipUnless(TCC is not None, "TCC host compiler unavailable")
    def test_c_runtime_executes_generated_dataclass_protocol(self) -> None:
        assert TCC is not None
        image_bytes, decoded, adapter_id = generated_dataclass_compact_fixture(
            self.artifact.document)
        image = ",".join(f"0x{byte:02X}" for byte in image_bytes)
        proof_hash = ",".join(
            f"0x{byte:02X}" for byte in bytes.fromhex(
                decoded["proof_document_semantic_sha256"]))
        with tempfile.TemporaryDirectory(prefix="pyz80-dataclass-vm-host-") as tmp:
            directory = Path(tmp)
            shutil.copy2(RUNTIME_C, directory / RUNTIME_C.name)
            shutil.copy2(RUNTIME_H, directory / RUNTIME_H.name)
            harness = f'''#include <stdint.h>
#include <stdio.h>
#include "pyz80_whole_program_vm.h"
static const uint8_t image_bytes[] = {{{image}}};
static const uint8_t proof_sha256[32] = {{{proof_hash}}};
typedef union AlignedArena {{ uint32_t align; uint8_t bytes[8192]; }} AlignedArena;
static uint8_t wrong_result;
static uint8_t calls;
static uint8_t invoke(void *context, struct PyZ80VM *vm, uint16_t op,
                      uint16_t destination, const PyZ80VMValue *arguments,
                      uint8_t count, uint32_t raw, PyZ80VMValue *result) {{
    (void)context; (void)vm; (void)destination; (void)raw;
    if (op != {adapter_id}u || count != 3u ||
        arguments[0].kind != PYZ80_VM_VALUE_SERIALIZED ||
        arguments[1].kind != PYZ80_VM_VALUE_I32 ||
        arguments[1].payload != 17u ||
        arguments[2].kind != PYZ80_VM_VALUE_I32 ||
        arguments[2].payload != 29u) return 0u;
    ++calls; result->reserved = 0u; result->symbol = PYZ80_VM_NO_SYMBOL;
    result->kind = wrong_result ? PYZ80_VM_VALUE_I32 : PYZ80_VM_VALUE_NONE;
    result->payload = wrong_result ? 1u : 0u; return 1u;
}}
static uint8_t reset(PyZ80VM *vm, PyZ80VMImage *image,
                     PyZ80VMAdapter *adapter, AlignedArena *arena,
                     PyZ80VMLimits *limits) {{
    calls = 0u;
    return PyZ80VM_Init(vm, image, adapter, arena->bytes,
                        sizeof(arena->bytes), limits);
}}
int main(void) {{
    PyZ80VM vm; PyZ80VMLimits limits = {{4, 0, 32, 8}};
    PyZ80VMMemoryImage memory = {{image_bytes, sizeof(image_bytes)}};
    PyZ80VMImage image = {{PyZ80VM_MemoryRead, &memory, sizeof(image_bytes),
                           proof_sha256}};
    PyZ80VMAdapter adapter = {{invoke, 0, 0}}; AlignedArena arena;
    PyZ80VMValue result;
    wrong_result = 0u;
    if (reset(&vm, &image, &adapter, &arena, &limits) != PYZ80_VM_IDLE ||
        PyZ80VM_Start(&vm, 0u) != PYZ80_VM_RUNNING ||
        PyZ80VM_Run(&vm, 100u, &result) != PYZ80_VM_RETURNED ||
        result.kind != PYZ80_VM_VALUE_SERIALIZED || calls != 1u) return 1;
    wrong_result = 1u;
    if (reset(&vm, &image, &adapter, &arena, &limits) != PYZ80_VM_IDLE ||
        PyZ80VM_Start(&vm, 0u) != PYZ80_VM_RUNNING ||
        PyZ80VM_Run(&vm, 100u, &result) != PYZ80_VM_ERROR ||
        PyZ80VM_LastError(&vm) != PYZ80_VM_E_ADAPTER || calls != 1u) return 2;
    puts("PZVM_DATACLASS_OK"); return 0;
}}
'''
            (directory / "check.c").write_text(harness, encoding="utf-8")
            compiled = subprocess.run(
                [str(TCC), "-std=c11", "-Wall", "-Werror",
                 "pyz80_whole_program_vm.c", "check.c", "-o", "check.exe"],
                cwd=directory, check=False, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding="utf-8", errors="replace", timeout=120)
            self.assertEqual(compiled.returncode, 0, compiled.stdout)
            executed = subprocess.run(
                [str(directory / "check.exe")], cwd=directory, check=False,
                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding="utf-8", errors="replace", timeout=120)
            self.assertEqual(executed.returncode, 0, executed.stdout)
            self.assertIn("PZVM_DATACLASS_OK", executed.stdout)

    @unittest.skipUnless(SDCC is not None, "pinned SDCC unavailable")
    def test_c_runtime_compiles_with_pinned_sdcc(self) -> None:
        assert SDCC is not None
        with tempfile.TemporaryDirectory(prefix="pyz80-whole-vm-z80-") as tmp:
            directory = Path(tmp)
            shutil.copy2(RUNTIME_C, directory / RUNTIME_C.name)
            shutil.copy2(RUNTIME_H, directory / RUNTIME_H.name)
            environment = os.environ.copy()
            environment["PATH"] = str(SDCC.parent) + os.pathsep + environment.get("PATH", "")
            command = [str(SDCC), "-mz80", "--std-c11", "--sdcccall", "1",
                       "--fno-omit-frame-pointer", "--stack-auto",
                       "--opt-code-speed", "--no-c-code-in-asm", "-c",
                       RUNTIME_C.name]
            completed = subprocess.run(
                command, cwd=directory, check=False, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding="utf-8", errors="replace", timeout=240,
                env=environment)
            self.assertEqual(completed.returncode, 0, completed.stdout)
            rel = (directory / RUNTIME_C.with_suffix(".rel").name).read_text(
                encoding="latin1")
            self.assertIn("A _CODE size ", rel)
            self.assertIn("A _DATA size 0 ", rel)


if __name__ == "__main__":
    unittest.main()
