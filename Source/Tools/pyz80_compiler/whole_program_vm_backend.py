"""Bankable executable bytecode for the active-Python whole-program CFG.

This module is deliberately target neutral.  It serialises every callable in
``call_graph.proven_reachable_callable_ids`` plus an explicitly separate set of
runtime-identity-guarded candidates.  Guarded candidates never become static
reachability edges.  Every selected CFG instruction, terminator and expression
program remains in source order.  The matching runtime in
``Source/C/python_vm`` reads the image through a 32-bit bank reader; it never
assumes that the image is resident in Z80 near memory.

The small set of ``vm-*`` operations is executable without a Python object
runtime and is used by the closure oracle.  Every real Python protocol
operation is delivered, in order, to a fail-closed adapter callback.  Thus an
encoded image is useful compiler output, but is not declared live merely
because it can be encoded.
"""

from __future__ import annotations

import ast
import copy
import dataclasses
import hashlib
import json
import math
import struct
import zlib
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from .cfg_ssa import CFGSSAError, DominatingDefinitions
from .phi_lowering import PhiLoweringError, lower_phi_units

from .active_call_site_lowering import (
    ACTIVE_CALL_SITE_LOWERING_FORMAT,
    ACTIVE_CALL_SITE_LOWERING_STATUS,
)
from .whole_program_vm_call_abi import (
    WHOLE_PROGRAM_VM_CALL_ABI_FORMAT,
    WHOLE_PROGRAM_VM_CALL_ABI_STATUS,
)


WHOLE_PROGRAM_VM_FORMAT = "pyz80.whole-program-vm.v1"
COMPACT_TARGET_VM_FORMAT = "pyz80.compact-target-vm.v1"
WHOLE_PROGRAM_VM_STATUS_FORMAT = "pyz80.whole-program-vm-status.v1"
BYTECODE_MAGIC = b"PZVM"
BYTECODE_VERSION = 1
TARGET_BYTECODE_MAGIC = b"PZVT"
TARGET_BYTECODE_VERSION = 1
RUNTIME_SOURCE_PATHS = (
    "Source/C/python_vm/pyz80_whole_program_vm.h",
    "Source/C/python_vm/pyz80_whole_program_vm.c",
    "Source/C/python_vm/pyz80_target_object_runtime.h",
    "Source/C/python_vm/pyz80_target_object_runtime.c",
    "Source/C/python_vm/pyz80_target_deque.h",
    "Source/C/python_vm/pyz80_target_deque.c",
    "Source/C/python_vm/pyz80_target_buffers.h",
    "Source/C/python_vm/pyz80_target_buffers.c",
    "Source/C/python_vm/pyz80_target_scope_runtime.h",
    "Source/C/python_vm/pyz80_target_scope_runtime.c",
    "Source/C/python_vm/pyz80_target_gc.h",
    "Source/C/python_vm/pyz80_target_gc.c",
    "Source/C/python_vm/pyz80_target_builtins.h",
    "Source/C/python_vm/pyz80_target_builtins.c",
    "Source/C/python_vm/pyz80_target_call_binding.h",
    "Source/C/python_vm/pyz80_target_call_binding.c",
)

_HEADER = struct.Struct("<4sBBHII32sHHHHIIIIIII")
_TARGET_HEADER = struct.Struct("<4sBBHII32sHHHHIIIIII")
_FUNCTION = struct.Struct("<HHHHII")
_UNIT = struct.Struct("<BBHHHIIIHHII")
_BLOCK = struct.Struct("<BIHHHI")
_INSTRUCTION = struct.Struct("<BIBHHHIIIII")
_TERMINATOR = struct.Struct("<BIBHIHI")

_BLOCK_TAG = 0xB0
_INSTRUCTION_TAG = 0xC0
_TERMINATOR_TAG = 0xD0

_NO_SYMBOL = 0xFFFF
_NO_PC = 0xFFFFFFFF

_UNIT_FUNCTION = 1
_UNIT_EXPRESSION = 2

_OP_ADAPTER = 0
_OP_CONSTANT = 1
_OP_LOAD_NAME = 2
_OP_STORE_NAME = 3
_OP_BINARY_I32 = 4
_OP_CALL = 5
_OP_EXECUTE_EXPRESSION = 6

_TERM_ADAPTER = 0
_TERM_JUMP = 1
_TERM_BRANCH = 2
_TERM_RETURN = 3
_TERM_YIELD = 4

_CORE_OPS = {
    "constant": _OP_CONSTANT,
    "load-name": _OP_LOAD_NAME,
    "store-name": _OP_STORE_NAME,
    "vm-binary-i32": _OP_BINARY_I32,
    "vm-call": _OP_CALL,
    "execute-expression-cfg": _OP_EXECUTE_EXPRESSION,
}
_CORE_TERMINATORS = {
    "jump": _TERM_JUMP,
    "branch-truth": _TERM_BRANCH,
    "return": _TERM_RETURN,
    "return-expression": _TERM_RETURN,
    "yield": _TERM_YIELD,
    "yield-value": _TERM_YIELD,
}


class WholeProgramVMError(ValueError):
    """A fail-closed compiler/image/oracle diagnostic."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


@dataclasses.dataclass(frozen=True)
class WholeProgramVMArtifact:
    proof_bytecode: bytes
    target_bytecode: bytes
    document: dict[str, Any]
    compact_document: dict[str, Any]
    adapter_table: tuple[dict[str, Any], ...]
    semantic_sha256: str
    proof_bytecode_sha256: str
    target_bytecode_sha256: str
    coverage: dict[str, int]
    target_coverage: dict[str, Any]
    live: bool
    live_blockers: tuple[dict[str, str], ...]

    @property
    def bytecode(self) -> bytes:
        """Executable target image; the lossless host proof is separate."""
        return self.target_bytecode

    @property
    def bytecode_sha256(self) -> str:
        return self.target_bytecode_sha256

    def report(self) -> dict[str, Any]:
        return {
            "format": WHOLE_PROGRAM_VM_FORMAT,
            "semantic_sha256": self.semantic_sha256,
            "proof_bytecode_sha256": self.proof_bytecode_sha256,
            "proof_bytecode_bytes": len(self.proof_bytecode),
            "target_bytecode_sha256": self.target_bytecode_sha256,
            "target_bytecode_bytes": len(self.target_bytecode),
            "proof_coverage": dict(self.coverage),
            "target_coverage": dict(self.target_coverage),
            "live": self.live,
            "live_blockers": [dict(item) for item in self.live_blockers],
        }


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _require_dict(value: object, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise WholeProgramVMError("PZWV001", f"{where} is not an object")
    return value


def _require_list(value: object, where: str) -> list[Any]:
    if not isinstance(value, list):
        raise WholeProgramVMError("PZWV002", f"{where} is not a list")
    return value


def _require_string(value: object, where: str) -> str:
    if not isinstance(value, str) or not value:
        raise WholeProgramVMError("PZWV003", f"{where} is not a non-empty string")
    return value


def _validated_semantic(value: dict[str, Any], where: str) -> None:
    expected = value.get("semantic_sha256")
    if not isinstance(expected, str) or len(expected) != 64:
        raise WholeProgramVMError("PZWV004", f"{where} has no semantic hash")
    payload = {key: item for key, item in value.items()
               if key != "semantic_sha256"}
    actual = _sha256_json(payload)
    if actual != expected:
        raise WholeProgramVMError(
            "PZWV005", f"{where} semantic hash mismatch: {expected} != {actual}")


def _resolution_classification(resolution: Mapping[str, Any]) -> str:
    targets = resolution.get("targets")
    if not isinstance(targets, list):
        raise WholeProgramVMError("PZWV263", "graph resolution targets malformed")
    kind = str(resolution.get("kind"))
    if (kind == "exact-generated-dataclass-init" and
            resolution.get("proven") is True):
        return "proven-core-generated-dataclass-init"
    if resolution.get("proven") is True and len(targets) == 1:
        return "proven-single-internal"
    if kind == "finite-dynamic-dispatch":
        return "finite-non-proven"
    if kind == "host-boundary":
        return "host-boundary"
    if kind.startswith("unresolved-"):
        return "unresolved"
    return "invalid-proven-target-arity"


def _graph_site_span(site: Mapping[str, Any]) -> dict[str, int]:
    result: dict[str, int] = {}
    for field in ("line", "column", "end_line", "end_column"):
        value = site.get(field)
        if not isinstance(value, int):
            raise WholeProgramVMError(
                "PZWV263", f"graph call-site {field} is malformed")
        result[field] = value
    return result


def _abi_live_blocker_counts(call_abi: Mapping[str, Any]) -> dict[str, int]:
    rows = _require_list(call_abi.get("live_blockers"), "call ABI live blockers")
    counts: dict[str, int] = {}
    for raw_row in rows:
        row = _require_dict(raw_row, "call ABI live blocker")
        code = _require_string(row.get("code"), "call ABI blocker code")
        count = row.get("count")
        if not isinstance(count, int) or count <= 0 or code in counts:
            raise WholeProgramVMError(
                "PZWV263", "call ABI live blocker count is invalid/duplicate")
        counts[code] = count
    return counts


def _validate_call_abi_prerequisites(
        document: Mapping[str, Any], lowering: Mapping[str, Any],
        call_abi: Mapping[str, Any]) -> None:
    """Validate completeness surfaces that a self-hash cannot authenticate."""
    graph_sites = _require_list(
        document.get("reachable_call_sites"), "reachable graph call sites")
    graph_by_id: dict[str, dict[str, Any]] = {}
    for raw_site in graph_sites:
        site = _require_dict(raw_site, "reachable graph call site")
        site_id = _require_string(site.get("call_site_id"), "graph call_site_id")
        if site_id in graph_by_id:
            raise WholeProgramVMError("PZWV263", "duplicate graph call-site ID")
        graph_by_id[site_id] = site

    occurrences = _require_list(
        lowering.get("cfg_occurrences_in_cfg_order"), "lowering occurrences")
    represented_ids: set[str] = set()
    for raw_occurrence in occurrences:
        occurrence = _require_dict(raw_occurrence, "lowering occurrence")
        represented_ids.add(_require_string(
            occurrence.get("call_site_id"), "occurrence call_site_id"))
    expected_unrepresented = [
        site for site in graph_sites
        if str(site.get("call_site_id")) not in represented_ids]
    lowering_unrepresented = _require_list(
        lowering.get("unrepresented_graph_sites_in_source_order"),
        "lowering unrepresented graph sites")
    expected_by_id = {
        str(site["call_site_id"]): site for site in expected_unrepresented}
    expected_ids = set(expected_by_id)
    actual_ids: list[str] = []
    for raw_row in lowering_unrepresented:
        row = _require_dict(raw_row, "lowering unrepresented graph site")
        site_id = _require_string(
            row.get("call_site_id"), "unrepresented call_site_id")
        actual_ids.append(site_id)
        graph_site = expected_by_id.get(site_id)
        if graph_site is None:
            raise WholeProgramVMError(
                "PZWV263", f"unexpected unrepresented graph site: {site_id}")
        resolution = _require_dict(
            graph_site.get("resolution"), "unrepresented graph resolution")
        span = _require_dict(row.get("span"), "unrepresented graph span")
        if (site_id != graph_site.get("call_site_id") or
                row.get("caller") != graph_site.get("caller") or
                any(span.get(field) != value for field, value in
                    _graph_site_span(graph_site).items()) or
                row.get("resolution_kind") != resolution.get("kind") or
                row.get("proven") is not (resolution.get("proven") is True) or
                row.get("classification") !=
                _resolution_classification(resolution) or
                row.get("targets") != resolution.get("targets")):
            raise WholeProgramVMError(
                "PZWV263", f"unrepresented graph binding mismatch: {site_id}")
    if set(actual_ids) != expected_ids or len(lowering_unrepresented) != len(
            expected_unrepresented):
        raise WholeProgramVMError(
            "PZWV263", "lowering unrepresented graph-site inventory differs")

    prerequisite = _require_dict(
        call_abi.get("call_site_lowering_prerequisites"),
        "call ABI lowering prerequisites")
    classifications = dict(sorted(Counter(
        _resolution_classification(_require_dict(
            site.get("resolution"), "unrepresented graph resolution"))
        for site in expected_unrepresented).items()))
    numeric_ids = [
        _require_dict(row, "unrepresented graph site").get(
            "numeric_call_site_id")
        for row in lowering_unrepresented]
    if (any(not isinstance(value, int) for value in numeric_ids) or
            prerequisite.get("unrepresented_graph_call_site_count") !=
            len(expected_unrepresented) or
            prerequisite.get(
                "unrepresented_numeric_call_site_ids_in_source_order") !=
            numeric_ids or
            prerequisite.get("unrepresented_call_site_ids_in_source_order") !=
            actual_ids or
            prerequisite.get("unrepresented_classification_counts") !=
            classifications or
            prerequisite.get("unrepresented_graph_sites_in_source_order") !=
            lowering_unrepresented):
        raise WholeProgramVMError(
            "PZWV263", "call ABI unrepresented prerequisite binding differs")

    mapping = _require_dict(lowering.get("mapping"), "lowering mapping")
    census = _require_dict(call_abi.get("census"), "call ABI census")
    represented_count = len(represented_ids)
    if (mapping.get("reachable_graph_call_site_count") != len(graph_sites) or
            mapping.get("represented_graph_call_site_count") !=
            represented_count or
            mapping.get("unrepresented_graph_call_site_count") !=
            len(expected_unrepresented) or
            mapping.get("cfg_python_call_occurrence_count") !=
            len(occurrences) or
            census.get("represented_call_site_count") != represented_count or
            census.get("unrepresented_graph_call_site_count") !=
            len(expected_unrepresented) or
            census.get("unrepresented_graph_call_site_classification_counts") !=
            classifications or
            census.get("call_occurrence_descriptor_count") != len(occurrences)):
        raise WholeProgramVMError(
            "PZWV263", "call ABI/lowering prerequisite census differs")
    expected_prerequisite_blockers = ({
        "PZCABI215": len(expected_unrepresented),
    } if expected_unrepresented else {})
    if census.get("prerequisite_blocker_counts") != \
            expected_prerequisite_blockers:
        raise WholeProgramVMError(
            "PZWV263", "call ABI prerequisite blocker census differs")

    proof = _require_dict(call_abi.get("proof"), "call ABI proof")
    for key in (
            "active_call_graph_and_lowering_validated_in_memory",
            "one_numeric_descriptor_per_represented_cfg_occurrence",
            "callable_ssa_chain_is_traced_without_receiver_invention",
            "finite_dispatch_tables_remain_non_proven",
            "constructor_sequence_is_allocate_bind_init_return",
            "argument_evaluation_order_is_not_reordered",
            "parameter_destination_map_is_per_occurrence_and_target",
            "nested_lexical_owner_is_explicit",
            "unrepresented_graph_sites_are_explicit_lowering_prerequisites",
            "backend_must_address_numeric_abi_descriptor_id_and_cfg_occurrence",
            "numeric_call_site_id_alone_is_not_backend_dispatch_identity"):
        if proof.get(key) is not True:
            raise WholeProgramVMError(
                "PZWV263", f"call ABI proof is absent/false: {key}")
    if proof.get("current_vm_backend_consumes_call_abi") is not False:
        raise WholeProgramVMError(
            "PZWV263", "input ABI makes an invented backend-consumer claim")

    descriptors = _require_list(
        call_abi.get("occurrence_abi_descriptors_in_cfg_order"),
        "call ABI occurrence descriptors")
    if len(descriptors) != len(occurrences):
        raise WholeProgramVMError(
            "PZWV263", "call ABI descriptor/prerequisite count differs")
    super_count = 0
    blocker_214_count = 0
    for raw_descriptor in descriptors:
        descriptor = _require_dict(raw_descriptor, "call ABI descriptor")
        blocker_codes = _require_list(
            descriptor.get("blocker_codes"), "call ABI descriptor blockers")
        is_super = descriptor.get("binding_mode") == "super"
        has_214 = "PZCABI214" in blocker_codes
        super_count += int(is_super)
        blocker_214_count += int(has_214)
        if is_super is not has_214:
            raise WholeProgramVMError(
                "PZWV263", "PZCABI214 does not exactly cover super descriptors")
    blocker_descriptor_counts = _require_dict(
        census.get("blocker_descriptor_counts"),
        "call ABI descriptor blocker census")
    if blocker_descriptor_counts.get("PZCABI214", 0) != super_count or \
            blocker_214_count != super_count:
        raise WholeProgramVMError(
            "PZWV263", "PZCABI214 descriptor census differs")
    live_counts = _abi_live_blocker_counts(call_abi)
    if (live_counts.get("PZCABI213") != 1 or
            live_counts.get("PZCABI214", 0) != super_count or
            live_counts.get("PZCABI215", 0) != len(expected_unrepresented)):
        raise WholeProgramVMError(
            "PZWV263", "call ABI required live blocker census differs")


def _guarded_candidate_rows(
        call_abi: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Select target bodies that are callable only after an identity guard.

    ``PZCABI212`` means that a finite candidate is intentionally absent from
    the source-proven reachable prefix.  A bound method is selected by exact
    runtime callable identity and an exact caller-local SSA receiver.  A
    nested free function additionally records its proven lexical owner; the
    runtime may enter it only when exactly one matching owner frame is active.
    """
    function_rows = _require_list(
        call_abi.get("function_id_table"), "call ABI function table")
    by_numeric: dict[int, dict[str, Any]] = {}
    for raw_row in function_rows:
        row = _require_dict(raw_row, "call ABI function row")
        numeric_id = row.get("numeric_function_id")
        if (not isinstance(numeric_id, int) or numeric_id < 0 or
                numeric_id in by_numeric):
            raise WholeProgramVMError(
                "PZWV271", "call ABI numeric function table is invalid")
        by_numeric[numeric_id] = row

    selected: dict[str, tuple[int, str | None]] = {}
    descriptors = _require_list(
        call_abi.get("occurrence_abi_descriptors_in_cfg_order"),
        "call ABI occurrence descriptors")
    for raw_descriptor in descriptors:
        descriptor = _require_dict(raw_descriptor, "call ABI descriptor")
        binding_mode = descriptor.get("binding_mode")
        if (descriptor.get("classification") != "finite-non-proven" or
                descriptor.get("proven") is not False or
                descriptor.get("resolution_kind") !=
                "finite-dynamic-dispatch" or
                binding_mode not in {"bound-method", "free"} or
                descriptor.get("blocker_codes") != [
                    "PZCABI204", "PZCABI212"]):
            continue
        targets = _require_list(
            descriptor.get("target_descriptors"),
            "guard-only finite target descriptors")
        if not targets:
            continue
        candidates: list[tuple[str, int, str | None]] = []
        for raw_target in targets:
            target = _require_dict(raw_target, "guard-only finite target")
            identifier = target.get("callable_id")
            numeric_id = target.get("numeric_function_id")
            table_row = (by_numeric.get(numeric_id)
                         if isinstance(numeric_id, int) else None)
            lexical_owner = target.get("lexical_owner")
            lexical_owner_id: str | None = None
            lexical_owner_valid = lexical_owner is None
            if isinstance(lexical_owner, Mapping):
                lexical_owner_id = lexical_owner.get("callable_id")
                owner_numeric_id = lexical_owner.get("numeric_function_id")
                owner_row = (by_numeric.get(owner_numeric_id)
                             if isinstance(owner_numeric_id, int) else None)
                lexical_owner_valid = (
                    isinstance(lexical_owner_id, str) and
                    owner_row is not None and
                    owner_row.get("callable_id") == lexical_owner_id and
                    owner_row.get("proven_reachable") is True and
                    lexical_owner.get("current_pzvt_function_id") ==
                    owner_row.get("current_pzvt_function_id") and
                    isinstance(owner_row.get("current_pzvt_function_id"), int))
            if (not isinstance(identifier, str) or not identifier or
                    not isinstance(numeric_id, int) or
                    target.get("current_pzvt_function_id") is not None or
                    target.get("proven_reachable") is not False or
                    target.get("binding_mode") != binding_mode or
                    not lexical_owner_valid or
                    (binding_mode == "bound-method" and
                     lexical_owner_id is not None) or
                    (binding_mode == "free" and
                     lexical_owner_id is None) or
                    target.get("blocker_codes") not in ([], ()) or
                    table_row is None or
                    table_row.get("callable_id") != identifier or
                    table_row.get("proven_reachable") is not False or
                    table_row.get("current_pzvt_function_id") is not None):
                candidates = []
                break
            candidates.append((identifier, numeric_id, lexical_owner_id))
        for identifier, numeric_id, lexical_owner_id in candidates:
            previous = selected.get(identifier)
            value = (numeric_id, lexical_owner_id)
            if previous is not None and previous != value:
                raise WholeProgramVMError(
                    "PZWV271", "guarded callable numeric identity changed")
            selected[identifier] = value
    return [
        {"callable_id": identifier, "numeric_function_id": value[0],
         "lexical_owner_callable_id": value[1]}
        for identifier, value in sorted(
            selected.items(), key=lambda item: (item[1][0], item[0]))
    ]


def _normalise_graph(
        graph: Mapping[str, Any], *,
        guarded_callable_rows: Sequence[Mapping[str, Any]] = (),
        ) -> dict[str, Any]:
    raw_graph = _require_dict(dict(graph), "active call graph")
    try:
        # The analyzer's public result is JSON-shaped semantically, although
        # immutable sequence fields may remain tuples in memory.  Normalize
        # before structural validation so direct analyzer -> backend and
        # saved-report -> backend use exactly the same representation.
        graph = json.loads(_canonical(raw_graph).decode("utf-8"))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise WholeProgramVMError(
            "PZWV050", f"active call graph is not JSON representable: {exc}") from exc
    source_semantic = graph.get("semantic_sha256")
    if not isinstance(source_semantic, str) or len(source_semantic) != 64:
        raise WholeProgramVMError(
            "PZWV050", "active call graph has no semantic hash")
    graph_payload = dict(graph)
    for key in ("semantic_sha256", "status", "live", "live_blockers"):
        graph_payload.pop(key, None)
    actual_graph_semantic = _sha256_json(graph_payload)
    if actual_graph_semantic != source_semantic:
        raise WholeProgramVMError(
            "PZWV051", "active call graph semantic hash mismatch: "
            f"{source_semantic} != {actual_graph_semantic}")
    call_graph = _require_dict(graph.get("call_graph"), "call_graph")
    reachable_raw = _require_list(
        call_graph.get("proven_reachable_callable_ids"),
        "proven_reachable_callable_ids")
    reachable = [_require_string(value, "reachable callable id")
                 for value in reachable_raw]
    if len(set(reachable)) != len(reachable):
        raise WholeProgramVMError("PZWV006", "reachable callable ids are duplicated")

    inventory = _require_dict(graph.get("callable_inventory"),
                              "callable_inventory")
    rows = _require_list(inventory.get("callables"), "callables")
    by_id: dict[str, dict[str, Any]] = {}
    for raw_row in rows:
        row = _require_dict(raw_row, "callable row")
        identifier = _require_string(row.get("callable_id"), "callable_id")
        if identifier in by_id:
            raise WholeProgramVMError("PZWV007", f"duplicate callable {identifier}")
        by_id[identifier] = row

    guarded_rows: list[dict[str, Any]] = []
    guarded_ids: list[str] = []
    guarded_numeric_ids: set[int] = set()
    reachable_set = set(reachable)
    for raw_guarded in guarded_callable_rows:
        guarded = _require_dict(
            copy.deepcopy(dict(raw_guarded)), "guarded callable row")
        identifier = _require_string(
            guarded.get("callable_id"), "guarded callable_id")
        numeric_id = guarded.get("numeric_function_id")
        lexical_owner = guarded.get("lexical_owner_callable_id")
        if (identifier in reachable_set or identifier in guarded_ids or
                not isinstance(numeric_id, int) or numeric_id < 0 or
                numeric_id in guarded_numeric_ids or
                (lexical_owner is not None and
                 lexical_owner not in reachable_set)):
            raise WholeProgramVMError(
                "PZWV271", "guarded callable identity/order is invalid")
        guarded_ids.append(identifier)
        guarded_numeric_ids.add(numeric_id)
        guarded_rows.append({
            "callable_id": identifier,
            "numeric_function_id": numeric_id,
            "pzvt_function_id": len(reachable) + len(guarded_rows),
            "admission": (
                "runtime-identity-and-lexical-owner-guard-only"
                if lexical_owner is not None else
                "runtime-identity-guard-only"),
            "lexical_owner_callable_id": lexical_owner,
            "static_reachability_edge": False,
        })

    definition_ids = [_require_string(value, "definition-only callable id") for value in
                      _require_list(inventory.get("definition_callable_ids", []), "definition callable ids")]
    if len(set(definition_ids)) != len(definition_ids) or set(definition_ids) & set([*reachable, *guarded_ids]):
        raise WholeProgramVMError("PZWV281", "definition-only function identities overlap or duplicate")
    all_function_ids = [*reachable, *guarded_ids, *definition_ids]
    missing = [identifier for identifier in all_function_ids
               if identifier not in by_id]
    if missing:
        raise WholeProgramVMError(
            "PZWV008", f"reachable callables absent from inventory: {missing[:4]}")

    functions: list[dict[str, Any]] = []
    for identifier in all_function_ids:
        row = copy.deepcopy(by_id[identifier])
        cfg = _require_dict(row.get("cfg"), f"{identifier}.cfg")
        _validated_semantic(cfg, f"{identifier}.cfg")
        blocks = _require_list(cfg.get("blocks"), f"{identifier}.blocks")
        programs = _require_list(
            cfg.get("expression_programs"),
            f"{identifier}.expression_programs")
        if not blocks:
            raise WholeProgramVMError("PZWV009", f"{identifier} has no CFG blocks")
        for program in programs:
            program = _require_dict(program, f"{identifier}.expression_program")
            _validated_semantic(program, f"{identifier}.{program.get('program_id')}")
            if not _require_list(program.get("blocks"), "expression blocks"):
                raise WholeProgramVMError(
                    "PZWV010", f"{identifier} has an empty expression program")
        functions.append({"callable_id": identifier, "row": row})

    raw_call_sites = call_graph.get("call_sites", [])
    if not isinstance(raw_call_sites, list):
        raise WholeProgramVMError("PZWV052", "call_graph.call_sites is not a list")
    reachable_call_sites: list[dict[str, Any]] = []
    seen_site_ids: set[str] = set()
    for raw_site in raw_call_sites:
        site = _require_dict(raw_site, "call site")
        if site.get("caller") not in reachable_set:
            continue
        site_id = _require_string(site.get("call_site_id"), "call_site_id")
        if site_id in seen_site_ids:
            raise WholeProgramVMError("PZWV053", f"duplicate reachable call site {site_id}")
        resolution = _require_dict(site.get("resolution"), f"{site_id}.resolution")
        targets = _require_list(resolution.get("targets"), f"{site_id}.targets")
        if any(not isinstance(target, str) for target in targets):
            raise WholeProgramVMError("PZWV054", f"invalid targets for {site_id}")
        for field in ("line", "column", "end_line", "end_column"):
            if not isinstance(site.get(field), int):
                raise WholeProgramVMError(
                    "PZWV055", f"invalid {field} for call site {site_id}")
        seen_site_ids.add(site_id)
        reachable_call_sites.append(copy.deepcopy(site))

    document = {
        "format": WHOLE_PROGRAM_VM_FORMAT,
        "active_call_graph_semantic_sha256": source_semantic,
        "proven_reachable_callable_ids": reachable,
        "guarded_callable_ids": guarded_ids,
        "guarded_callable_table": guarded_rows,
        "function_table_contract": (
            "proven-reachable-prefix-then-runtime-guard-only-candidates"),
        # Host-only proof input for call-site-aware lowering.  PZVT stores only
        # numeric adapter/function IDs; source text/spans remain in PZVM.
        "reachable_call_sites": reachable_call_sites,
        "functions": functions,
    }
    if definition_ids:
        document["definition_callable_ids"] = definition_ids
        document["function_table_contract"] += "-then-source-definitions-not-static-edges"
    # Analyzer reports are JSON documents, but their in-memory construction may
    # retain tuple containers.  PZVM deliberately decodes JSON arrays as lists;
    # normalise once inside the backend so direct analyzer -> backend use has
    # the same lossless contract as loading the signed report from disk.  The
    # caller must not need a private tuple-to-list workaround.
    return json.loads(_canonical(document).decode("utf-8"))


def _collect_strings(value: object, output: set[str]) -> None:
    if isinstance(value, str):
        output.add(value)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _collect_strings(item, output)
    elif isinstance(value, dict):
        for key, item in value.items():
            output.add(str(key))
            _collect_strings(item, output)


class _TypedCodec:
    NONE = 0
    FALSE = 1
    TRUE = 2
    I32 = 3
    I64 = 4
    BIGINT = 5
    F64 = 6
    STRING = 7
    LIST = 8
    MAP = 9
    BYTES = 10

    def __init__(self, strings: Sequence[str]) -> None:
        self.strings = tuple(strings)
        self.by_string = {value: index for index, value in enumerate(strings)}

    def encode(self, value: object) -> bytes:
        if value is None:
            return bytes((self.NONE,))
        if value is False:
            return bytes((self.FALSE,))
        if value is True:
            return bytes((self.TRUE,))
        if isinstance(value, int):
            if -(1 << 31) <= value < (1 << 31):
                return bytes((self.I32,)) + struct.pack("<i", value)
            if -(1 << 63) <= value < (1 << 63):
                return bytes((self.I64,)) + struct.pack("<q", value)
            encoded = str(value).encode("ascii")
            return bytes((self.BIGINT,)) + struct.pack("<I", len(encoded)) + encoded
        if isinstance(value, float):
            if not math.isfinite(value):
                raise WholeProgramVMError("PZWV011", "non-finite float in CFG")
            return bytes((self.F64,)) + struct.pack("<d", value)
        if isinstance(value, str):
            return bytes((self.STRING,)) + struct.pack("<H", self.by_string[value])
        if isinstance(value, bytes):
            return bytes((self.BYTES,)) + struct.pack("<I", len(value)) + value
        if isinstance(value, (list, tuple)):
            return (bytes((self.LIST,)) + struct.pack("<I", len(value)) +
                    b"".join(self.encode(item) for item in value))
        if isinstance(value, dict):
            ordered = sorted(value.items(), key=lambda item: str(item[0]))
            return (bytes((self.MAP,)) + struct.pack("<I", len(ordered)) +
                    b"".join(
                        struct.pack("<H", self.by_string[str(key)]) +
                        self.encode(item) for key, item in ordered))
        raise WholeProgramVMError(
            "PZWV012", f"unsupported CFG value {type(value).__name__}")

    def decode(self, data: bytes, offset: int = 0,
               depth: int = 0) -> tuple[object, int]:
        if depth > 64 or offset >= len(data):
            raise WholeProgramVMError("PZWV013", "malformed typed value")
        tag = data[offset]
        offset += 1
        try:
            if tag == self.NONE:
                return None, offset
            if tag == self.FALSE:
                return False, offset
            if tag == self.TRUE:
                return True, offset
            if tag == self.I32:
                return struct.unpack_from("<i", data, offset)[0], offset + 4
            if tag == self.I64:
                return struct.unpack_from("<q", data, offset)[0], offset + 8
            if tag == self.BIGINT:
                size = struct.unpack_from("<I", data, offset)[0]
                offset += 4
                return int(data[offset:offset + size].decode("ascii")), offset + size
            if tag == self.F64:
                return struct.unpack_from("<d", data, offset)[0], offset + 8
            if tag == self.STRING:
                index = struct.unpack_from("<H", data, offset)[0]
                return self.strings[index], offset + 2
            if tag == self.BYTES:
                size = struct.unpack_from("<I", data, offset)[0]
                offset += 4
                return data[offset:offset + size], offset + size
            if tag == self.LIST:
                count = struct.unpack_from("<I", data, offset)[0]
                offset += 4
                result = []
                for _ in range(count):
                    item, offset = self.decode(data, offset, depth + 1)
                    result.append(item)
                return result, offset
            if tag == self.MAP:
                count = struct.unpack_from("<I", data, offset)[0]
                offset += 4
                result: dict[str, object] = {}
                for _ in range(count):
                    key_index = struct.unpack_from("<H", data, offset)[0]
                    offset += 2
                    item, offset = self.decode(data, offset, depth + 1)
                    result[self.strings[key_index]] = item
                return result, offset
        except (IndexError, struct.error, UnicodeError, ValueError) as exc:
            raise WholeProgramVMError("PZWV013", "malformed typed value") from exc
        raise WholeProgramVMError("PZWV014", f"unknown typed tag {tag}")


def _sid(mapping: Mapping[str, int], value: object) -> int:
    return _NO_SYMBOL if value is None else mapping[str(value)]


def _parameter_count(cfg: dict[str, Any]) -> int:
    signature = cfg.get("signature")
    if not isinstance(signature, dict):
        return 0
    parameters = signature.get("parameters", [])
    return len(parameters) if isinstance(parameters, list) else 0


def _unit_specs(document: dict[str, Any]) -> tuple[list[dict[str, Any]],
                                                      list[dict[str, Any]]]:
    functions: list[dict[str, Any]] = []
    units: list[dict[str, Any]] = []
    guarded_lexical_owners = {
        str(row.get("callable_id")): row.get("lexical_owner_callable_id")
        for row in document.get("guarded_callable_table", ())
        if isinstance(row, Mapping)
    }
    for function_index, item in enumerate(document["functions"]):
        row = item["row"]
        cfg = row["cfg"]
        function_unit = len(units)
        functions.append({
            "callable_id": item["callable_id"],
            "unit": function_unit,
            "parameter_count": _parameter_count(cfg),
            "meta": {key: copy.deepcopy(value) for key, value in row.items()
                     if key != "cfg"},
        })
        units.append({
            "kind": _UNIT_FUNCTION,
            "owner": function_index,
            "name": item["callable_id"],
            "result": None,
            "entry": cfg["entry"],
            "blocks": cfg["blocks"],
            "lexical_parent_callable_id": guarded_lexical_owners.get(
                item["callable_id"], row.get("lexical_parent_id")),
            "meta": {key: copy.deepcopy(value) for key, value in cfg.items()
                     if key not in ("blocks", "expression_programs")},
        })
        for program in cfg["expression_programs"]:
            units.append({
                "kind": _UNIT_EXPRESSION,
                "owner": function_index,
                "name": program["program_id"],
                "result": program["result"],
                "entry": program["entry"],
                "blocks": program["blocks"],
                "meta": {key: copy.deepcopy(value)
                         for key, value in program.items() if key != "blocks"},
            })
    return functions, units


def _object_store_payload(report: Mapping[str, Any]) -> dict[str, Any]:
    """Rebuild the signed v2 object-store payload from its public report."""
    source = _require_dict(report.get("source"), "object-store source")
    return {
        "format": report.get("format"),
        "source_path": source.get("path"),
        "source_sha256": source.get("sha256"),
        "hook_semantic": report.get("mutation_hook_semantic_sha256"),
        "fragments": copy.deepcopy(report.get("fragments")),
        "bind_schema_site_ids": copy.deepcopy(
            report.get("bind_schema_site_ids")),
        "coverage": copy.deepcopy(report.get("coverage")),
    }


def _validate_object_store_report(
        active_call_graph: Mapping[str, Any],
        report: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Authenticate an optional exact fragment report against the call graph."""
    if report is None:
        return None
    normal = json.loads(_canonical(dict(report)).decode("utf-8"))
    if normal.get("format") != "pyz80.object-store-module-ir.v2":
        raise WholeProgramVMError("PZWV272", "object-store format changed")
    semantic = normal.get("semantic_sha256")
    if (not isinstance(semantic, str) or len(semantic) != 64 or
            _sha256_json(_object_store_payload(normal)) != semantic):
        raise WholeProgramVMError(
            "PZWV273", "object-store semantic hash mismatch")
    graph_binding = active_call_graph.get("object_store_binding")
    if not isinstance(graph_binding, Mapping):
        raise WholeProgramVMError(
            "PZWV274", "active call graph has no object-store binding")
    if (graph_binding.get("object_store_semantic_sha256") != semantic or
            graph_binding.get("source_sha256") !=
            normal.get("source", {}).get("sha256")):
        raise WholeProgramVMError(
            "PZWV275", "object-store report is stale against call graph")
    fragments = _require_list(normal.get("fragments"),
                              "object-store fragments")
    ids = [row.get("site_id") for row in fragments
           if isinstance(row, Mapping)]
    if (len(ids) != len(fragments) or any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in ids) or len(set(ids)) != len(ids)):
        raise WholeProgramVMError(
            "PZWV276", "object-store fragment IDs are invalid")
    return normal


def _rename_effect_value(value: object, prefix: str) -> object:
    if isinstance(value, str) and value.startswith("%"):
        return prefix + value[1:]
    if isinstance(value, list):
        return [_rename_effect_value(item, prefix) for item in value]
    if isinstance(value, dict):
        return {key: _rename_effect_value(item, prefix)
                for key, item in value.items()}
    return copy.deepcopy(value)


def _expand_object_store_units(
        units: Sequence[dict[str, Any]],
        object_store_report: Mapping[str, Any] | None,
        ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Lower exact store fragments into ordinary PZVT operations.

    The function CFG deliberately carries a hash-bound fragment reference so
    every analysis stage sees the original statement as one effect.  The
    executable target cannot call back into a host-side fragment interpreter,
    however.  Here, after call-ABI paths have been consumed, that reference is
    expanded into the already-certified expression CFG and effect SSA.  This
    keeps receiver/RHS single evaluation and makes object state persistent in
    the target object provider instead of silently discarding whole updates.
    """
    prepared = copy.deepcopy(list(units))
    if object_store_report is None:
        return prepared, {
            "enabled": False,
            "expanded_fragment_count": 0,
            "added_expression_unit_count": 0,
        }
    fragments = {
        int(row["site_id"]): row
        for row in _require_list(object_store_report.get("fragments"),
                                 "object-store fragments")
    }
    added: list[dict[str, Any]] = []
    expanded_ids: list[int] = []
    for unit in prepared:
        if unit.get("kind") != _UNIT_FUNCTION:
            continue
        next_sequence = 0
        for block in unit["blocks"]:
            output: list[dict[str, Any]] = []
            for instruction in block["instructions"]:
                if instruction.get("op") != "execute-object-store-fragment":
                    item = copy.deepcopy(instruction)
                    item["sequence"] = next_sequence
                    next_sequence += 1
                    output.append(item)
                    continue
                arguments = instruction.get("arguments")
                if (not isinstance(arguments, list) or len(arguments) != 2 or
                        not isinstance(arguments[0], int) or
                        not isinstance(arguments[1], str)):
                    raise WholeProgramVMError(
                        "PZWV277", "malformed object-store fragment reference")
                site_id = arguments[0]
                fragment = fragments.get(site_id)
                if (fragment is None or
                        fragment.get("semantic_sha256") != arguments[1]):
                    raise WholeProgramVMError(
                        "PZWV278", f"object-store fragment {site_id} mismatch")
                prefix = f"%pzstore_{site_id:04d}_"
                expression = _require_dict(
                    fragment.get("expression"), "store expression")
                program_id = _require_string(
                    expression.get("program_id"), "store expression program")
                if any(row.get("name") == program_id for row in prepared + added):
                    raise WholeProgramVMError(
                        "PZWV279", f"duplicate store expression {program_id}")
                added.append({
                    "kind": _UNIT_EXPRESSION,
                    "owner": unit["owner"],
                    "name": program_id,
                    "result": expression.get("result"),
                    "entry": expression.get("entry"),
                    "blocks": copy.deepcopy(expression.get("blocks")),
                    "meta": {key: copy.deepcopy(value)
                             for key, value in expression.items()
                             if key != "blocks"},
                })
                effects = _require_list(fragment.get("instructions"),
                                        "store effect instructions")
                for effect in effects:
                    effect = _require_dict(effect, "store effect instruction")
                    item = copy.deepcopy(effect)
                    if item.get("op") == "eval-receiver":
                        item["op"] = "load-name"
                    item["arguments"] = _rename_effect_value(
                        item.get("arguments", []), prefix)
                    if isinstance(item.get("destination"), str):
                        item["destination"] = _rename_effect_value(
                            item["destination"], prefix)
                    item["sequence"] = next_sequence
                    next_sequence += 1
                    output.append(item)
                expanded_ids.append(site_id)
            block["instructions"] = output
    if len(expanded_ids) != len(set(expanded_ids)):
        raise WholeProgramVMError(
            "PZWV280", "one object-store fragment was expanded twice")
    prepared.extend(added)
    return prepared, {
        "enabled": True,
        "object_store_semantic_sha256":
            object_store_report.get("semantic_sha256"),
        "expanded_fragment_count": len(expanded_ids),
        "expanded_fragment_ids": sorted(expanded_ids),
        "added_expression_unit_count": len(added),
        "opaque_fragment_adapter_count": 0,
        "effect_ssa_namespaced_per_site": True,
    }


def _instruction_bytes(instruction: dict[str, Any], codec: _TypedCodec,
                       strings: Mapping[str, int]) -> bytes:
    op = _require_string(instruction.get("op"), "instruction op")
    arguments = _require_list(instruction.get("arguments"), f"{op}.arguments")
    args = codec.encode(arguments)
    attrs = codec.encode(instruction.get("attributes", {}))
    span = codec.encode(instruction.get("span", {}))
    header_size = _INSTRUCTION.size
    size = header_size + len(args) + len(attrs) + len(span)
    return (_INSTRUCTION.pack(
        _INSTRUCTION_TAG, size, _CORE_OPS.get(op, _OP_ADAPTER),
        strings[op], _sid(strings, instruction.get("destination")),
        _sid(strings, instruction.get("value_kind")),
        int(instruction.get("sequence", 0)), len(args), len(attrs), len(span),
        len(arguments)) + args + attrs + span)


def _terminator_bytes(terminator: dict[str, Any], codec: _TypedCodec,
                      strings: Mapping[str, int], target_pcs: Mapping[str, int]) -> bytes:
    op = _require_string(terminator.get("op"), "terminator op")
    arguments = _require_list(terminator.get("arguments"), f"{op}.arguments")
    targets = _require_list(terminator.get("targets"), f"{op}.targets")
    args = codec.encode(arguments)
    span = codec.encode(terminator.get("span", {}))
    target_bytes = b"".join(
        struct.pack("<HI", strings[_require_string(target, "target")],
                    target_pcs[_require_string(target, "target")])
        for target in targets)
    size = _TERMINATOR.size + len(target_bytes) + len(args) + len(span)
    return (_TERMINATOR.pack(
        _TERMINATOR_TAG, size, _CORE_TERMINATORS.get(op, _TERM_ADAPTER),
        strings[op], len(args), len(targets), len(span)) +
        target_bytes + args + span)


def _block_size(block: dict[str, Any], codec: _TypedCodec,
                strings: Mapping[str, int]) -> int:
    instructions = _require_list(block.get("instructions"), "block.instructions")
    terminator = _require_dict(block.get("terminator"), "block.terminator")
    dummy_targets = {
        _require_string(target, "target"): 0
        for target in _require_list(terminator.get("targets"), "targets")}
    return (_BLOCK.size +
            sum(len(_instruction_bytes(item, codec, strings))
                for item in instructions) +
            len(_terminator_bytes(terminator, codec, strings, dummy_targets)))


def _encode_unit_blocks(unit: dict[str, Any], base: int, codec: _TypedCodec,
                        strings: Mapping[str, int]) -> tuple[bytes, int, int]:
    blocks = [_require_dict(item, "unit block") for item in unit["blocks"]]
    names = [_require_string(block.get("name"), "block name") for block in blocks]
    if len(set(names)) != len(names):
        raise WholeProgramVMError("PZWV015", f"duplicate block in {unit['name']}")
    target_pcs: dict[str, int] = {}
    cursor = base
    for name, block in zip(names, blocks):
        target_pcs[name] = cursor + _BLOCK.size
        cursor += _block_size(block, codec, strings)
    entry = _require_string(unit["entry"], "unit entry")
    if entry not in target_pcs:
        raise WholeProgramVMError("PZWV016", f"unknown entry block {entry}")

    output = bytearray()
    for name, block in zip(names, blocks):
        instructions = _require_list(block.get("instructions"), "instructions")
        exception = block.get("exception_target")
        if exception is not None and exception not in target_pcs:
            raise WholeProgramVMError(
                "PZWV017", f"unknown exception target {exception}")
        block_size = _block_size(block, codec, strings)
        output.extend(_BLOCK.pack(
            _BLOCK_TAG, block_size, strings[name], _sid(strings, exception),
            len(instructions), _NO_PC if exception is None else target_pcs[exception]))
        for instruction in instructions:
            output.extend(_instruction_bytes(
                _require_dict(instruction, "instruction"), codec, strings))
        output.extend(_terminator_bytes(
            _require_dict(block.get("terminator"), "terminator"),
            codec, strings, target_pcs))
    return bytes(output), target_pcs[entry], len(target_pcs)


def _encode(document: dict[str, Any]) -> tuple[bytes, dict[str, int]]:
    functions, units = _unit_specs(document)
    all_strings: set[str] = set()
    _collect_strings(document, all_strings)
    strings = sorted(all_strings, key=lambda value: value.encode("utf-8"))
    if len(strings) >= _NO_SYMBOL:
        raise WholeProgramVMError("PZWV018", "too many bytecode symbols")
    string_ids = {value: index for index, value in enumerate(strings)}
    codec = _TypedCodec(strings)

    string_blob = b"".join(
        struct.pack("<H", len(encoded)) + encoded
        for value in strings for encoded in (value.encode("utf-8"),))
    root_meta = {key: copy.deepcopy(value) for key, value in document.items()
                 if key != "functions"}
    metadata = bytearray(codec.encode(root_meta))
    function_meta: list[tuple[int, int]] = []
    for function in functions:
        encoded = codec.encode(function["meta"])
        function_meta.append((len(metadata), len(encoded)))
        metadata.extend(encoded)
    unit_meta: list[tuple[int, int]] = []
    for unit in units:
        encoded = codec.encode(unit["meta"])
        unit_meta.append((len(metadata), len(encoded)))
        metadata.extend(encoded)

    string_offset = _HEADER.size
    function_offset = string_offset + len(string_blob)
    unit_offset = function_offset + len(functions) * _FUNCTION.size
    meta_offset = unit_offset + len(units) * _UNIT.size
    code_offset = meta_offset + len(metadata)

    code = bytearray()
    unit_layout: list[tuple[int, int, int, int]] = []
    block_count = 0
    for unit in units:
        start = code_offset + len(code)
        blob, entry_pc, count = _encode_unit_blocks(
            unit, start, codec, string_ids)
        code.extend(blob)
        unit_layout.append((entry_pc, start, start + len(blob), count))
        block_count += count

    function_table = bytearray()
    for function, (relative, size) in zip(functions, function_meta):
        function_table.extend(_FUNCTION.pack(
            string_ids[function["callable_id"]], function["unit"],
            function["parameter_count"], 0, relative, size))
    unit_table = bytearray()
    for unit, layout, (relative, size) in zip(units, unit_layout, unit_meta):
        entry_pc, start, end, _ = layout
        unit_table.extend(_UNIT.pack(
            unit["kind"], 0, unit["owner"], string_ids[unit["name"]],
            _sid(string_ids, unit["result"]), entry_pc, start, end,
            string_ids[unit["meta"].get("semantic_sha256", unit["name"])],
            0, relative, size))

    payload = (string_blob + bytes(function_table) + bytes(unit_table) +
               bytes(metadata) + bytes(code))
    digest = hashlib.sha256(payload).digest()
    header = _HEADER.pack(
        BYTECODE_MAGIC, BYTECODE_VERSION, 0, _HEADER.size,
        _HEADER.size + len(payload), zlib.crc32(payload) & 0xFFFFFFFF,
        digest, len(strings), len(functions), len(units), 0,
        string_offset, function_offset, unit_offset,
        meta_offset, len(metadata), code_offset, len(code))
    coverage = {
        "function_count": len(functions),
        "proven_reachable_function_count": len(
            document.get("proven_reachable_callable_ids", ())),
        "guarded_callable_function_count": len(
            document.get("guarded_callable_ids", ())),
        "unit_count": len(units),
        "expression_program_count": len(units) - len(functions),
        "block_count": block_count,
        "instruction_count": sum(
            len(block["instructions"]) for unit in units
            for block in unit["blocks"]),
        "terminator_count": block_count,
        "symbol_count": len(strings),
        "bytecode_bytes": len(header) + len(payload),
    }
    return header + payload, coverage


def _slice(data: bytes, offset: int, size: int, where: str) -> bytes:
    if offset < 0 or size < 0 or offset + size > len(data):
        raise WholeProgramVMError("PZWV019", f"{where} outside image")
    return data[offset:offset + size]


def _parse_header(data: bytes) -> dict[str, Any]:
    if len(data) < _HEADER.size:
        raise WholeProgramVMError("PZWV020", "truncated bytecode header")
    try:
        values = _HEADER.unpack_from(data)
    except struct.error as exc:
        raise WholeProgramVMError("PZWV020", "truncated bytecode header") from exc
    (magic, version, flags, header_size, total_size, crc32, digest,
     string_count, function_count, unit_count, entry_function,
     string_offset, function_offset, unit_offset, meta_offset, meta_size,
     code_offset, code_size) = values
    if (magic != BYTECODE_MAGIC or version != BYTECODE_VERSION or flags != 0 or
            header_size != _HEADER.size or total_size != len(data)):
        raise WholeProgramVMError("PZWV021", "invalid bytecode header")
    payload = data[header_size:]
    if zlib.crc32(payload) & 0xFFFFFFFF != crc32:
        raise WholeProgramVMError("PZWV022", "bytecode CRC mismatch")
    if hashlib.sha256(payload).digest() != digest:
        raise WholeProgramVMError("PZWV023", "bytecode SHA-256 mismatch")
    if not (header_size <= string_offset <= function_offset <= unit_offset <=
            meta_offset <= code_offset <= len(data)):
        raise WholeProgramVMError("PZWV024", "non-monotonic bytecode sections")
    if meta_offset + meta_size != code_offset or code_offset + code_size != len(data):
        raise WholeProgramVMError("PZWV025", "inconsistent bytecode section sizes")
    return dict(zip((
        "string_count", "function_count", "unit_count", "entry_function",
        "string_offset", "function_offset", "unit_offset", "meta_offset",
        "meta_size", "code_offset", "code_size"), (
        string_count, function_count, unit_count, entry_function,
        string_offset, function_offset, unit_offset, meta_offset, meta_size,
        code_offset, code_size)))


def _decode_strings(data: bytes, header: dict[str, Any]) -> tuple[str, ...]:
    cursor = header["string_offset"]
    output: list[str] = []
    for _ in range(header["string_count"]):
        if cursor + 2 > header["function_offset"]:
            raise WholeProgramVMError("PZWV026", "truncated string table")
        size = struct.unpack_from("<H", data, cursor)[0]
        cursor += 2
        raw = _slice(data, cursor, size, "string")
        cursor += size
        try:
            output.append(raw.decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise WholeProgramVMError("PZWV027", "invalid UTF-8 symbol") from exc
    if cursor != header["function_offset"] or output != sorted(
            output, key=lambda value: value.encode("utf-8")) or len(set(output)) != len(output):
        raise WholeProgramVMError("PZWV028", "non-canonical string table")
    return tuple(output)


def _decode_typed_exact(codec: _TypedCodec, data: bytes,
                        offset: int, size: int, where: str) -> object:
    blob = _slice(data, offset, size, where)
    value, end = codec.decode(blob)
    if end != len(blob):
        raise WholeProgramVMError("PZWV029", f"trailing bytes in {where}")
    return value


def _decode_unit_blocks(data: bytes, descriptor: dict[str, Any],
                        codec: _TypedCodec, strings: Sequence[str]) -> list[dict[str, Any]]:
    cursor = descriptor["start"]
    blocks: list[dict[str, Any]] = []
    pc_to_name: dict[int, str] = {}
    pending_targets: list[tuple[dict[str, Any], list[tuple[str, int]]]] = []
    while cursor < descriptor["end"]:
        if cursor + _BLOCK.size > descriptor["end"]:
            raise WholeProgramVMError("PZWV030", "truncated block")
        tag, block_size, name_sid, ex_sid, count, ex_pc = _BLOCK.unpack_from(data, cursor)
        if tag != _BLOCK_TAG or block_size < _BLOCK.size or cursor + block_size > descriptor["end"]:
            raise WholeProgramVMError("PZWV031", "invalid block record")
        name = strings[name_sid]
        block_pc = cursor + _BLOCK.size
        pc_to_name[block_pc] = name
        cursor = block_pc
        instructions: list[dict[str, Any]] = []
        for _ in range(count):
            fields = _INSTRUCTION.unpack_from(data, cursor)
            (tag, size, _core, op_sid, dst_sid, kind_sid, sequence,
             args_size, attrs_size, span_size, arg_count) = fields
            if tag != _INSTRUCTION_TAG or size < _INSTRUCTION.size:
                raise WholeProgramVMError("PZWV032", "invalid instruction record")
            pos = cursor + _INSTRUCTION.size
            arguments = _decode_typed_exact(codec, data, pos, args_size, "arguments")
            pos += args_size
            attributes = _decode_typed_exact(codec, data, pos, attrs_size, "attributes")
            pos += attrs_size
            span = _decode_typed_exact(codec, data, pos, span_size, "span")
            pos += span_size
            if pos != cursor + size or not isinstance(arguments, list) or len(arguments) != arg_count:
                raise WholeProgramVMError("PZWV033", "inconsistent instruction record")
            item: dict[str, Any] = {
                "sequence": sequence, "op": strings[op_sid],
                "arguments": arguments, "span": span,
            }
            if dst_sid != _NO_SYMBOL:
                item["destination"] = strings[dst_sid]
            if kind_sid != _NO_SYMBOL:
                item["value_kind"] = strings[kind_sid]
            if attributes:
                item["attributes"] = attributes
            instructions.append(item)
            cursor += size
        fields = _TERMINATOR.unpack_from(data, cursor)
        tag, size, _core, op_sid, args_size, target_count, span_size = fields
        if tag != _TERMINATOR_TAG or size < _TERMINATOR.size:
            raise WholeProgramVMError("PZWV034", "invalid terminator record")
        pos = cursor + _TERMINATOR.size
        targets: list[tuple[str, int]] = []
        for _ in range(target_count):
            sid, pc = struct.unpack_from("<HI", data, pos)
            pos += 6
            targets.append((strings[sid], pc))
        arguments = _decode_typed_exact(codec, data, pos, args_size, "term arguments")
        pos += args_size
        span = _decode_typed_exact(codec, data, pos, span_size, "term span")
        pos += span_size
        if pos != cursor + size or cursor + size != block_pc - _BLOCK.size + block_size:
            raise WholeProgramVMError("PZWV035", "inconsistent terminator/block size")
        terminator = {
            "op": strings[op_sid], "arguments": arguments,
            "targets": [name for name, _ in targets], "span": span,
        }
        block = {"name": name, "instructions": instructions,
                 "terminator": terminator}
        if ex_sid != _NO_SYMBOL:
            block["exception_target"] = strings[ex_sid]
            pending_targets.append((block, [(strings[ex_sid], ex_pc)]))
        pending_targets.append((terminator, targets))
        blocks.append(block)
        cursor += size
    if cursor != descriptor["end"]:
        raise WholeProgramVMError("PZWV036", "unit code length mismatch")
    for _owner, targets in pending_targets:
        for name, pc in targets:
            if pc_to_name.get(pc) != name:
                raise WholeProgramVMError("PZWV037", f"branch target mismatch for {name}")
    if pc_to_name.get(descriptor["entry"]) is None:
        raise WholeProgramVMError("PZWV038", "unit entry is not a block")
    return blocks


def decode_whole_program_vm(data: bytes) -> dict[str, Any]:
    """Validate and losslessly decode a whole-program VM image."""
    data = bytes(data)
    header = _parse_header(data)
    strings = _decode_strings(data, header)
    codec = _TypedCodec(strings)

    function_rows = []
    for index in range(header["function_count"]):
        offset = header["function_offset"] + index * _FUNCTION.size
        if offset + _FUNCTION.size > header["unit_offset"]:
            raise WholeProgramVMError("PZWV039", "truncated function table")
        sid, unit, params, flags, meta_rel, meta_size = _FUNCTION.unpack_from(data, offset)
        if flags != 0 or unit >= header["unit_count"]:
            raise WholeProgramVMError("PZWV040", "invalid function descriptor")
        meta = _decode_typed_exact(
            codec, data, header["meta_offset"] + meta_rel, meta_size,
            "function metadata")
        function_rows.append({"callable_id": strings[sid], "unit": unit,
                              "params": params, "meta": meta})
    expected_function_end = (header["function_offset"] +
                             header["function_count"] * _FUNCTION.size)
    if expected_function_end != header["unit_offset"]:
        raise WholeProgramVMError("PZWV041", "function table padding is forbidden")

    unit_rows = []
    for index in range(header["unit_count"]):
        offset = header["unit_offset"] + index * _UNIT.size
        if offset + _UNIT.size > header["meta_offset"]:
            raise WholeProgramVMError("PZWV042", "truncated unit table")
        (kind, flags, owner, name_sid, result_sid, entry, start, end,
         semantic_sid, locals_count, meta_rel, meta_size) = _UNIT.unpack_from(data, offset)
        if (kind not in (_UNIT_FUNCTION, _UNIT_EXPRESSION) or flags != 0 or
                owner >= header["function_count"] or not
                header["code_offset"] <= start <= end <= len(data)):
            raise WholeProgramVMError("PZWV043", "invalid unit descriptor")
        meta = _decode_typed_exact(
            codec, data, header["meta_offset"] + meta_rel, meta_size,
            "unit metadata")
        descriptor = {"kind": kind, "owner": owner, "name": strings[name_sid],
                      "result": None if result_sid == _NO_SYMBOL else strings[result_sid],
                      "entry": entry, "start": start, "end": end,
                      "semantic": strings[semantic_sid], "locals": locals_count,
                      "meta": meta}
        descriptor["blocks"] = _decode_unit_blocks(data, descriptor, codec, strings)
        unit_rows.append(descriptor)
    expected_unit_end = header["unit_offset"] + header["unit_count"] * _UNIT.size
    if expected_unit_end != header["meta_offset"]:
        raise WholeProgramVMError("PZWV044", "unit table padding is forbidden")

    root_meta, root_end = codec.decode(data, header["meta_offset"])
    if not isinstance(root_meta, dict) or root_end > header["code_offset"]:
        raise WholeProgramVMError("PZWV045", "invalid root metadata")
    document = copy.deepcopy(root_meta)
    functions: list[dict[str, Any]] = []
    for function_index, function in enumerate(function_rows):
        unit = unit_rows[function["unit"]]
        if unit["kind"] != _UNIT_FUNCTION or unit["owner"] != function_index:
            raise WholeProgramVMError("PZWV046", "function/unit ownership mismatch")
        cfg = copy.deepcopy(unit["meta"])
        cfg["blocks"] = unit["blocks"]
        cfg["expression_programs"] = []
        for expression in unit_rows:
            if expression["kind"] == _UNIT_EXPRESSION and expression["owner"] == function_index:
                program = copy.deepcopy(expression["meta"])
                program["blocks"] = expression["blocks"]
                cfg["expression_programs"].append(program)
        row = copy.deepcopy(function["meta"])
        row["cfg"] = cfg
        functions.append({"callable_id": function["callable_id"], "row": row})
    document["functions"] = functions
    expected_function_ids = [
        *document.get("proven_reachable_callable_ids", ()),
        *document.get("guarded_callable_ids", ()),
        *document.get("definition_callable_ids", ()),
    ]
    if expected_function_ids != [item["callable_id"] for item in functions]:
        raise WholeProgramVMError(
            "PZWV047", "proved/guarded order differs from function table")
    return document


# ---------------------------------------------------------------------------
# Compact target image.  The lossless PZVM container above is a host proof
# only.  PZVT deliberately contains no source/debug payload.

_TARGET_ADAPTER_BASE = 16
_TARGET_CORE_CONSTANT = 1
_TARGET_CORE_LOAD_NAME = 2
_TARGET_CORE_STORE_NAME = 3
_TARGET_CORE_BINARY_I32 = 4
_TARGET_CORE_CALL = 5
_TARGET_CORE_EXPRESSION = 6
_TARGET_CORE_CONSTRUCT = 7
_TARGET_CORE_NOP = 8
_TARGET_CORE_DATACLASS_INIT = 9
_TARGET_CORE_GUARDED_DISPATCH = 10
_TARGET_CORE_GUARDED_BOUND_DISPATCH = 11
_TARGET_CORE_GUARDED_LEXICAL_DISPATCH = 12
_TARGET_CORE_POSITIONAL_CLOSURE_CALL = 13
_TARGET_CORE_LOAD_LOCAL_NAME = 14
_TARGET_CORE_KEYWORD_CLOSURE_CALL = 15
_FINITE_DISPATCH_MODES = frozenset({
    "finite-dispatch", "finite-bound-dispatch",
    "finite-lexical-dispatch"})

_TARGET_TERM_JUMP = 1
_TARGET_TERM_BRANCH = 2
_TARGET_TERM_RETURN = 3
_TARGET_TERM_YIELD = 4       # layout-test primitive, never active suspend-yield
_TARGET_TERM_YIELD_NEXT = 5  # Проверенное тело исходного генератора: next/send(None).

_TARGET_BINARY_IDS = {
    "add": 0, "sub": 1, "mul": 2, "floordiv": 3,
    "mod": 4, "eq": 5, "lt": 6, "le": 7,
}


def _uvar(value: int) -> bytes:
    if not isinstance(value, int) or value < 0 or value > 0xFFFFFFFF:
        raise WholeProgramVMError("PZWV201", f"uvar out of range: {value}")
    output = bytearray()
    while value >= 0x80:
        output.append((value & 0x7F) | 0x80)
        value >>= 7
    output.append(value)
    return bytes(output)


def _read_uvar(data: bytes, offset: int, end: int) -> tuple[int, int]:
    value = 0
    shift = 0
    for _ in range(5):
        if offset >= end:
            raise WholeProgramVMError("PZWV202", "truncated compact varint")
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            if value > 0xFFFFFFFF:
                raise WholeProgramVMError("PZWV203", "compact varint overflow")
            return value, offset
        shift += 7
    raise WholeProgramVMError("PZWV203", "compact varint overflow")


def _u24(value: int) -> bytes:
    if value < 0 or value > 0xFFFFFF:
        raise WholeProgramVMError("PZWV204", f"24-bit offset overflow: {value}")
    return bytes((value & 0xFF, (value >> 8) & 0xFF, (value >> 16) & 0xFF))


def _read_u24(data: bytes, offset: int) -> int:
    if offset < 0 or offset + 3 > len(data):
        raise WholeProgramVMError("PZWV205", "truncated 24-bit offset")
    return data[offset] | data[offset + 1] << 8 | data[offset + 2] << 16


def _target_constant_bytes(value: object) -> bytes:
    if value is None:
        return b"\x00"
    if value is False:
        return b"\x01"
    if value is True:
        return b"\x02"
    if isinstance(value, int):
        if -(1 << 31) <= value < (1 << 31):
            zigzag = (value << 1) ^ (value >> 31)
            return b"\x03" + _uvar(zigzag & 0xFFFFFFFF)
        raw = str(value).encode("ascii")
        return b"\x09" + _uvar(len(raw)) + raw
    if isinstance(value, float):
        if not math.isfinite(value):
            raise WholeProgramVMError("PZWV206", "non-finite compact constant")
        return b"\x04" + struct.pack("<d", value)
    if isinstance(value, str):
        raw = value.encode("utf-8")
        return b"\x05" + _uvar(len(raw)) + raw
    if isinstance(value, bytes):
        return b"\x08" + _uvar(len(value)) + value
    if isinstance(value, (list, tuple)):
        return (b"\x06" + _uvar(len(value)) +
                b"".join(_target_constant_bytes(item) for item in value))
    if isinstance(value, dict):
        ordered = sorted(value.items(), key=lambda item: str(item[0]).encode("utf-8"))
        return (b"\x07" + _uvar(len(ordered)) + b"".join(
            _target_constant_bytes(str(key)) + _target_constant_bytes(item)
            for key, item in ordered))
    raise WholeProgramVMError(
        "PZWV207", f"unsupported compact constant {type(value).__name__}")


def _decode_target_constant(data: bytes, offset: int,
                            end: int, depth: int = 0) -> tuple[object, int]:
    if depth > 64 or offset >= end:
        raise WholeProgramVMError("PZWV208", "malformed compact constant")
    tag = data[offset]
    offset += 1
    if tag == 0:
        return None, offset
    if tag == 1:
        return False, offset
    if tag == 2:
        return True, offset
    if tag == 3:
        raw, offset = _read_uvar(data, offset, end)
        return (raw >> 1) ^ -(raw & 1), offset
    if tag == 4:
        if offset + 8 > end:
            raise WholeProgramVMError("PZWV208", "truncated float constant")
        return struct.unpack_from("<d", data, offset)[0], offset + 8
    if tag in (5, 8, 9):
        size, offset = _read_uvar(data, offset, end)
        if offset + size > end:
            raise WholeProgramVMError("PZWV208", "truncated variable constant")
        raw = data[offset:offset + size]
        if tag == 5:
            try:
                value: object = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise WholeProgramVMError("PZWV208", "invalid constant UTF-8") from exc
        elif tag == 9:
            try:
                value = int(raw.decode("ascii"))
            except (UnicodeError, ValueError) as exc:
                raise WholeProgramVMError("PZWV208", "invalid bigint constant") from exc
        else:
            value = raw
        return value, offset + size
    if tag == 6:
        count, offset = _read_uvar(data, offset, end)
        result = []
        for _ in range(count):
            item, offset = _decode_target_constant(data, offset, end, depth + 1)
            result.append(item)
        return result, offset
    if tag == 7:
        count, offset = _read_uvar(data, offset, end)
        result: dict[str, object] = {}
        for _ in range(count):
            key, offset = _decode_target_constant(data, offset, end, depth + 1)
            item, offset = _decode_target_constant(data, offset, end, depth + 1)
            if not isinstance(key, str) or key in result:
                raise WholeProgramVMError("PZWV208", "invalid compact map key")
            result[key] = item
        return result, offset
    raise WholeProgramVMError("PZWV209", f"unknown compact constant tag {tag}")


def _adapter_descriptor(kind: str, item: dict[str, Any]) -> dict[str, Any]:
    descriptor = {
        "kind": kind,
        "op": item["op"],
        "argument_count": len(item.get("arguments", [])),
        "attributes": copy.deepcopy(item.get("attributes", {})),
    }
    if kind == "instruction":
        descriptor["value_kind"] = item.get("value_kind")
        descriptor["has_destination"] = item.get("destination") is not None
    else:
        descriptor["target_count"] = len(item.get("targets", []))
    if kind == "instruction" and item.get("op") == "python-call":
        # Shape-only deduplication is invalid for call boundaries: the target
        # adapter must know which source call site and resolution obligation it
        # implements.  The full SHA/targets stay in the host table; PZVT carries
        # only the resulting dense numeric adapter ID.
        binding = item.get("_target_call_site")
        if isinstance(binding, dict):
            descriptor["call_site_id"] = binding["call_site_id"]
            descriptor["resolution_kind"] = binding.get("resolution_kind")
            descriptor["resolution_targets"] = list(binding.get("targets", []))
            # An ABI report describes occurrences, not merely source sites.
            # Keep duplicate CFG occurrences distinct even when their source
            # span, call-site ID and operation shape are identical.
            if isinstance(binding.get("numeric_abi_descriptor_id"), int):
                descriptor["numeric_abi_descriptor_id"] = binding[
                    "numeric_abi_descriptor_id"]
                descriptor["cfg_occurrence_index"] = binding[
                    "cfg_occurrence_index"]
                descriptor["cfg_path"] = copy.deepcopy(binding["cfg_path"])
    descriptor["semantic_sha256"] = _sha256_json(descriptor)
    return descriptor


def _constructor_allocation_adapter_descriptor() -> dict[str, Any]:
    """Return the one target boundary needed by every exact constructor.

    Allocation and object lifetime remain target-owned; argument binding,
    ``__init__`` dispatch, its mandatory ``None`` result and expression return
    are core VM semantics rather than a per-call Python adapter.
    """
    return _adapter_descriptor("instruction", {
        "op": "allocate-instance",
        "arguments": ["$constructed-class"],
        "destination": "$allocated-object",
        "value_kind": "opaque",
        "attributes": {
            "allocation_boundary": "target-object-model",
            "result_contract": "opaque-instance",
        },
    })


def _generated_dataclass_init_adapter_descriptor(
        schema: Mapping[str, Any]) -> dict[str, Any]:
    """Return the exact target-object-model boundary for dataclass fields."""
    descriptor = {
        "kind": "generated-dataclass-init",
        "op": "store-generated-dataclass-fields",
        "class_id": schema.get("class_id"),
        "field_names": [row.get("name") for row in schema.get("fields", ())
                        if isinstance(row, Mapping)],
        "argument_count": 1 + len(schema.get("fields", ())),
        "result_contract": "none",
        "generated_dataclass_init_semantic_sha256": schema.get(
            "semantic_sha256"),
    }
    descriptor["semantic_sha256"] = _sha256_json(descriptor)
    return descriptor


def _finite_dispatch_guard_adapter_descriptor(
        plan: Mapping[str, Any]) -> dict[str, Any]:
    """Return the identity-selection boundary for a finite callable set.

    The adapter receives the already evaluated callable object and returns the
    zero-based candidate index as I32.  PZVT validates that index before any
    candidate is entered; an unknown identity therefore fails closed instead
    of selecting a guessed implementation.
    """
    candidates = plan.get("candidates", ())
    descriptor = {
        "kind": "finite-callable-identity-dispatch",
        "op": "resolve-finite-callable-identity",
        "call_site_id": plan.get("call_site_id"),
        "candidate_callable_ids": [
            row.get("target") for row in candidates
            if isinstance(row, Mapping)],
        "argument_count": 1,
        "result_contract": "i32-zero-based-candidate-index",
        "unknown_identity_contract": "fail-closed",
    }
    descriptor["semantic_sha256"] = _sha256_json(descriptor)
    return descriptor


def _finite_dispatch_receiver_adapter_descriptor(
        plan: Mapping[str, Any]) -> dict[str, Any]:
    """Return the checked receiver extraction boundary for a bound callback.

    The callable was loaded from a local parameter, so its receiver has no
    caller-local SSA value.  After the identity guard selects one exact target,
    this adapter receives the same callable plus that I32 candidate index and
    returns the callable's actual bound receiver.  The target object model must
    reject unbound callables and identity/index disagreement.
    """
    candidates = plan.get("candidates", ())
    descriptor = {
        "kind": "finite-bound-callable-receiver",
        "op": "extract-finite-bound-callable-receiver",
        "call_site_id": plan.get("call_site_id"),
        "candidate_callable_ids": [
            row.get("target") for row in candidates
            if isinstance(row, Mapping)],
        "argument_count": 2,
        "argument_contract": [
            "already-evaluated-callable", "i32-zero-based-candidate-index"],
        "result_contract": "opaque-bound-receiver-for-selected-candidate",
        "unbound_or_mismatch_contract": "fail-closed",
    }
    descriptor["semantic_sha256"] = _sha256_json(descriptor)
    return descriptor


def _call_site_span_key(caller: str, item: Mapping[str, Any]) -> tuple[
        str, int, int, int, int] | None:
    span = item.get("span")
    if not isinstance(span, dict):
        return None
    values = [span.get(field) for field in (
        "line", "column", "end_line", "end_column")]
    if any(not isinstance(value, int) for value in values):
        return None
    return (caller, values[0], values[1], values[2], values[3])


def _safe_direct_python_target(
        item: Mapping[str, Any], site: Mapping[str, Any] | None,
        function_specs: Mapping[str, Mapping[str, Any]]) -> str | None:
    """Return a semantics-preserving direct target for the v1 ABI.

    This is the deliberately narrow fallback used when the exact call ABI is
    absent.  The ABI-aware path additionally handles receivers, keyword
    reordering, explicitly supplied defaulted parameters and constructors.
    """
    if site is None:
        return None
    resolution = site.get("resolution")
    if not isinstance(resolution, dict) or resolution.get("proven") is not True:
        return None
    targets = resolution.get("targets")
    if (resolution.get("kind") != "exact-internal-function" or
            not isinstance(targets, list) or len(targets) != 1 or
            targets[0] not in function_specs):
        return None
    args = item.get("arguments")
    attrs = item.get("attributes", {})
    if (not isinstance(args, list) or not args or not isinstance(attrs, dict) or
            attrs.get("keywords") not in (False, None)):
        return None
    layout = attrs.get("argument_layout", [])
    if (not isinstance(layout, list) or len(layout) != len(args) - 1 or
            any(not isinstance(row, (list, tuple)) or len(row) != 2 or
                row[0] != "positional" for row in layout)):
        return None
    target = function_specs[targets[0]]
    signature = target.get("signature")
    if not isinstance(signature, dict):
        return None
    parameters = signature.get("parameters")
    if (not isinstance(parameters, list) or len(parameters) != len(args) - 1 or
            signature.get("async") is not False or
            signature.get("decorators") not in ([], ()) or
            signature.get("execution_kind") == "generator-frame"):
        return None
    for parameter in parameters:
        if (not isinstance(parameter, dict) or
                parameter.get("kind") not in (
                    "positional-only", "positional-or-keyword")):
            return None
    return str(targets[0])


def _prepare_legacy_call_site_aware_units(
        document: Mapping[str, Any], functions: Sequence[dict[str, Any]],
        units: Sequence[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Copy/annotate target units without modifying the lossless proof CFG."""
    prepared = copy.deepcopy(list(units))
    by_span: dict[tuple[str, int, int, int, int], dict[str, Any]] = {}
    raw_sites = document.get("reachable_call_sites", [])
    if not isinstance(raw_sites, list):
        raise WholeProgramVMError("PZWV245", "reachable_call_sites is not a list")
    for raw_site in raw_sites:
        site = _require_dict(raw_site, "reachable call site")
        coordinates = [site.get(field) for field in (
            "line", "column", "end_line", "end_column")]
        if (not isinstance(site.get("caller"), str) or
                any(not isinstance(value, int) for value in coordinates)):
            raise WholeProgramVMError("PZWV245", "malformed target call-site span")
        _require_string(site.get("call_site_id"), "target call_site_id")
        _require_dict(site.get("resolution"), "target call-site resolution")
        key = (site["caller"], coordinates[0], coordinates[1],
               coordinates[2], coordinates[3])
        previous = by_span.get(key)
        if previous is not None and previous.get("call_site_id") != site.get("call_site_id"):
            raise WholeProgramVMError(
                "PZWV245", f"ambiguous call-site span for {key[0]}:{key[1]}:{key[2]}")
        by_span[key] = site

    function_specs = {
        function["callable_id"]: prepared[function["unit"]]["meta"]
        for function in functions}
    seen_python_sites: set[str] = set()
    matched_graph_sites: set[str] = set()
    lowered_sites: set[str] = set()
    lowered_instructions = 0
    python_instructions = 0
    missing_instructions = 0
    lowering_rows: dict[str, dict[str, Any]] = {}
    for unit in prepared:
        caller = functions[unit["owner"]]["callable_id"]
        for cfg_block in unit["blocks"]:
            for item in cfg_block["instructions"]:
                if item.get("op") != "python-call":
                    continue
                python_instructions += 1
                key = _call_site_span_key(caller, item)
                site = by_span.get(key) if key is not None else None
                if site is None:
                    missing_instructions += 1
                    derived = _sha256_json({
                        "caller": caller,
                        "span": item.get("span", {}),
                        "op": "python-call",
                    })
                    binding = {
                        "call_site_id": f"derived:{derived}",
                        "resolution_kind": "missing-call-graph-site",
                        "targets": [],
                    }
                else:
                    site_id = str(site["call_site_id"])
                    matched_graph_sites.add(site_id)
                    binding = {
                        "call_site_id": site_id,
                        "resolution_kind": site["resolution"].get("kind"),
                        "targets": list(site["resolution"].get("targets", [])),
                    }
                item["_target_call_site"] = binding
                site_id = binding["call_site_id"]
                seen_python_sites.add(site_id)
                direct = _safe_direct_python_target(item, site, function_specs)
                if direct is not None:
                    item["_target_direct_function"] = direct
                    lowered_sites.add(site_id)
                    lowered_instructions += 1
                    mode = "direct-core-call"
                else:
                    mode = "site-specific-adapter"
                lowering_rows[site_id] = {
                    **binding, "mode": mode,
                }
    return prepared, {
        "call_abi_input_enabled": False,
        "active_call_site_lowering_semantic_sha256": None,
        "whole_program_vm_call_abi_semantic_sha256": None,
        "python_call_instruction_count": python_instructions,
        "python_call_site_count": len(seen_python_sites),
        "matched_call_graph_site_count": len(matched_graph_sites),
        "missing_call_graph_instruction_count": missing_instructions,
        "direct_call_instruction_count": lowered_instructions,
        "direct_call_site_count": len(lowered_sites),
        "direct_call_site_ids": sorted(lowered_sites),
        "legacy_direct_call_instruction_count": lowered_instructions,
        "legacy_direct_call_site_count": len(lowered_sites),
        "abi_exact_internal_occurrence_count": 0,
        "abi_eligible_call_instruction_count": 0,
        "abi_lowered_call_instruction_count": 0,
        "abi_finite_dispatch_instruction_count": 0,
        "abi_finite_dispatch_site_count": 0,
        "abi_finite_dispatch_site_ids": [],
        "abi_finite_bound_dispatch_instruction_count": 0,
        "abi_finite_bound_dispatch_site_count": 0,
        "abi_finite_bound_dispatch_site_ids": [],
        "abi_finite_lexical_dispatch_instruction_count": 0,
        "abi_finite_lexical_dispatch_site_count": 0,
        "abi_finite_lexical_dispatch_site_ids": [],
        "abi_constructor_call_instruction_count": 0,
        "abi_unlowered_call_instruction_count": python_instructions,
        "abi_eligible_call_site_count": 0,
        "abi_lowered_call_site_count": 0,
        "abi_unlowered_call_site_count": len(seen_python_sites),
        "abi_unlowered_reason_counts": {
            "optional-call-abi-not-supplied": python_instructions},
        "guarded_body_adapter_instruction_count": 0,
        "guarded_body_adapter_site_count": 0,
        "call_site_lowering": [lowering_rows[key] for key in sorted(lowering_rows)],
    }


def _validate_optional_call_abi_inputs(
        document: Mapping[str, Any],
        active_call_site_lowering: Mapping[str, Any] | None,
        whole_program_vm_call_abi: Mapping[str, Any] | None,
        ) -> tuple[dict[str, Any], dict[str, Any]] | None:
    if active_call_site_lowering is None and whole_program_vm_call_abi is None:
        return None
    if active_call_site_lowering is None or whole_program_vm_call_abi is None:
        raise WholeProgramVMError(
            "PZWV266", "call-site lowering and call ABI must be supplied together")
    lowering = _require_dict(
        copy.deepcopy(dict(active_call_site_lowering)),
        "active call-site lowering")
    call_abi = _require_dict(
        copy.deepcopy(dict(whole_program_vm_call_abi)),
        "whole-program VM call ABI")
    _validated_semantic(lowering, "active call-site lowering")
    _validated_semantic(call_abi, "whole-program VM call ABI")
    if (lowering.get("format") != ACTIVE_CALL_SITE_LOWERING_FORMAT or
            lowering.get("status") != ACTIVE_CALL_SITE_LOWERING_STATUS or
            lowering.get("live") is not False):
        raise WholeProgramVMError(
            "PZWV263", "active call-site lowering status/format mismatch")
    if (call_abi.get("format") != WHOLE_PROGRAM_VM_CALL_ABI_FORMAT or
            call_abi.get("status") != WHOLE_PROGRAM_VM_CALL_ABI_STATUS or
            call_abi.get("live") is not False):
        raise WholeProgramVMError(
            "PZWV263", "whole-program VM call ABI status/format mismatch")
    graph_semantic = document.get("active_call_graph_semantic_sha256")
    if (lowering.get("active_call_graph_semantic_sha256") != graph_semantic or
            call_abi.get("active_call_graph_semantic_sha256") !=
            graph_semantic or
            call_abi.get("call_site_lowering_semantic_sha256") !=
            lowering.get("semantic_sha256")):
        raise WholeProgramVMError(
            "PZWV263", "call ABI inputs are not bound to this graph/lowering")
    reachable = list(document.get("proven_reachable_callable_ids", ()))
    function_rows = _require_list(
        call_abi.get("function_id_table"), "call ABI function table")
    if len(function_rows) < len(reachable):
        raise WholeProgramVMError("PZWV263", "call ABI function table is short")
    for index, callable_id in enumerate(reachable):
        row = _require_dict(function_rows[index], "call ABI function row")
        if (row.get("numeric_function_id") != index or
                row.get("callable_id") != callable_id or
                row.get("proven_reachable") is not True or
                row.get("current_pzvt_function_id") != index):
            raise WholeProgramVMError(
                "PZWV263", "call ABI reachable function prefix mismatch")
    guarded_table = _require_list(
        document.get("guarded_callable_table", []),
        "guarded callable table")
    guarded_ids = _require_list(
        document.get("guarded_callable_ids", []), "guarded callable ids")
    if len(guarded_table) != len(guarded_ids):
        raise WholeProgramVMError(
            "PZWV271", "guarded callable table/count mismatch")
    for generated_index, (callable_id, raw_guarded) in enumerate(
            zip(guarded_ids, guarded_table), start=len(reachable)):
        guarded = _require_dict(raw_guarded, "guarded callable row")
        numeric_id = guarded.get("numeric_function_id")
        if (not isinstance(numeric_id, int) or
                not 0 <= numeric_id < len(function_rows)):
            raise WholeProgramVMError(
                "PZWV271", "guarded callable numeric ID is out of range")
        abi_row = _require_dict(
            function_rows[numeric_id], "guarded call ABI function row")
        lexical_owner = guarded.get("lexical_owner_callable_id")
        expected_admission = (
            "runtime-identity-and-lexical-owner-guard-only"
            if lexical_owner is not None else
            "runtime-identity-guard-only")
        if (callable_id != guarded.get("callable_id") or
                guarded.get("pzvt_function_id") != generated_index or
                guarded.get("admission") != expected_admission or
                (lexical_owner is not None and
                 lexical_owner not in reachable) or
                guarded.get("static_reachability_edge") is not False or
                abi_row.get("numeric_function_id") != numeric_id or
                abi_row.get("callable_id") != callable_id or
                abi_row.get("proven_reachable") is not False or
                abi_row.get("current_pzvt_function_id") is not None):
            raise WholeProgramVMError(
                "PZWV271", "guarded callable ABI binding mismatch")
    _validate_call_abi_prerequisites(document, lowering, call_abi)
    return lowering, call_abi


def _call_instruction_proof(instruction: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "op": instruction.get("op"),
        "sequence": instruction.get("sequence"),
        "destination": instruction.get("destination"),
        "arguments": list(instruction.get("arguments", ())),
        "span": dict(instruction.get("span", {})),
    }


def _call_definition_map(
        instructions: Sequence[Mapping[str, Any]], stop: int,
        ) -> dict[str, list[Mapping[str, Any]]]:
    result: dict[str, list[Mapping[str, Any]]] = {}
    for instruction in instructions[:stop]:
        destination = instruction.get("destination")
        if isinstance(destination, str):
            result.setdefault(destination, []).append(instruction)
    return result


def _call_dominating_definition_map(
        unit: Mapping[str, Any], block_index: int, instruction_index: int,
        cache: dict[int, DominatingDefinitions] | None = None,
        ) -> dict[str, list[Mapping[str, Any]]]:
    """Return unique candidates visible through strict CFG dominance."""
    try:
        index = cache.get(id(unit)) if cache is not None else None
        if index is None:
            index = DominatingDefinitions(unit)
            if cache is not None:
                cache[id(unit)] = index
        return index.at(block_index, instruction_index)
    except CFGSSAError as error:
        raise WholeProgramVMError("PZWV264", str(error)) from error


def _call_trace_value(
        value: Any, definitions: Mapping[str, list[Mapping[str, Any]]], *,
        seen: frozenset[str] = frozenset(), depth: int = 0,
        ) -> dict[str, Any]:
    if not isinstance(value, str) or not value.startswith("%"):
        return {"value": value, "kind": "literal-or-name"}
    matches = definitions.get(value, ())
    if len(matches) != 1:
        return {
            "value": value, "kind": "ambiguous-ssa-definition",
            "definition_count": len(matches),
        }
    if value in seen or depth >= 32:
        return {"value": value, "kind": "ssa-cycle-or-depth-limit"}
    definition = matches[0]
    arguments = list(definition.get("arguments", ()))
    return {
        "value": value,
        "kind": "ssa-definition",
        "definition": _call_instruction_proof(definition),
        "inputs": [
            _call_trace_value(
                argument, definitions, seen=seen | {value}, depth=depth + 1)
            for argument in arguments
            if isinstance(argument, str) and argument.startswith("%")
        ],
    }


def _call_trace_is_unambiguous(trace: Mapping[str, Any]) -> bool:
    if trace.get("kind") == "literal-or-name":
        return True
    if trace.get("kind") != "ssa-definition":
        return False
    return all(_call_trace_is_unambiguous(item)
               for item in trace.get("inputs", ()))


def _actual_callable_ssa_provenance(
        instruction: Mapping[str, Any],
        definitions: Mapping[str, list[Mapping[str, Any]]],
        ) -> dict[str, Any]:
    arguments = instruction.get("arguments")
    if not isinstance(arguments, list) or not arguments:
        return {
            "status": "ambiguous", "blocker": "PZCABI201",
            "detail": "python-call has no callable operand",
        }
    callable_value = arguments[0]
    require_matches = definitions.get(str(callable_value), ())
    if len(require_matches) != 1 or require_matches[0].get(
            "op") != "require-callable":
        return {
            "status": "ambiguous", "blocker": "PZCABI201",
            "callable_value": callable_value,
            "definition_count": len(require_matches),
            "detail": "callable operand has no unique require-callable",
        }
    require = require_matches[0]
    require_arguments = list(require.get("arguments", ()))
    if len(require_arguments) != 1:
        return {
            "status": "ambiguous", "blocker": "PZCABI201",
            "callable_value": callable_value,
            "require_callable": _call_instruction_proof(require),
            "detail": "require-callable does not have one source value",
        }
    source_value = require_arguments[0]
    source_matches = definitions.get(str(source_value), ())
    if len(source_matches) != 1:
        return {
            "status": "ambiguous", "blocker": "PZCABI201",
            "callable_value": callable_value,
            "require_callable": _call_instruction_proof(require),
            "callable_source_value": source_value,
            "source_definition_count": len(source_matches),
            "detail": "require-callable source has no unique SSA definition",
        }
    source = source_matches[0]
    source_arguments = list(source.get("arguments", ()))
    result: dict[str, Any] = {
        "status": "exact",
        "callable_value": callable_value,
        "require_callable": _call_instruction_proof(require),
        "callable_source_value": source_value,
        "callable_source": _call_instruction_proof(source),
        "source_operation": source.get("op"),
    }
    if source.get("op") == "load-attribute" and len(source_arguments) >= 2:
        receiver = source_arguments[0]
        receiver_provenance = _call_trace_value(receiver, definitions)
        result.update({
            "source_kind": "attribute",
            "receiver_value": receiver,
            "attribute_name": source_arguments[1],
            "receiver_provenance": receiver_provenance,
            "receiver_status": (
                "exact" if _call_trace_is_unambiguous(receiver_provenance)
                else "ambiguous"),
        })
    elif source.get("op") == "load-name" and len(source_arguments) == 1:
        result.update({
            "source_kind": "name",
            "loaded_name": source_arguments[0],
        })
    else:
        result.update({
            "status": "ambiguous",
            "blocker": "PZCABI201",
            "source_kind": "other-expression",
            "detail": "callable source is neither load-name nor load-attribute",
        })
    return result


def _call_abi_occurrence_instruction(
        occurrence: Mapping[str, Any], *,
        functions_by_callable: Mapping[str, Mapping[str, Any]],
        units: Sequence[dict[str, Any]], unit_ids: Mapping[str, int],
        document_functions: Mapping[str, Mapping[str, Any]],
        definition_indexes: dict[int, DominatingDefinitions] | None = None,
        ) -> tuple[int, int, int, dict[str, Any], dict[str, Any]]:
    caller = _require_string(occurrence.get("caller"), "occurrence caller")
    function = functions_by_callable.get(caller)
    document_function = document_functions.get(caller)
    if function is None or document_function is None:
        raise WholeProgramVMError("PZWV264", f"unknown ABI caller {caller}")
    path = _require_list(occurrence.get("cfg_path"), "occurrence cfg_path")
    if (len(path) == 4 and path[0] == "blocks" and
            path[2] == "instructions" and
            isinstance(path[1], int) and isinstance(path[3], int)):
        unit_index = int(function["unit"])
        block_index, instruction_index = int(path[1]), int(path[3])
    elif (len(path) == 6 and path[0] == "expression_programs" and
          path[2] == "blocks" and path[4] == "instructions" and
          isinstance(path[1], int) and isinstance(path[3], int) and
          isinstance(path[5], int)):
        program_index = int(path[1])
        programs = document_function["row"]["cfg"].get(
            "expression_programs", [])
        if not (0 <= program_index < len(programs)):
            raise WholeProgramVMError(
                "PZWV264", "ABI expression-program index is out of range")
        program_id = programs[program_index].get("program_id")
        if program_id not in unit_ids:
            raise WholeProgramVMError(
                "PZWV264", "ABI expression program has no PZVT unit")
        unit_index = int(unit_ids[str(program_id)])
        block_index, instruction_index = int(path[3]), int(path[5])
    else:
        raise WholeProgramVMError(
            "PZWV264", f"unsupported exact CFG occurrence path: {path}")
    if not (0 <= unit_index < len(units)):
        raise WholeProgramVMError("PZWV264", "ABI unit index is out of range")
    blocks = units[unit_index].get("blocks")
    if not isinstance(blocks, list) or not (0 <= block_index < len(blocks)):
        raise WholeProgramVMError("PZWV264", "ABI block index is out of range")
    instructions = blocks[block_index].get("instructions")
    if (not isinstance(instructions, list) or
            not (0 <= instruction_index < len(instructions))):
        raise WholeProgramVMError(
            "PZWV264", "ABI instruction index is out of range")
    item = _require_dict(
        instructions[instruction_index], "ABI occurrence instruction")
    if item.get("op") != "python-call":
        raise WholeProgramVMError(
            "PZWV264", "ABI occurrence path does not point to python-call")
    actual_provenance = _actual_callable_ssa_provenance(
        item, _call_dominating_definition_map(
            units[unit_index], block_index, instruction_index,
            definition_indexes))
    return (unit_index, block_index, instruction_index, item,
            actual_provenance)


def _abi_signature_parameters(
        target: str, function_specs: Mapping[str, Mapping[str, Any]],
        lowering_signatures: Mapping[str, Any],
        ) -> tuple[list[dict[str, Any]], Mapping[str, Any]]:
    function = function_specs.get(target)
    lowering_signature = lowering_signatures.get(target)
    if function is None or not isinstance(lowering_signature, Mapping):
        raise WholeProgramVMError(
            "PZWV265", f"ABI target signature is absent: {target}")
    meta = function.get("meta")
    cfg_signature = meta.get("signature") if isinstance(meta, Mapping) else None
    if not isinstance(cfg_signature, Mapping):
        raise WholeProgramVMError(
            "PZWV265", f"CFG target signature is absent: {target}")
    cfg_parameters = cfg_signature.get("parameters")
    lowering_parameters = lowering_signature.get("parameters")
    if not isinstance(cfg_parameters, list) or not isinstance(
            lowering_parameters, list):
        raise WholeProgramVMError("PZWV265", "ABI parameter table malformed")
    normalised: list[dict[str, Any]] = []
    for cfg_row, lowering_row in zip(cfg_parameters, lowering_parameters):
        if not isinstance(cfg_row, Mapping) or not isinstance(
                lowering_row, Mapping):
            raise WholeProgramVMError("PZWV265", "ABI parameter row malformed")
        row = {
            "name": cfg_row.get("name"),
            "kind": cfg_row.get("kind"),
            "has_default": cfg_row.get("default") is not None,
            "default_source": cfg_row.get("default"),
            "default_ast_sha256": lowering_row.get("default_ast_sha256"),
        }
        if (row["name"] != lowering_row.get("name") or
                row["kind"] != lowering_row.get("kind") or
                row["has_default"] is not lowering_row.get("has_default")):
            raise WholeProgramVMError(
                "PZWV265", f"CFG/call-ABI signature mismatch: {target}")
        normalised.append(row)
    if len(cfg_parameters) != len(lowering_parameters):
        raise WholeProgramVMError(
            "PZWV265", f"CFG/call-ABI parameter count mismatch: {target}")
    if bool(cfg_signature.get("async")) != bool(
            lowering_signature.get("is_async")):
        raise WholeProgramVMError(
            "PZWV265", f"CFG/call-ABI async mismatch: {target}")
    return normalised, lowering_signature


def _immutable_literal_default(
        parameter: Mapping[str, Any]) -> tuple[bool, object]:
    """Return a source/hash-proven scalar default supported by the value pool.

    Compound defaults require type and identity preserving object storage;
    they must not use the pool's generic sequence encoding (which conflates
    lists and tuples). Bytes need a typed JSON representation in the ABI
    manifest. Names and calls need definition-time evaluation.
    """
    source = parameter.get("default_source")
    expected_hash = parameter.get("default_ast_sha256")
    if not isinstance(source, str) or not isinstance(expected_hash, str):
        return False, None
    try:
        node = ast.parse(source, mode="eval").body
    except SyntaxError:
        return False, None
    actual_hash = hashlib.sha256(ast.dump(
        node, include_attributes=False).encode("utf-8")).hexdigest()
    if actual_hash != expected_hash:
        raise WholeProgramVMError(
            "PZWV265", "CFG/call-ABI default AST hash mismatch")
    try:
        value = ast.literal_eval(node)
    except (ValueError, TypeError):
        return False, None

    scalar = value is None or isinstance(value, (bool, int, float, str))
    if isinstance(value, float) and not math.isfinite(value):
        scalar = False
    return (True, value) if scalar else (False, None)


def _abi_generated_dataclass_init_plan(
        descriptor: Mapping[str, Any], resolution: Mapping[str, Any],
        target_rows: Sequence[Mapping[str, Any]],
        cfg_layout: Sequence[Mapping[str, Any]], *,
        function_specs: Mapping[str, Mapping[str, Any]],
        function_ids: Mapping[str, int],
        reasons: list[str],
        ) -> tuple[dict[str, Any] | None, list[str]]:
    """Validate and lower one source-proven generated dataclass initializer."""
    if len(target_rows) != 1:
        raise WholeProgramVMError(
            "PZWV265", "generated dataclass ABI descriptor target count mismatch")
    target_descriptor = target_rows[0]
    schema = resolution.get("generated_dataclass_init")
    if not isinstance(schema, Mapping):
        raise WholeProgramVMError(
            "PZWV265", "generated dataclass schema is absent")
    schema_payload = dict(schema)
    schema_hash = schema_payload.pop("semantic_sha256", None)
    parameters = schema.get("parameters")
    fields = schema.get("fields")
    post_init = schema.get("post_init_target")
    graph_targets = resolution.get("targets")
    expected_graph_targets = ([post_init]
                              if isinstance(post_init, str) else [])
    if (_sha256_json(schema_payload) != schema_hash or
            descriptor.get("generated_dataclass_init") != schema or
            target_descriptor.get("generated_dataclass_init") != schema or
            graph_targets != expected_graph_targets or
            target_descriptor.get("callable_id") != post_init or
            target_descriptor.get("binding_mode") !=
            "generated-dataclass-init" or
            target_descriptor.get("blocker_codes") not in ([], ()) or
            not isinstance(parameters, list) or not parameters or
            not isinstance(fields, list) or len(parameters) != len(fields) + 1):
        raise WholeProgramVMError(
            "PZWV265", "generated dataclass schema/target binding mismatch")
    parameter_rows = [
        _require_dict(row, "generated dataclass parameter")
        for row in parameters]
    field_rows = [
        _require_dict(row, "generated dataclass field") for row in fields]
    expected_names = [
        _require_string(row.get("name"), "generated dataclass parameter name")
        for row in parameter_rows]
    field_names = [
        _require_string(row.get("name"), "generated dataclass field name")
        for row in field_rows]
    if (expected_names[0] != "self" or expected_names[1:] != field_names or
            len(set(expected_names)) != len(expected_names) or
            any(row.get("kind") != "positional-or-keyword"
                for row in parameter_rows)):
        raise WholeProgramVMError(
            "PZWV265", "generated dataclass field/parameter order mismatch")
    receiver = descriptor.get("receiver_value")
    if (not isinstance(receiver, str) or
            receiver != resolution.get("receiver_parameter")):
        raise WholeProgramVMError(
            "PZWV265", "generated dataclass receiver proof mismatch")

    parameter_by_name = {str(row["name"]): row for row in parameter_rows}
    positional = expected_names[1:]
    cursor = 0
    supplied = {"self"}
    expected_destinations: dict[int, str] = {}
    for evaluation_index, argument in enumerate(cfg_layout):
        kind = argument.get("kind")
        if kind == "positional":
            if cursor >= len(positional):
                raise WholeProgramVMError(
                    "PZWV265", "generated dataclass has extra positional argument")
            parameter = positional[cursor]
            cursor += 1
        elif kind == "keyword":
            parameter = str(argument.get("keyword"))
            if parameter not in parameter_by_name or parameter == "self":
                raise WholeProgramVMError(
                    "PZWV265", "generated dataclass has unexpected keyword")
        else:
            return None, sorted(set(reasons + [
                f"unsupported-argument-layout:{kind}"]))
        if parameter in supplied:
            raise WholeProgramVMError(
                "PZWV265", "generated dataclass parameter is supplied twice")
        supplied.add(parameter)
        expected_destinations[evaluation_index] = parameter

    parameter_map = target_descriptor.get("parameter_destination_map")
    if not isinstance(parameter_map, list) or len(parameter_map) != len(parameters):
        raise WholeProgramVMError(
            "PZWV265", "generated dataclass parameter map/count mismatch")
    by_parameter: dict[str, Any] = {}
    seen_indexes: set[int] = set()
    for raw_entry in parameter_map:
        entry = _require_dict(raw_entry, "generated dataclass parameter map")
        parameter = entry.get("destination_parameter")
        if (not isinstance(parameter, str) or parameter in by_parameter or
                parameter not in parameter_by_name or
                entry.get("destination_kind") != "positional-or-keyword"):
            raise WholeProgramVMError(
                "PZWV265", "generated dataclass parameter destination mismatch")
        source_kind = entry.get("source_kind")
        if parameter == "self":
            if (source_kind != "receiver" or
                    entry.get("evaluation_index") != -1 or
                    entry.get("source_value") != receiver):
                raise WholeProgramVMError(
                    "PZWV265", "generated dataclass self mapping mismatch")
            value = receiver
        elif source_kind == "argument":
            evaluation_index = entry.get("evaluation_index")
            if (not isinstance(evaluation_index, int) or
                    not (0 <= evaluation_index < len(cfg_layout)) or
                    evaluation_index in seen_indexes or
                    expected_destinations.get(evaluation_index) != parameter or
                    entry.get("source_value") !=
                    cfg_layout[evaluation_index].get("value")):
                raise WholeProgramVMError(
                    "PZWV265", "generated dataclass argument mapping mismatch")
            seen_indexes.add(evaluation_index)
            value = entry.get("source_value")
        elif source_kind == "literal-default":
            schema_parameter = parameter_by_name[parameter]
            if (parameter in supplied or
                    schema_parameter.get("has_default") is not True or
                    schema_parameter.get("default_value_proven") is not True or
                    entry.get("evaluation_index") is not None or
                    entry.get("source_value") !=
                    schema_parameter.get("default_value")):
                raise WholeProgramVMError(
                    "PZWV265", "generated dataclass literal default mismatch")
            value = entry.get("source_value")
        else:
            return None, sorted(set(reasons + [
                f"unsupported-parameter-source:{source_kind}"]))
        by_parameter[parameter] = value
    if (set(by_parameter) != set(expected_names) or
            seen_indexes != set(range(len(cfg_layout)))):
        raise WholeProgramVMError(
            "PZWV265", "generated dataclass parameter map is incomplete")

    post_function_id: int | None = None
    if isinstance(post_init, str):
        post_function_id = function_ids.get(post_init)
        post_function = function_specs.get(post_init)
        if (post_function_id is None or post_function is None or
                target_descriptor.get("numeric_function_id") !=
                post_function_id or
                target_descriptor.get("current_pzvt_function_id") !=
                post_function_id or
                target_descriptor.get("proven_reachable") is not True):
            raise WholeProgramVMError(
                "PZWV265", "generated dataclass post-init target mismatch")
        post_parameters = post_function.get("meta", {}).get(
            "signature", {}).get("parameters")
        if (not isinstance(post_parameters, list) or len(post_parameters) != 1 or
                post_parameters[0].get("name") != "self"):
            return None, sorted(set(reasons + [
                "generated-dataclass-post-init-signature-not-self-only"]))
    elif any(target_descriptor.get(key) is not None for key in (
            "numeric_function_id", "current_pzvt_function_id")):
        raise WholeProgramVMError(
            "PZWV265", "generated dataclass has spurious post-init target")
    expected_numeric_targets = ([post_function_id]
                                if post_function_id is not None else [])
    if descriptor.get("target_numeric_function_ids") != expected_numeric_targets:
        raise WholeProgramVMError(
            "PZWV265", "generated dataclass numeric target mismatch")
    if reasons:
        return None, sorted(set(reasons))
    operands = [by_parameter[name] for name in expected_names]
    return {
        "target": post_init,
        "target_pzvt_function_id": post_function_id,
        "binding_mode": "generated-dataclass-init",
        "generated_dataclass_init": copy.deepcopy(dict(schema)),
        "target_parameter_names": expected_names,
        "field_names": field_names,
        "call_argument_operands": operands,
        "signature_parameter_count": len(parameters),
        "argument_operand_count": len(operands),
        "parameter_order_exact": True,
        "only_invocation_is_replaced": True,
        "constructor_sequence_consumed": False,
        "constructed_class": None,
    }, []


def _abi_direct_call_plan(
        descriptor: Mapping[str, Any], occurrence: Mapping[str, Any],
        item: Mapping[str, Any], *,
        actual_provenance: Mapping[str, Any],
        graph_site: Mapping[str, Any],
        function_specs: Mapping[str, Mapping[str, Any]],
        function_ids: Mapping[str, int], lowering_signatures: Mapping[str, Any],
        ) -> tuple[dict[str, Any] | None, list[str]]:
    index = occurrence.get("cfg_occurrence_index")
    expected_identity = {
        "cfg_occurrence_index": index,
        "numeric_call_site_id": occurrence.get("numeric_call_site_id"),
        "call_site_id": occurrence.get("call_site_id"),
        "caller": occurrence.get("caller"),
        "span": occurrence.get("span"),
    }
    if any(descriptor.get(key) != value
           for key, value in expected_identity.items()):
        raise WholeProgramVMError(
            "PZWV264", f"ABI descriptor/occurrence identity mismatch: {index}")
    if (descriptor.get("numeric_abi_descriptor_id") != index or
            descriptor.get("caller_numeric_function_id") !=
            function_ids.get(str(occurrence.get("caller"))) or
            item.get("destination") != occurrence.get("destination") or
            item.get("span") != occurrence.get("span")):
        raise WholeProgramVMError(
            "PZWV264", f"ABI descriptor differs from CFG occurrence: {index}")
    arguments = item.get("arguments")
    layout = occurrence.get("argument_layout")
    attributes = item.get("attributes")
    if not isinstance(arguments, list) or not arguments or not isinstance(
            layout, list) or not isinstance(attributes, Mapping):
        raise WholeProgramVMError("PZWV264", "ABI call operands malformed")
    raw_layout = attributes.get("argument_layout")
    argument_count = attributes.get("argument_count")
    if (not isinstance(raw_layout, (list, tuple)) or
            not isinstance(argument_count, int) or
            argument_count != len(raw_layout) or
            len(arguments) != argument_count + 1):
        raise WholeProgramVMError(
            "PZWV264", "CFG python-call argument layout/count is malformed")
    cfg_layout: list[dict[str, Any]] = []
    for layout_index, raw_entry in enumerate(raw_layout):
        if (not isinstance(raw_entry, (list, tuple)) or
                len(raw_entry) != 2 or raw_entry[0] not in {
                    "positional", "keyword", "star-positional",
                    "star-keyword"} or
                (raw_entry[0] == "keyword" and
                 not isinstance(raw_entry[1], str))):
            raise WholeProgramVMError(
                "PZWV264", "CFG python-call argument layout entry malformed")
        cfg_layout.append({
            "argument_index": layout_index,
            "kind": str(raw_entry[0]),
            "keyword": raw_entry[1],
            "value": arguments[layout_index + 1],
        })
    if (arguments[0] != occurrence.get("callable_value") or
            layout != cfg_layout):
        raise WholeProgramVMError(
            "PZWV264", "ABI argument layout differs from CFG operands")

    reasons: list[str] = []
    generated_mode = (descriptor.get("binding_mode") ==
                      "generated-dataclass-init")
    expected_classification = ("proven-core-generated-dataclass-init"
                               if generated_mode else
                               "proven-single-internal")
    if (descriptor.get("classification") != expected_classification or
            descriptor.get("proven") is not True):
        reasons.append("not-proven-executable-internal")
    mode = str(descriptor.get("binding_mode"))
    if mode not in {
            "free", "bound-method", "common-dispatch", "classmethod",
            "constructor", "generated-dataclass-init"}:
        reasons.append(f"unsupported-binding-mode:{mode}")
    provenance = descriptor.get("callable_ssa_provenance")
    if not isinstance(provenance, Mapping) or provenance.get("status") != "exact":
        reasons.append("callable-ssa-provenance-not-exact")
    if provenance != actual_provenance:
        raise WholeProgramVMError(
            "PZWV265", "ABI callable SSA provenance differs from CFG")
    expected_evaluation_order = [{
        "evaluation_index": layout_index,
        "kind": row["kind"],
        "keyword": row["keyword"],
        "source_value": row["value"],
    } for layout_index, row in enumerate(cfg_layout)]
    if descriptor.get("argument_evaluation_order") != expected_evaluation_order:
        raise WholeProgramVMError(
            "PZWV264", "ABI evaluation order differs from CFG operands")
    descriptor_blockers = descriptor.get("blocker_codes")
    if not isinstance(descriptor_blockers, list):
        raise WholeProgramVMError("PZWV265", "ABI blocker list malformed")
    # PZCABI209 says at least one omitted argument needs its Python default.
    # The generic ABI pass intentionally does not interpret expressions.  The
    # executable backend can still prove and embed immutable literal defaults
    # from the independently matched CFG signature below.
    reasons.extend(f"abi-blocker:{code}" for code in descriptor_blockers
                   if code != "PZCABI209")
    targets = descriptor.get("target_descriptors")
    if not isinstance(targets, list):
        raise WholeProgramVMError("PZWV265", "ABI target descriptors malformed")
    resolution = _require_dict(
        graph_site.get("resolution"), "ABI graph-site resolution")
    graph_targets = _require_list(
        resolution.get("targets"), "ABI graph-site resolution targets")
    target_rows = [
        _require_dict(row, "ABI target descriptor") for row in targets]
    has_default_parameter_mapping = any(
        entry.get("source_kind") == "default"
        for target_row in target_rows
        for entry in target_row.get("parameter_destination_map", ())
        if isinstance(entry, Mapping))
    if ("PZCABI209" in descriptor_blockers and
            not has_default_parameter_mapping):
        reasons.append("abi-blocker:PZCABI209")
    if generated_mode:
        if (graph_site.get("call_site_id") != occurrence.get("call_site_id") or
                graph_site.get("caller") != occurrence.get("caller") or
                descriptor.get("classification") !=
                _resolution_classification(resolution) or
                descriptor.get("proven") is not True or
                descriptor.get("resolution_kind") !=
                "exact-generated-dataclass-init"):
            raise WholeProgramVMError(
                "PZWV265", "generated dataclass graph binding mismatch")
        return _abi_generated_dataclass_init_plan(
            descriptor, resolution, target_rows, cfg_layout,
            function_specs=function_specs, function_ids=function_ids,
            reasons=reasons)
    descriptor_targets = [
        _require_string(row.get("callable_id"), "ABI target callable")
        for row in target_rows]
    descriptor_numeric_targets = [
        row.get("numeric_function_id") for row in target_rows]
    if (graph_site.get("call_site_id") != occurrence.get("call_site_id") or
            graph_site.get("caller") != occurrence.get("caller") or
            descriptor.get("classification") !=
            _resolution_classification(resolution) or
            descriptor.get("proven") is not
            (resolution.get("proven") is True) or
            descriptor.get("resolution_kind") != resolution.get("kind") or
            descriptor_targets != graph_targets or
            descriptor.get("target_numeric_function_ids") !=
            descriptor_numeric_targets):
        raise WholeProgramVMError(
            "PZWV265", "ABI target/active-graph binding mismatch")
    if reasons:
        return None, sorted(set(reasons))
    if len(targets) != 1:
        raise WholeProgramVMError(
            "PZWV265", "proven-single ABI descriptor target count mismatch")
    target_descriptor = _require_dict(targets[0], "ABI target descriptor")
    target = _require_string(
        target_descriptor.get("callable_id"), "ABI target callable")
    if (target not in function_ids or
            target_descriptor.get("numeric_function_id") !=
            function_ids[target] or
            target_descriptor.get("proven_reachable") is not True or
            target_descriptor.get("current_pzvt_function_id") !=
            function_ids[target] or
            target_descriptor.get("binding_mode") != mode):
        raise WholeProgramVMError(
            "PZWV265", "ABI target/function table binding mismatch")
    target_blockers = target_descriptor.get("blocker_codes")
    if not isinstance(target_blockers, (list, tuple)):
        raise WholeProgramVMError("PZWV265", "ABI target blocker list malformed")
    non_default_target_blockers = [
        code for code in target_blockers
        if code != "PZCABI209" or not has_default_parameter_mapping]
    if non_default_target_blockers:
        return None, [f"target-abi-blocker:{code}" for code in
                      non_default_target_blockers]

    parameters, lowering_signature = _abi_signature_parameters(
        target, function_specs, lowering_signatures)
    if (lowering_signature.get("is_async") or
            lowering_signature.get("has_var_positional") or
            lowering_signature.get("has_var_keyword")):
        return None, ["async-or-variadic-target"]
    if any(row["kind"] not in {
            "positional-only", "positional-or-keyword", "keyword-only"}
            for row in parameters):
        return None, ["unsupported-target-parameter-kind"]
    cfg_signature = function_specs[target]["meta"]["signature"]
    decorators = list(cfg_signature.get("decorators", ()))
    if (mode == "classmethod" and
            (lowering_signature.get("is_classmethod") is not True or
             decorators != ["classmethod"])):
        return None, ["classmethod-decorator-contract-mismatch"]
    static_common_dispatch = (
        mode == "common-dispatch" and decorators == ["staticmethod"] and
        lowering_signature.get("is_staticmethod") is True)
    if (mode in {"bound-method", "common-dispatch"} and decorators and
            not static_common_dispatch):
        return None, ["bound-method-has-runtime-decorator"]
    if mode == "free" and decorators not in ([], ["staticmethod"]):
        return None, ["free-call-has-runtime-decorator"]
    if mode == "free" and lowering_signature.get("is_classmethod"):
        return None, ["free-call-target-is-classmethod"]
    if ((decorators == ["staticmethod"]) !=
            bool(lowering_signature.get("is_staticmethod"))):
        return None, ["staticmethod-decorator-contract-mismatch"]
    if any(block.get("terminator", {}).get("op") in {
            "suspend-yield", "suspend-yield-from", "yield", "yield-value"}
            for block in function_specs[target].get("blocks", ())):
        return None, ["generator-target"]

    # ``obj.static_method(...)`` still has an exact receiver lookup in the
    # source CFG, but Python's staticmethod descriptor does not bind that
    # receiver as an implicit argument.  The call ABI proves this distinction
    # with a parameter map containing explicit arguments only.  Treating every
    # common-dispatch lookup as a bound method needlessly pushed these exact
    # calls through the generic python-call adapter.
    receiver_lookup_modes = {
        "bound-method", "common-dispatch", "classmethod"}
    receiver_binding_modes = set(receiver_lookup_modes)
    if static_common_dispatch:
        receiver_binding_modes.remove("common-dispatch")
    implicit_modes = receiver_binding_modes | {"constructor"}
    receiver = descriptor.get("receiver_value")
    if mode in receiver_lookup_modes:
        if (not isinstance(provenance, Mapping) or
                provenance.get("source_kind") != "attribute" or
                provenance.get("receiver_status") != "exact" or
                receiver is None or
                provenance.get("receiver_value") != receiver):
            return None, ["bound-receiver-not-exact"]
    elif receiver is not None:
        raise WholeProgramVMError(
            "PZWV265", "non-receiver ABI unexpectedly carries a receiver")

    parameter_by_name = {str(row["name"]): row for row in parameters}
    implicit_count = 1 if mode in implicit_modes else 0
    positional_parameters = [row for row in parameters
                             if row["kind"] in {
                                 "positional-only",
                                 "positional-or-keyword"}]
    if implicit_count and not positional_parameters:
        raise WholeProgramVMError(
            "PZWV265", "ABI receiver target has no positional parameter")
    positional_cursor = implicit_count
    expected_argument_destinations: dict[int, str] = {}
    supplied_parameters = ({str(positional_parameters[0]["name"])}
                           if implicit_count else set())
    for evaluation_index, argument in enumerate(cfg_layout):
        kind = argument["kind"]
        if kind == "positional":
            if positional_cursor >= len(positional_parameters):
                raise WholeProgramVMError(
                    "PZWV265", "ABI call has an unexpected positional argument")
            destination_parameter = str(
                positional_parameters[positional_cursor]["name"])
            positional_cursor += 1
        elif kind == "keyword":
            destination_parameter = str(argument["keyword"])
            parameter = parameter_by_name.get(destination_parameter)
            if parameter is None or parameter["kind"] == "positional-only":
                raise WholeProgramVMError(
                    "PZWV265", "ABI call has an unexpected keyword argument")
        else:
            return None, [f"unsupported-argument-layout:{kind}"]
        if destination_parameter in supplied_parameters:
            raise WholeProgramVMError(
                "PZWV265", "ABI call supplies a parameter more than once")
        supplied_parameters.add(destination_parameter)
        expected_argument_destinations[evaluation_index] = (
            destination_parameter)
    parameter_map = target_descriptor.get("parameter_destination_map")
    if not isinstance(parameter_map, list) or len(parameter_map) != len(parameters):
        raise WholeProgramVMError(
            "PZWV265", "ABI parameter map/count mismatch")
    by_parameter: dict[str, Any] = {}
    seen_evaluation_indexes: set[int] = set()
    literal_parameters: set[str] = set()
    for entry in parameter_map:
        if not isinstance(entry, Mapping):
            raise WholeProgramVMError("PZWV265", "ABI parameter map malformed")
        parameter = entry.get("destination_parameter")
        if not isinstance(parameter, str) or parameter in by_parameter:
            raise WholeProgramVMError(
                "PZWV265", "ABI parameter destination is duplicate/missing")
        source_kind = entry.get("source_kind")
        expected_parameter = parameter_by_name.get(parameter)
        if (expected_parameter is None or
                entry.get("destination_kind") !=
                expected_parameter["kind"]):
            raise WholeProgramVMError(
                "PZWV265", "ABI parameter destination kind mismatch")
        if source_kind == "receiver":
            if (mode not in receiver_binding_modes or
                    entry.get("evaluation_index") != -1 or
                    entry.get("source_value") != receiver):
                raise WholeProgramVMError(
                    "PZWV265", "ABI receiver parameter mapping mismatch")
        elif source_kind == "allocated-object":
            if (mode != "constructor" or entry.get("evaluation_index") != -1 or
                    entry.get("source_value") != "$allocated-object"):
                raise WholeProgramVMError(
                    "PZWV265", "ABI allocated-object mapping mismatch")
            by_parameter[parameter] = "$allocated-object"
            continue
        elif source_kind == "argument":
            evaluation_index = entry.get("evaluation_index")
            if (not isinstance(evaluation_index, int) or
                    not (0 <= evaluation_index < len(layout)) or
                    evaluation_index in seen_evaluation_indexes or
                    parameter != expected_argument_destinations.get(
                        evaluation_index) or
                    entry.get("keyword") !=
                    cfg_layout[evaluation_index]["keyword"] or
                    entry.get("source_value") !=
                    layout[evaluation_index].get("value")):
                raise WholeProgramVMError(
                    "PZWV265", "ABI explicit argument mapping mismatch")
            seen_evaluation_indexes.add(evaluation_index)
        elif source_kind == "default":
            if (expected_parameter.get("has_default") is not True or
                    parameter in supplied_parameters or
                    entry.get("evaluation_index") is not None or
                    entry.get("source_value") !=
                    expected_parameter.get("default_ast_sha256")):
                raise WholeProgramVMError(
                    "PZWV265", "ABI default parameter mapping mismatch")
            literal, value = _immutable_literal_default(expected_parameter)
            if not literal:
                return None, ["abi-blocker:PZCABI209"]
            by_parameter[parameter] = value
            literal_parameters.add(parameter)
            continue
        else:
            return None, [f"unsupported-parameter-source:{source_kind}"]
        by_parameter[parameter] = entry.get("source_value")
    expected_names = [str(row["name"]) for row in parameters]
    if (set(by_parameter) != set(expected_names) or
            seen_evaluation_indexes != set(range(len(layout)))):
        raise WholeProgramVMError(
            "PZWV265", "ABI parameter map is not statically complete")
    if (mode in receiver_binding_modes and
            parameter_map[0].get("source_kind") != "receiver"):
        raise WholeProgramVMError(
            "PZWV265", "ABI implicit receiver is not the first parameter")
    if mode == "free" and any(
            row.get("source_kind") == "receiver" for row in parameter_map):
        raise WholeProgramVMError(
            "PZWV265", "free-call ABI unexpectedly binds a receiver")
    if mode == "constructor":
        if (not parameter_map or
                parameter_map[0].get("source_kind") != "allocated-object"):
            raise WholeProgramVMError(
                "PZWV265", "ABI allocated object is not the first parameter")
        resolution_class = resolution.get("constructed_class")
        sequence = descriptor.get("constructor_sequence")
        expected_sequence = [
            {"step": 0, "operation": "allocate-instance",
             "constructed_class": resolution_class,
             "result": "$allocated-object"},
            {"step": 1, "operation": "bind-init-self",
             "value": "$allocated-object"},
            {"step": 2, "operation": "invoke-__init__",
             "required_return": None,
             "target_numeric_function_ids": [function_ids[target]]},
            {"step": 3, "operation": "return-allocated-instance",
             "value": "$allocated-object"},
        ]
        if (not isinstance(resolution_class, str) or
                sequence != expected_sequence or
                function_specs[target]["meta"].get("function") != "__init__"):
            raise WholeProgramVMError(
                "PZWV265", "ABI constructor sequence/target mismatch")
        ordered_operands = [by_parameter[name] for name in expected_names[1:]]
    else:
        if descriptor.get("constructor_sequence") is not None:
            raise WholeProgramVMError(
                "PZWV265", "non-constructor ABI carries constructor sequence")
        ordered_operands = [by_parameter[name] for name in expected_names]
    if len(ordered_operands) != len(parameters) - (1 if mode == "constructor" else 0):
        raise WholeProgramVMError("PZWV265", "ABI operand count mismatch")
    return {
        "target": target,
        "target_pzvt_function_id": function_ids[target],
        "binding_mode": mode,
        "target_parameter_names": expected_names,
        "call_argument_operands": ordered_operands,
        "literal_argument_indexes": [
            index for index, name in enumerate(
                expected_names[1:] if mode == "constructor" else expected_names)
            if name in literal_parameters],
        "signature_parameter_count": len(parameters),
        "argument_operand_count": len(ordered_operands),
        "parameter_order_exact": True,
        "only_invocation_is_replaced": True,
        "constructor_sequence_consumed": mode == "constructor",
        "constructed_class": (resolution.get("constructed_class")
                              if mode == "constructor" else None),
    }, []


def _abi_runtime_bound_finite_candidate_plan(
        target: str, target_row: Mapping[str, Any],
        occurrence: Mapping[str, Any], item: Mapping[str, Any], *,
        actual_provenance: Mapping[str, Any],
        function_specs: Mapping[str, Mapping[str, Any]],
        function_ids: Mapping[str, int], lowering_signatures: Mapping[str, Any],
        ) -> tuple[dict[str, Any] | None, list[str]]:
    """Rebind a locally held *bound* method without inventing its receiver.

    A callback parameter is represented by ``load-name``.  Its bound receiver
    therefore is part of the runtime callable object rather than an SSA local.
    This path is permitted only when the ordinary free-call ABI failed solely
    because exactly one required parameter is absent and rebinding the exact
    source argument layout after a synthetic receiver fills the full method
    signature.  The receiver itself is obtained later by a checked adapter.
    """
    if (actual_provenance.get("status") != "exact" or
            actual_provenance.get("source_kind") != "name" or
            target_row.get("binding_mode") != "free" or
            target_row.get("blocker_codes") != ["PZCABI208"]):
        return None, ["finite-runtime-bound-callback-shape-not-proven"]
    parameters, lowering_signature = _abi_signature_parameters(
        target, function_specs, lowering_signatures)
    meta = function_specs[target].get("meta")
    cfg_signature = meta.get("signature") if isinstance(meta, Mapping) else None
    if (not isinstance(meta, Mapping) or
            not isinstance(meta.get("class"), str) or
            not isinstance(cfg_signature, Mapping) or
            list(cfg_signature.get("decorators", ())) or
            lowering_signature.get("is_async") or
            lowering_signature.get("is_classmethod") or
            lowering_signature.get("is_staticmethod") or
            lowering_signature.get("has_var_positional") or
            lowering_signature.get("has_var_keyword") or
            not parameters or parameters[0].get("name") != "self" or
            any(row.get("kind") != "positional-or-keyword" or
                row.get("has_default") for row in parameters) or
            any(block.get("terminator", {}).get("op") in {
                "suspend-yield", "suspend-yield-from", "yield", "yield-value"}
                for block in function_specs[target].get("blocks", ()))):
        return None, ["finite-runtime-bound-target-not-simple-method"]

    layout = occurrence.get("argument_layout")
    arguments = item.get("arguments")
    parameter_map = target_row.get("parameter_destination_map")
    if (not isinstance(layout, list) or not isinstance(arguments, list) or
            len(arguments) != len(layout) + 1 or
            not isinstance(parameter_map, list) or
            len(parameter_map) != len(parameters) or
            target_row.get("explicit_argument_evaluation_order") != [
                row.get("value") for row in layout
                if isinstance(row, Mapping)] or
            sum(isinstance(row, Mapping) and
                row.get("source_kind") == "missing-required"
                for row in parameter_map) != 1 or
            any(not isinstance(row, Mapping) or row.get("source_kind") not in {
                "argument", "missing-required"} for row in parameter_map)):
        return None, ["finite-runtime-bound-free-binding-shape-mismatch"]
    mapped_indexes = {
        row.get("evaluation_index") for row in parameter_map
        if row.get("source_kind") == "argument"}
    if (mapped_indexes != set(range(len(layout))) or
            any(type(row.get("evaluation_index")) is not int or
                not 0 <= row["evaluation_index"] < len(layout)
                for row in parameter_map
                if row.get("source_kind") == "argument")):
        return None, ["finite-runtime-bound-free-binding-shape-mismatch"]
    for row in parameter_map:
        evaluation_index = row.get("evaluation_index")
        if row.get("source_kind") == "argument" and (
                not isinstance(evaluation_index, int) or
                row.get("source_value") != layout[evaluation_index].get(
                    "value")):
            return None, ["finite-runtime-bound-free-binding-shape-mismatch"]

    parameter_names = [str(row["name"]) for row in parameters]
    parameter_by_name = {str(row["name"]): row for row in parameters}
    by_parameter: dict[str, Any] = {
        parameter_names[0]: "$runtime-bound-receiver"}
    positional_cursor = 1
    for evaluation_index, raw_argument in enumerate(layout):
        if not isinstance(raw_argument, Mapping):
            return None, ["finite-runtime-bound-argument-layout-malformed"]
        kind = raw_argument.get("kind")
        if kind == "positional":
            if positional_cursor >= len(parameters):
                return None, ["finite-runtime-bound-has-extra-positional"]
            parameter = parameter_names[positional_cursor]
            positional_cursor += 1
        elif kind == "keyword":
            parameter = raw_argument.get("keyword")
            if not isinstance(parameter, str) or parameter not in parameter_by_name:
                return None, ["finite-runtime-bound-has-unknown-keyword"]
        else:
            return None, [f"unsupported-argument-layout:{kind}"]
        if parameter in by_parameter:
            return None, ["finite-runtime-bound-parameter-supplied-twice"]
        value = raw_argument.get("value")
        if arguments[evaluation_index + 1] != value:
            raise WholeProgramVMError(
                "PZWV268", "finite runtime-bound CFG operand mismatch")
        by_parameter[parameter] = value
    if set(by_parameter) != set(parameter_names):
        return None, ["finite-runtime-bound-parameter-map-incomplete"]
    explicit_operands = [by_parameter[name] for name in parameter_names[1:]]
    return {
        "target": target,
        "target_pzvt_function_id": function_ids[target],
        "binding_mode": "runtime-bound-method",
        "target_parameter_names": parameter_names,
        "call_argument_operands": explicit_operands,
        "argument_operand_count": len(explicit_operands) + 1,
        "runtime_bound_receiver_required": True,
    }, []


def _abi_finite_dispatch_plan(
        descriptor: Mapping[str, Any], occurrence: Mapping[str, Any],
        item: Mapping[str, Any], *,
        actual_provenance: Mapping[str, Any],
        graph_site: Mapping[str, Any],
        function_specs: Mapping[str, Mapping[str, Any]],
        function_ids: Mapping[str, int],
        abi_numeric_function_ids: Mapping[str, int],
        guarded_callable_ids: frozenset[str],
        guarded_lexical_owner_ids: Mapping[str, str | None],
        lowering_signatures: Mapping[str, Any],
        ) -> tuple[dict[str, Any] | None, list[str]]:
    """Validate one finite call and retain its mandatory runtime guard.

    Each candidate is independently passed through the exact direct-call ABI
    validator.  The candidate set is never promoted to a static edge: PZVT
    asks the target object model to select the identity at runtime, validates
    the returned index, and only then pushes that candidate's bound frame.
    """
    resolution = _require_dict(
        graph_site.get("resolution"), "finite graph-site resolution")
    graph_targets = _require_list(
        resolution.get("targets"), "finite graph-site targets")
    target_rows = _require_list(
        descriptor.get("target_descriptors"), "finite ABI targets")
    descriptor_targets = [
        _require_string(_require_dict(row, "finite ABI target").get(
            "callable_id"), "finite ABI target callable")
        for row in target_rows]
    table = _require_dict(
        descriptor.get("finite_dispatch_table"), "finite dispatch table")
    table_entries = _require_list(
        table.get("entries"), "finite dispatch entries")
    expected_entries = [{
        "callable_id": target,
        "numeric_function_id": _require_dict(
            row, "finite ABI target").get("numeric_function_id"),
        "current_pzvt_function_id": _require_dict(
            row, "finite ABI target").get("current_pzvt_function_id"),
    } for target, row in zip(descriptor_targets, target_rows)]
    if (descriptor.get("classification") != "finite-non-proven" or
            descriptor.get("proven") is not False or
            descriptor.get("resolution_kind") != "finite-dynamic-dispatch" or
            resolution.get("kind") != "finite-dynamic-dispatch" or
            resolution.get("proven") is not False or
            graph_site.get("call_site_id") != occurrence.get("call_site_id") or
            graph_site.get("caller") != occurrence.get("caller") or
            descriptor_targets != graph_targets or not descriptor_targets or
            descriptor.get("target_numeric_function_ids") != [
                row["numeric_function_id"] for row in expected_entries] or
            table.get("proven") is not False or
            table.get("runtime_identity_guard_required") is not True or
            table.get("candidate_set_is_not_a_reachability_edge") is not True or
            table_entries != expected_entries):
        raise WholeProgramVMError(
            "PZWV268", "finite dispatch graph/ABI/table binding mismatch")
    blockers = descriptor.get("blocker_codes")
    runtime_bound = blockers == ["PZCABI204", "PZCABI208"]
    guarded_only = blockers == ["PZCABI204", "PZCABI212"]
    if blockers != ["PZCABI204"] and not runtime_bound and not guarded_only:
        return None, [f"abi-blocker:{code}" for code in
                      blockers if isinstance(code, str)] if isinstance(
                          blockers, list) else ["finite-blocker-list-malformed"]

    candidates: list[dict[str, Any]] = []
    expected_target_blockers = ["PZCABI208"] if runtime_bound else []
    for target, raw_target in zip(descriptor_targets, target_rows):
        target_row = _require_dict(raw_target, "finite ABI target")
        target_is_guarded = target in guarded_callable_ids
        target_lexical_owner = guarded_lexical_owner_ids.get(target)
        abi_lexical_owner = target_row.get("lexical_owner")
        lexical_owner_binding = (
            (target_lexical_owner is None and abi_lexical_owner is None) or
            (isinstance(abi_lexical_owner, Mapping) and
             abi_lexical_owner.get("callable_id") == target_lexical_owner and
             abi_lexical_owner.get("current_pzvt_function_id") ==
             function_ids.get(target_lexical_owner)))
        guarded_binding = (
            guarded_only and
            target_row.get("numeric_function_id") ==
            abi_numeric_function_ids.get(target) and
            target_row.get("current_pzvt_function_id") is None and
            target_row.get("proven_reachable") is False and
            lexical_owner_binding)
        proven_binding = (
            target_row.get("numeric_function_id") == function_ids.get(target) and
            target_row.get("current_pzvt_function_id") ==
            function_ids.get(target) and
            target_row.get("proven_reachable") is True)
        if (target not in function_ids or
                not (guarded_binding if target_is_guarded else
                     proven_binding) or
                target_row.get("blocker_codes") != expected_target_blockers):
            return None, ["finite-target-not-current-and-bindable"]
        synthetic_resolution = copy.deepcopy(dict(resolution))
        synthetic_resolution.update({
            "kind": "exact-internal-function",
            "proven": True,
            "targets": [target],
        })
        synthetic_site = copy.deepcopy(dict(graph_site))
        synthetic_site["resolution"] = synthetic_resolution
        synthetic_target_row = copy.deepcopy(dict(target_row))
        synthetic_target_row.update({
            "numeric_function_id": function_ids[target],
            "current_pzvt_function_id": function_ids[target],
            "proven_reachable": True,
        })
        synthetic_descriptor = copy.deepcopy(dict(descriptor))
        synthetic_descriptor.update({
            "classification": "proven-single-internal",
            "proven": True,
            "resolution_kind": "exact-internal-function",
            "target_descriptors": [synthetic_target_row],
            "target_numeric_function_ids": [function_ids[target]],
            "finite_dispatch_table": None,
            "blocker_codes": [],
        })
        direct, reasons = _abi_direct_call_plan(
            synthetic_descriptor, occurrence, item,
            actual_provenance=actual_provenance,
            graph_site=synthetic_site, function_specs=function_specs,
            function_ids=function_ids,
            lowering_signatures=lowering_signatures)
        if runtime_bound:
            if direct is not None or reasons != [
                    "target-abi-blocker:PZCABI208"]:
                return None, ["finite-runtime-bound-original-blocker-mismatch"]
            direct, reasons = _abi_runtime_bound_finite_candidate_plan(
                target, target_row, occurrence, item,
                actual_provenance=actual_provenance,
                function_specs=function_specs, function_ids=function_ids,
                lowering_signatures=lowering_signatures)
        if direct is None or reasons:
            return None, [f"finite-target:{reason}" for reason in reasons]
        if direct["binding_mode"] in {
                "constructor", "generated-dataclass-init"}:
            return None, ["finite-target-unsupported-binding-mode"]
        candidates.append({
            "target": direct["target"],
            "target_pzvt_function_id": direct["target_pzvt_function_id"],
            "binding_mode": direct["binding_mode"],
            "target_parameter_names": list(direct["target_parameter_names"]),
            "call_argument_operands": list(direct["call_argument_operands"]),
            "literal_argument_indexes": list(direct.get(
                "literal_argument_indexes", [])),
            "argument_operand_count": direct["argument_operand_count"],
            "runtime_bound_receiver_required": direct.get(
                "runtime_bound_receiver_required", False),
            "guarded_only_target": target_is_guarded,
            "lexical_owner_callable_id": target_lexical_owner,
        })

    descriptor_provenance = descriptor.get("callable_ssa_provenance")
    if not isinstance(descriptor_provenance, Mapping):
        raise WholeProgramVMError(
            "PZWV268", "finite dispatch callable provenance is not an object")
    callable_value = descriptor_provenance.get("callable_value")
    arguments = item.get("arguments")
    if (not isinstance(callable_value, str) or
            not isinstance(arguments, list) or not arguments or
            arguments[0] != callable_value):
        raise WholeProgramVMError(
            "PZWV268", "finite dispatch callable operand mismatch")
    lexical_dispatch = any(
        row.get("lexical_owner_callable_id") is not None
        for row in candidates)
    if lexical_dispatch and any(
            row.get("lexical_owner_callable_id") is None
            for row in candidates):
        return None, ["finite-mixed-lexical-candidate-set"]
    return {
        "binding_mode": (
            "finite-bound-dispatch" if runtime_bound else
            "finite-lexical-dispatch" if lexical_dispatch else
            "finite-dispatch"),
        "source_binding_mode": descriptor.get("binding_mode"),
        "call_site_id": occurrence.get("call_site_id"),
        "callable_operand": callable_value,
        "candidates": candidates,
        "runtime_identity_guard_required": True,
        "runtime_bound_receiver_required": runtime_bound,
        "guarded_only_candidate_set": guarded_only,
        "candidate_set_is_not_a_static_edge": True,
        "only_invocation_is_replaced": True,
    }, []


def _generated_dataclass_super_preparation_indexes(
        block: Mapping[str, Any], outer_index: int,
        ) -> list[int]:
    """Prove the five single-use SSA operations implementing ``super()``."""
    instructions = block.get("instructions")
    terminator = block.get("terminator")
    if (not isinstance(instructions, list) or
            not (0 <= outer_index < len(instructions)) or
            not isinstance(terminator, Mapping)):
        raise WholeProgramVMError(
            "PZWV265", "generated dataclass preparation block is malformed")

    def defining(value: Any) -> tuple[int, Mapping[str, Any]]:
        matches = [(index, row) for index, row in enumerate(instructions)
                   if index < outer_index and isinstance(row, Mapping) and
                   row.get("destination") == value]
        if len(matches) != 1:
            raise WholeProgramVMError(
                "PZWV265", "generated dataclass preparation definition is not unique")
        return matches[0]

    outer = _require_dict(instructions[outer_index],
                          "generated dataclass outer call")
    outer_arguments = outer.get("arguments")
    if (outer.get("op") != "python-call" or
            not isinstance(outer_arguments, list) or not outer_arguments):
        raise WholeProgramVMError(
            "PZWV265", "generated dataclass outer call is malformed")
    require_index, require = defining(outer_arguments[0])
    require_arguments = require.get("arguments")
    if (require.get("op") != "require-callable" or
            not isinstance(require_arguments, list) or
            len(require_arguments) != 1):
        raise WholeProgramVMError(
            "PZWV265", "generated dataclass outer callable proof mismatch")
    attribute_index, attribute = defining(require_arguments[0])
    attribute_arguments = attribute.get("arguments")
    if (attribute.get("op") != "load-attribute" or
            not isinstance(attribute_arguments, list) or
            len(attribute_arguments) != 2 or
            attribute_arguments[1] != "__init__"):
        raise WholeProgramVMError(
            "PZWV265", "generated dataclass attribute proof mismatch")
    super_call_index, super_call = defining(attribute_arguments[0])
    super_arguments = super_call.get("arguments")
    super_attributes = super_call.get("attributes")
    if (super_call.get("op") != "python-call" or
            not isinstance(super_arguments, list) or
            len(super_arguments) != 1 or
            not isinstance(super_attributes, Mapping) or
            super_attributes.get("argument_count") != 0 or
            list(super_attributes.get("argument_layout", ())) != []):
        raise WholeProgramVMError(
            "PZWV265", "generated dataclass zero-argument super proof mismatch")
    inner_require_index, inner_require = defining(super_arguments[0])
    inner_require_arguments = inner_require.get("arguments")
    if (inner_require.get("op") != "require-callable" or
            not isinstance(inner_require_arguments, list) or
            len(inner_require_arguments) != 1):
        raise WholeProgramVMError(
            "PZWV265", "generated dataclass super callable proof mismatch")
    load_index, load = defining(inner_require_arguments[0])
    if load.get("op") != "load-name" or load.get("arguments") != ["super"]:
        raise WholeProgramVMError(
            "PZWV265", "generated dataclass super name proof mismatch")

    chain = [load_index, inner_require_index, super_call_index,
             attribute_index, require_index]
    destinations = [instructions[index].get("destination") for index in chain]
    expected_consumers = [inner_require_index, super_call_index,
                          attribute_index, require_index, outer_index]
    for value, expected_consumer in zip(destinations, expected_consumers):
        uses = [index for index, row in enumerate(instructions)
                if isinstance(row, Mapping) and
                isinstance(row.get("arguments"), list) and
                value in row["arguments"]]
        if value in terminator.get("arguments", ()):
            uses.append(len(instructions))
        if uses != [expected_consumer]:
            raise WholeProgramVMError(
                "PZWV265", "generated dataclass preparation SSA is not single-use")
    return chain


def _prepare_call_abi_units(
        document: Mapping[str, Any], functions: Sequence[dict[str, Any]],
        units: Sequence[dict[str, Any]], lowering: Mapping[str, Any],
        call_abi: Mapping[str, Any],
        ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    prepared = copy.deepcopy(list(units))
    functions_by_callable = {
        str(row["callable_id"]): row for row in functions}
    document_functions = {
        str(row["callable_id"]): row for row in document["functions"]}
    graph_sites = _require_list(
        document.get("reachable_call_sites"), "reachable graph call sites")
    graph_by_site = {
        str(row["call_site_id"]): row
        for raw_row in graph_sites
        for row in (_require_dict(raw_row, "reachable graph call site"),)
    }
    function_ids = {str(row["callable_id"]): index
                    for index, row in enumerate(functions)}
    guarded_callable_ids = frozenset(str(value) for value in
                                     document.get("guarded_callable_ids", ()))
    guarded_lexical_owner_ids = {
        str(row["callable_id"]): row.get("lexical_owner_callable_id")
        for raw_row in document.get("guarded_callable_table", ())
        for row in (_require_dict(raw_row, "guarded callable row"),)
    }
    abi_numeric_function_ids: dict[str, int] = {}
    for raw_row in _require_list(
            call_abi.get("function_id_table"), "call ABI function table"):
        row = _require_dict(raw_row, "call ABI function row")
        identifier = _require_string(
            row.get("callable_id"), "call ABI function callable_id")
        numeric_id = row.get("numeric_function_id")
        if not isinstance(numeric_id, int) or identifier in abi_numeric_function_ids:
            raise WholeProgramVMError(
                "PZWV271", "call ABI function identity is invalid/duplicate")
        abi_numeric_function_ids[identifier] = numeric_id
    unit_ids = {str(row["name"]): index for index, row in enumerate(prepared)}
    signatures = lowering.get("target_signatures")
    if not isinstance(signatures, Mapping):
        raise WholeProgramVMError("PZWV263", "lowering signatures malformed")
    legacy_specs = {
        str(row["callable_id"]): prepared[row["unit"]]["meta"]
        for row in functions
    }
    occurrences = _require_list(
        lowering.get("cfg_occurrences_in_cfg_order"),
        "lowering CFG occurrences")
    descriptors = _require_list(
        call_abi.get("occurrence_abi_descriptors_in_cfg_order"),
        "call ABI occurrence descriptors")
    if len(occurrences) != len(descriptors):
        raise WholeProgramVMError(
            "PZWV263", "call ABI occurrence count differs from lowering")
    descriptors_by_index: dict[int, dict[str, Any]] = {}
    for raw_descriptor in descriptors:
        descriptor = _require_dict(raw_descriptor, "call ABI descriptor")
        index = descriptor.get("cfg_occurrence_index")
        if (not isinstance(index, int) or index in descriptors_by_index or
                not (0 <= index < len(occurrences))):
            raise WholeProgramVMError(
                "PZWV263", "call ABI occurrence index is invalid/duplicate")
        descriptors_by_index[index] = descriptor
    if set(descriptors_by_index) != set(range(len(occurrences))):
        raise WholeProgramVMError(
            "PZWV263", "call ABI occurrence index set is incomplete")

    matched_locations: set[tuple[int, int, int]] = set()
    seen_sites: set[str] = set()
    matched_graph_sites: set[str] = set()
    exact_internal_occurrences = 0
    eligible_instructions = 0
    lowered_instructions = 0
    direct_core_instructions = 0
    finite_dispatch_instructions = 0
    finite_bound_dispatch_instructions = 0
    finite_lexical_dispatch_instructions = 0
    constructor_instructions = 0
    generated_dataclass_instructions = 0
    consumed_callable_preparation_instructions = 0
    consumed_python_call_preparation_instructions = 0
    consumed_call_sites: set[str] = set()
    legacy_lowered_instructions = 0
    legacy_lowered_sites: set[str] = set()
    occurrence_counts_by_site: dict[str, int] = {}
    eligible_counts_by_site: dict[str, int] = {}
    lowered_counts_by_site: dict[str, int] = {}
    direct_counts_by_site: dict[str, int] = {}
    finite_dispatch_counts_by_site: dict[str, int] = {}
    finite_bound_dispatch_counts_by_site: dict[str, int] = {}
    finite_lexical_dispatch_counts_by_site: dict[str, int] = {}
    reason_counts: dict[str, int] = {}
    guarded_body_adapter_instructions = 0
    guarded_body_adapter_sites: set[str] = set()
    binding_rows: list[dict[str, Any]] = []
    definition_indexes: dict[int, DominatingDefinitions] = {}
    for expected_index, raw_occurrence in enumerate(occurrences):
        occurrence = _require_dict(raw_occurrence, "call lowering occurrence")
        if occurrence.get("cfg_occurrence_index") != expected_index:
            raise WholeProgramVMError(
                "PZWV263", "lowering occurrence order/index mismatch")
        descriptor = descriptors_by_index[expected_index]
        (unit_index, block_index, instruction_index, item,
         actual_provenance) = (
            _call_abi_occurrence_instruction(
                occurrence, functions_by_callable=functions_by_callable,
                units=prepared, unit_ids=unit_ids,
                document_functions=document_functions,
                definition_indexes=definition_indexes))
        location = (unit_index, block_index, instruction_index)
        if location in matched_locations:
            raise WholeProgramVMError(
                "PZWV264", "two ABI occurrences point to one CFG instruction")
        matched_locations.add(location)
        site_id = _require_string(
            occurrence.get("call_site_id"), "occurrence call_site_id")
        graph_site = graph_by_site.get(site_id)
        if graph_site is None:
            raise WholeProgramVMError(
                "PZWV264", f"ABI occurrence has no graph site: {site_id}")
        seen_sites.add(site_id)
        matched_graph_sites.add(site_id)
        occurrence_counts_by_site[site_id] = (
            occurrence_counts_by_site.get(site_id, 0) + 1)
        if _safe_direct_python_target(item, graph_site, legacy_specs) is not None:
            legacy_lowered_instructions += 1
            legacy_lowered_sites.add(site_id)
        function_specs = {
            str(row["callable_id"]): prepared[row["unit"]]
            for row in functions}
        if descriptor.get("classification") == "finite-non-proven":
            plan, reasons = _abi_finite_dispatch_plan(
                descriptor, occurrence, item,
                actual_provenance=actual_provenance,
                graph_site=graph_site, function_specs=function_specs,
                function_ids=function_ids,
                abi_numeric_function_ids=abi_numeric_function_ids,
                guarded_callable_ids=guarded_callable_ids,
                guarded_lexical_owner_ids=guarded_lexical_owner_ids,
                lowering_signatures=signatures)
        else:
            plan, reasons = _abi_direct_call_plan(
                descriptor, occurrence, item,
                actual_provenance=actual_provenance, graph_site=graph_site,
                function_specs=function_specs, function_ids=function_ids,
                lowering_signatures=signatures)
        if descriptor.get("classification") == "proven-single-internal":
            exact_internal_occurrences += 1
        binding = {
            "numeric_abi_descriptor_id": expected_index,
            "cfg_occurrence_index": expected_index,
            "cfg_path": copy.deepcopy(occurrence["cfg_path"]),
            "numeric_call_site_id": occurrence.get("numeric_call_site_id"),
            "call_site_id": site_id,
            "caller": occurrence.get("caller"),
            "resolution_kind": descriptor.get("resolution_kind"),
            "binding_mode": descriptor.get("binding_mode"),
            "targets": [row.get("callable_id") for row in
                        descriptor.get("target_descriptors", ())
                        if isinstance(row, Mapping)],
        }
        item["_target_call_site"] = binding
        if plan is not None:
            eligible_instructions += 1
            lowered_instructions += 1
            eligible_counts_by_site[site_id] = (
                eligible_counts_by_site.get(site_id, 0) + 1)
            lowered_counts_by_site[site_id] = (
                lowered_counts_by_site.get(site_id, 0) + 1)
            item["_target_call_abi"] = copy.deepcopy(plan)
            if plan["binding_mode"] in _FINITE_DISPATCH_MODES:
                finite_dispatch_instructions += 1
                finite_dispatch_counts_by_site[site_id] = (
                    finite_dispatch_counts_by_site.get(site_id, 0) + 1)
                mode = "abi-core-guarded-finite-dispatch"
                if plan["binding_mode"] == "finite-bound-dispatch":
                    finite_bound_dispatch_instructions += 1
                    finite_bound_dispatch_counts_by_site[site_id] = (
                        finite_bound_dispatch_counts_by_site.get(site_id, 0) +
                        1)
                    mode = "abi-core-guarded-finite-bound-dispatch"
                elif plan["binding_mode"] == "finite-lexical-dispatch":
                    finite_lexical_dispatch_instructions += 1
                    finite_lexical_dispatch_counts_by_site[site_id] = (
                        finite_lexical_dispatch_counts_by_site.get(
                            site_id, 0) + 1)
                    mode = "abi-core-guarded-finite-lexical-dispatch"
            else:
                direct_core_instructions += 1
                direct_counts_by_site[site_id] = (
                    direct_counts_by_site.get(site_id, 0) + 1)
                item["_target_direct_function"] = plan["target"]
                item["_target_call_arguments"] = list(
                    plan["call_argument_operands"])
            if plan["binding_mode"] == "constructor":
                constructor_instructions += 1
                mode = "abi-core-constructor"
            elif plan["binding_mode"] == "generated-dataclass-init":
                chain = _generated_dataclass_super_preparation_indexes(
                    prepared[unit_index]["blocks"][block_index],
                    instruction_index)
                for elided_index in chain:
                    elided = prepared[unit_index]["blocks"][block_index][
                        "instructions"][elided_index]
                    if not isinstance(elided, dict):
                        raise WholeProgramVMError(
                            "PZWV265", "generated dataclass preparation malformed")
                    elided["_target_elided"] = {
                        "kind": "generated-dataclass-super-preparation",
                        "consumer_cfg_occurrence_index": expected_index,
                    }
                inner_call = prepared[unit_index]["blocks"][block_index][
                    "instructions"][chain[2]]
                inner_binding = inner_call.get("_target_call_site")
                if not isinstance(inner_binding, Mapping) or not isinstance(
                        inner_binding.get("numeric_abi_descriptor_id"), int):
                    raise WholeProgramVMError(
                        "PZWV265", "generated dataclass inner super ABI is absent")
                inner_descriptor_index = int(inner_binding[
                    "numeric_abi_descriptor_id"])
                prior = next((entry for entry in binding_rows
                              if entry["numeric_abi_descriptor_id"] ==
                              inner_descriptor_index), None)
                if prior is None:
                    raise WholeProgramVMError(
                        "PZWV265", "generated dataclass inner super order mismatch")
                for reason in prior["unlowered_reasons"]:
                    remaining = reason_counts.get(reason, 0) - 1
                    if remaining > 0:
                        reason_counts[reason] = remaining
                    else:
                        reason_counts.pop(reason, None)
                prior["mode"] = "abi-consumed-callable-preparation"
                prior["unlowered_reasons"] = []
                prior["consumed_by_cfg_occurrence_index"] = expected_index
                prior["semantic_sha256"] = _sha256_json({
                    key: value for key, value in prior.items()
                    if key != "semantic_sha256"})
                consumed_call_sites.add(str(inner_binding["call_site_id"]))
                consumed_python_call_preparation_instructions += 1
                plan["consumed_callable_preparation_instruction_count"] = len(chain)
                plan["consumed_callable_preparation_instruction_indexes"] = chain
                item["_target_call_abi"] = copy.deepcopy(plan)
                consumed_callable_preparation_instructions += len(chain)
                generated_dataclass_instructions += 1
                mode = "abi-core-generated-dataclass-init"
            elif plan["binding_mode"] not in _FINITE_DISPATCH_MODES:
                mode = "abi-direct-core-call"
        else:
            for reason in reasons:
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
            mode = "abi-site-specific-adapter"
        row = {
            **binding,
            "mode": mode,
            "unlowered_reasons": reasons,
            "direct_call_plan": copy.deepcopy(plan),
        }
        row["semantic_sha256"] = _sha256_json(row)
        binding_rows.append(row)

    # Guard-only target bodies were deliberately outside the source-proven
    # call-site lowering pass.  Preserve each of their Python calls as an
    # occurrence-specific adapter instead of guessing a transitive edge.
    for unit_index, unit in enumerate(prepared):
        caller = str(functions[unit["owner"]]["callable_id"])
        if caller not in guarded_callable_ids:
            continue
        for block_index, cfg_block in enumerate(unit["blocks"]):
            for instruction_index, item in enumerate(cfg_block["instructions"]):
                if item.get("op") != "python-call":
                    continue
                location = (unit_index, block_index, instruction_index)
                if location in matched_locations:
                    raise WholeProgramVMError(
                        "PZWV271", "guarded body call unexpectedly has proven ABI")
                derived = _sha256_json({
                    "caller": caller,
                    "unit": unit.get("name"),
                    "block": cfg_block.get("name"),
                    "instruction": instruction_index,
                    "call": _call_instruction_proof(item),
                })
                site_id = f"guarded:{derived}"
                binding = {
                    "call_site_id": site_id,
                    "resolution_kind": "guarded-body-adapter",
                    "targets": [],
                    "guarded_only_caller": True,
                }
                item["_target_call_site"] = binding
                matched_locations.add(location)
                seen_sites.add(site_id)
                guarded_body_adapter_sites.add(site_id)
                guarded_body_adapter_instructions += 1
                reason = "guarded-body-not-in-proven-call-abi"
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
                row = {
                    "numeric_abi_descriptor_id": None,
                    "cfg_occurrence_index": None,
                    "cfg_path": [unit.get("name"), block_index,
                                 "instructions", instruction_index],
                    "numeric_call_site_id": None,
                    "call_site_id": site_id,
                    "caller": caller,
                    "resolution_kind": "guarded-body-adapter",
                    "binding_mode": "adapter",
                    "targets": [],
                    "mode": "guarded-body-site-specific-adapter",
                    "unlowered_reasons": [reason],
                    "direct_call_plan": None,
                }
                row["semantic_sha256"] = _sha256_json(row)
                binding_rows.append(row)

    python_locations = {
        (unit_index, block_index, instruction_index)
        for unit_index, unit in enumerate(prepared)
        for block_index, cfg_block in enumerate(unit["blocks"])
        for instruction_index, item in enumerate(cfg_block["instructions"])
        if item.get("op") == "python-call"
    }
    if python_locations != matched_locations:
        raise WholeProgramVMError(
            "PZWV264", "lowering/ABI does not cover every PZVT python-call")
    eligible_sites = {
        site_id for site_id, count in occurrence_counts_by_site.items()
        if eligible_counts_by_site.get(site_id, 0) == count}
    lowered_sites = {
        site_id for site_id, count in occurrence_counts_by_site.items()
        if lowered_counts_by_site.get(site_id, 0) == count}
    direct_sites = {
        site_id for site_id, count in occurrence_counts_by_site.items()
        if direct_counts_by_site.get(site_id, 0) == count}
    finite_dispatch_sites = {
        site_id for site_id, count in occurrence_counts_by_site.items()
        if finite_dispatch_counts_by_site.get(site_id, 0) == count}
    finite_bound_dispatch_sites = {
        site_id for site_id, count in occurrence_counts_by_site.items()
        if finite_bound_dispatch_counts_by_site.get(site_id, 0) == count}
    finite_lexical_dispatch_sites = {
        site_id for site_id, count in occurrence_counts_by_site.items()
        if finite_lexical_dispatch_counts_by_site.get(site_id, 0) == count}
    return prepared, {
        "call_abi_input_enabled": True,
        "active_call_site_lowering_semantic_sha256": lowering[
            "semantic_sha256"],
        "whole_program_vm_call_abi_semantic_sha256": call_abi[
            "semantic_sha256"],
        "python_call_instruction_count": len(python_locations),
        "python_call_site_count": len(seen_sites),
        "matched_call_graph_site_count": len(matched_graph_sites),
        "missing_call_graph_instruction_count": 0,
        "direct_call_instruction_count": direct_core_instructions,
        "direct_call_site_count": len(direct_sites),
        "direct_call_site_ids": sorted(direct_sites),
        "legacy_direct_call_instruction_count": legacy_lowered_instructions,
        "legacy_direct_call_site_count": len(legacy_lowered_sites),
        "abi_exact_internal_occurrence_count": exact_internal_occurrences,
        "abi_eligible_call_instruction_count": eligible_instructions,
        "abi_lowered_call_instruction_count": lowered_instructions,
        "abi_finite_dispatch_instruction_count": finite_dispatch_instructions,
        "abi_finite_dispatch_site_count": len(finite_dispatch_sites),
        "abi_finite_dispatch_site_ids": sorted(finite_dispatch_sites),
        "abi_finite_bound_dispatch_instruction_count": (
            finite_bound_dispatch_instructions),
        "abi_finite_bound_dispatch_site_count": len(
            finite_bound_dispatch_sites),
        "abi_finite_bound_dispatch_site_ids": sorted(
            finite_bound_dispatch_sites),
        "abi_finite_lexical_dispatch_instruction_count": (
            finite_lexical_dispatch_instructions),
        "abi_finite_lexical_dispatch_site_count": len(
            finite_lexical_dispatch_sites),
        "abi_finite_lexical_dispatch_site_ids": sorted(
            finite_lexical_dispatch_sites),
        "abi_constructor_call_instruction_count": constructor_instructions,
        "abi_generated_dataclass_init_instruction_count": (
            generated_dataclass_instructions),
        "abi_consumed_callable_preparation_instruction_count": (
            consumed_callable_preparation_instructions),
        "abi_consumed_python_call_preparation_instruction_count": (
            consumed_python_call_preparation_instructions),
        "abi_unlowered_call_instruction_count": (
            len(python_locations) - lowered_instructions -
            consumed_python_call_preparation_instructions),
        "abi_eligible_call_site_count": len(eligible_sites),
        "abi_lowered_call_site_count": len(lowered_sites),
        "abi_consumed_call_site_count": len(consumed_call_sites),
        "abi_unlowered_call_site_count": len(
            seen_sites - lowered_sites - consumed_call_sites),
        "abi_unlowered_reason_counts": dict(sorted(reason_counts.items())),
        "guarded_body_adapter_instruction_count": (
            guarded_body_adapter_instructions),
        "guarded_body_adapter_site_count": len(guarded_body_adapter_sites),
        "call_site_lowering": binding_rows,
    }


def _prepare_call_site_aware_units(
        document: Mapping[str, Any], functions: Sequence[dict[str, Any]],
        units: Sequence[dict[str, Any]], *,
        active_call_site_lowering: Mapping[str, Any] | None = None,
        whole_program_vm_call_abi: Mapping[str, Any] | None = None,
        ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    validated = _validate_optional_call_abi_inputs(
        document, active_call_site_lowering, whole_program_vm_call_abi)
    if validated is None:
        return _prepare_legacy_call_site_aware_units(
            document, functions, units)
    lowering, call_abi = validated
    return _prepare_call_abi_units(
        document, functions, units, lowering, call_abi)


def _instruction_is_target_core(item: dict[str, Any],
                                function_ids: Mapping[str, int],
                                unit_ids: Mapping[str, int]) -> bool:
    if isinstance(item.get("_target_elided"), Mapping):
        return True
    op = item.get("op")
    args = item.get("arguments")
    destination = item.get("destination")
    if not isinstance(args, list):
        return False
    if op in ("constant", "vm-copy"):
        return destination is not None and len(args) == 1
    if op == "load-name":
        return destination is not None and len(args) == 1 and isinstance(args[0], str)
    if op == "store-name":
        return destination is None and len(args) == 2 and isinstance(args[0], str)
    if op == "vm-binary-i32":
        return (destination is not None and len(args) == 3 and
                args[0] in _TARGET_BINARY_IDS)
    if op == "vm-call":
        return (destination is not None and len(args) >= 1 and
                args[0] in function_ids)
    if op == "python-call":
        plan = item.get("_target_call_abi")
        if (isinstance(plan, Mapping) and
                plan.get("binding_mode") in _FINITE_DISPATCH_MODES):
            candidates = plan.get("candidates")
            return (destination is not None and len(args) >= 1 and
                    isinstance(candidates, list) and bool(candidates) and
                    all(isinstance(row, Mapping) and
                        row.get("target") in function_ids and
                        isinstance(row.get("call_argument_operands"), list)
                        for row in candidates))
        if (isinstance(plan, Mapping) and plan.get("binding_mode") ==
                "generated-dataclass-init"):
            target = plan.get("target")
            return (destination is not None and len(args) >= 1 and
                    (target is None or target in function_ids))
        return (destination is not None and len(args) >= 1 and
                item.get("_target_direct_function") in function_ids)
    if op == "execute-expression-cfg":
        return (destination is not None and len(args) == 1 and
                args[0] in unit_ids)
    return False


def _terminator_is_target_core(item: dict[str, Any]) -> bool:
    op = item.get("op")
    args = item.get("arguments")
    targets = item.get("targets")
    if not isinstance(args, list) or not isinstance(targets, list):
        return False
    if op == "jump":
        return not args and len(targets) == 1
    if op == "branch-truth":
        return len(args) == 1 and len(targets) == 2
    if op in ("return", "return-expression"):
        return len(args) <= 1 and not targets
    # Only the explicit test primitive maps to core.  Active Python uses
    # suspend-yield/suspend-yield-from and therefore receives adapter IDs.
    if op in ("yield", "yield-value", "vm-yield-next"):
        return len(args) <= 1 and len(targets) == 1
    return False


class _CompactPool:
    def __init__(self) -> None:
        self.values: list[object] = []
        self.encoded: list[bytes] = []
        self.by_encoded: dict[bytes, int] = {}

    def add(self, value: object) -> int:
        encoded = _target_constant_bytes(value)
        found = self.by_encoded.get(encoded)
        if found is not None:
            return found
        index = len(self.values)
        if index >= 0x8000:
            raise WholeProgramVMError("PZWV210", "compact constant pool exceeds 32768")
        self.values.append(copy.deepcopy(value))
        self.encoded.append(encoded)
        self.by_encoded[encoded] = index
        return index


def _unit_local_map(unit: dict[str, Any]) -> tuple[dict[str, int], list[str]]:
    names: list[str] = []
    seen: set[str] = set()

    def visit(value: object) -> None:
        if isinstance(value, str) and value.startswith("%") and value not in seen:
            seen.add(value)
            names.append(value)
        elif isinstance(value, (list, tuple)):
            for child in value:
                visit(child)
        elif isinstance(value, dict):
            for child in value.values():
                visit(child)

    for block in unit["blocks"]:
        for item in block["instructions"]:
            destination = item.get("destination")
            if isinstance(destination, str):
                visit(destination)
            visit(item.get("arguments", []))
        visit(block["terminator"].get("arguments", []))
    if len(names) >= 0x8000:
        raise WholeProgramVMError("PZWV211", f"too many locals in {unit['name']}")
    return {name: index for index, name in enumerate(names)}, names


def _compact_operand(value: object, locals_by_name: Mapping[str, int],
                     pool: _CompactPool, *, literal: bool = False) -> bytes:
    if not literal and isinstance(value, str) and value.startswith("%"):
        try:
            return _uvar(locals_by_name[value] << 1)
        except KeyError as exc:
            raise WholeProgramVMError("PZWV212", f"unknown compact local {value}") from exc
    return _uvar((pool.add(value) << 1) | 1)


def _compact_call_operands(arguments: list[Any], plan: Mapping[str, Any] | None,
                           locals_by_name: Mapping[str, int],
                           pool: _CompactPool) -> bytes:
    literal_indexes = set(plan.get("literal_argument_indexes", ())
                          if isinstance(plan, Mapping) else ())
    return b"".join(_compact_operand(value, locals_by_name, pool,
                                    literal=index in literal_indexes)
                    for index, value in enumerate(arguments))


def _collect_adapter_table(units: Sequence[dict[str, Any]],
                           function_ids: Mapping[str, int],
                           unit_ids: Mapping[str, int]) -> tuple[
                               tuple[dict[str, Any], ...], dict[bytes, int]]:
    by_key: dict[bytes, dict[str, Any]] = {}
    for unit in units:
        for block in unit["blocks"]:
            for item in block["instructions"]:
                plan = item.get("_target_call_abi")
                if (isinstance(plan, Mapping) and
                        plan.get("binding_mode") == "constructor"):
                    descriptor = _constructor_allocation_adapter_descriptor()
                    by_key[_canonical(descriptor)] = descriptor
                if (isinstance(plan, Mapping) and plan.get("binding_mode") ==
                        "generated-dataclass-init"):
                    schema = _require_dict(
                        plan.get("generated_dataclass_init"),
                        "generated dataclass init schema")
                    descriptor = _generated_dataclass_init_adapter_descriptor(
                        schema)
                    by_key[_canonical(descriptor)] = descriptor
                if (isinstance(plan, Mapping) and
                        plan.get("binding_mode") in _FINITE_DISPATCH_MODES):
                    descriptor = _finite_dispatch_guard_adapter_descriptor(
                        plan)
                    by_key[_canonical(descriptor)] = descriptor
                    if plan.get("binding_mode") == "finite-bound-dispatch":
                        receiver = _finite_dispatch_receiver_adapter_descriptor(
                            plan)
                        by_key[_canonical(receiver)] = receiver
                if (not _instruction_is_target_core(item, function_ids, unit_ids) or
                        (item.get("op") == "load-name" and
                         not isinstance(item.get("_target_elided"), Mapping))):
                    descriptor = _adapter_descriptor("instruction", item)
                    by_key[_canonical(descriptor)] = descriptor
            term = block["terminator"]
            if not _terminator_is_target_core(term):
                descriptor = _adapter_descriptor("terminator", term)
                by_key[_canonical(descriptor)] = descriptor
    ordered_keys = sorted(by_key)
    table = tuple(
        {"adapter_id": index, **by_key[key]}
        for index, key in enumerate(ordered_keys))
    if len(table) >= 0xFFFF - _TARGET_ADAPTER_BASE:
        raise WholeProgramVMError("PZWV213", "too many compact adapter IDs")
    return table, {key: index for index, key in enumerate(ordered_keys)}


def _encode_compact_instruction(
        item: dict[str, Any], locals_by_name: Mapping[str, int],
        pool: _CompactPool, function_ids: Mapping[str, int],
        unit_ids: Mapping[str, int], adapter_ids: Mapping[bytes, int]) -> bytes:
    op = item["op"]
    args = item["arguments"]
    destination = item.get("destination")
    layout = item.get("attributes", {}).get("argument_layout")
    if (op == "python-call" and not _instruction_is_target_core(item, function_ids, unit_ids)
            and isinstance(layout, (list, tuple)) and len(layout) == len(args) - 1
            and all(isinstance(pair, (list, tuple)) and len(pair) == 2 and
                    (tuple(pair) == ("positional", None) or
                     (pair[0] == "keyword" and isinstance(pair[1], str) and pair[1])) for pair in layout)):
        descriptor = _adapter_descriptor("instruction", item)
        for kind, name in layout:
            if kind == "keyword": pool.add(name)
        opcode = _TARGET_CORE_KEYWORD_CLOSURE_CALL if any(pair[0] == "keyword" for pair in layout) else _TARGET_CORE_POSITIONAL_CLOSURE_CALL
        return b"".join((_uvar(opcode),
            _uvar(adapter_ids[_canonical(descriptor)]),
            _uvar(0 if destination is None else locals_by_name[destination] + 1),
            _uvar(len(args)), *(_compact_operand(arg, locals_by_name, pool) for arg in args)))
    if _instruction_is_target_core(item, function_ids, unit_ids):
        if isinstance(item.get("_target_elided"), Mapping):
            return _uvar(_TARGET_CORE_NOP)
        if op in ("constant", "vm-copy"):
            return (_uvar(_TARGET_CORE_CONSTANT) + _uvar(locals_by_name[destination]) +
                    _compact_operand(args[0], locals_by_name, pool,
                                     literal=op == "constant"))
        if op == "load-name":
            if item.get("attributes", {}).get("local_only") is True:
                owner = item["attributes"]["owner_callable_id"]
                return (_uvar(_TARGET_CORE_LOAD_LOCAL_NAME) + _uvar(locals_by_name[destination]) +
                        _uvar(pool.add(args[0])) + _uvar(function_ids[owner]))
            descriptor = _adapter_descriptor("instruction", item)
            adapter = adapter_ids[_canonical(descriptor)]
            return (_uvar(_TARGET_CORE_LOAD_NAME) + _uvar(locals_by_name[destination]) +
                    _uvar(pool.add(args[0])) + _uvar(adapter))
        if op == "store-name":
            return (_uvar(_TARGET_CORE_STORE_NAME) + _uvar(pool.add(args[0])) +
                    _compact_operand(args[1], locals_by_name, pool))
        if op == "vm-binary-i32":
            return (b"".join((
                _uvar(_TARGET_CORE_BINARY_I32), _uvar(locals_by_name[destination]),
                _uvar(_TARGET_BINARY_IDS[args[0]]),
                _compact_operand(args[1], locals_by_name, pool),
                _compact_operand(args[2], locals_by_name, pool))))
        if op in ("vm-call", "python-call"):
            call_arguments = (args[1:] if op == "vm-call" else
                              item.get("_target_call_arguments", args[1:]))
            if not isinstance(call_arguments, list):
                raise WholeProgramVMError(
                    "PZWV265", "direct call argument operands are not a list")
            plan = item.get("_target_call_abi")
            target = (args[0] if op == "vm-call" else
                      item.get("_target_direct_function"))
            if (op == "python-call" and isinstance(plan, Mapping) and
                    plan.get("binding_mode") == "constructor"):
                allocation = _constructor_allocation_adapter_descriptor()
                return b"".join((
                    _uvar(_TARGET_CORE_CONSTRUCT),
                    _uvar(locals_by_name[destination] + 1),
                    _uvar(adapter_ids[_canonical(allocation)]),
                    _compact_operand(
                        plan["constructed_class"], locals_by_name, pool),
                    _uvar(function_ids[target]), _uvar(len(call_arguments)),
                    _compact_call_operands(
                        call_arguments, plan, locals_by_name, pool)))
            if (op == "python-call" and isinstance(plan, Mapping) and
                    plan.get("binding_mode") == "generated-dataclass-init"):
                schema = _require_dict(
                    plan.get("generated_dataclass_init"),
                    "generated dataclass init schema")
                field_store = _generated_dataclass_init_adapter_descriptor(
                    schema)
                # Keep source field identities in the compact pool so the target
                # initializer table can use exactly the same numeric keys as
                # ordinary load/store-attribute instructions.
                for field_name in field_store["field_names"]:
                    pool.add(field_name)
                post_init = plan.get("target")
                return b"".join((
                    _uvar(_TARGET_CORE_DATACLASS_INIT),
                    _uvar(locals_by_name[destination] + 1),
                    _uvar(adapter_ids[_canonical(field_store)]),
                    _uvar(0 if post_init is None else
                          function_ids[str(post_init)] + 1),
                    _uvar(len(call_arguments)),
                    _compact_call_operands(
                        call_arguments, plan, locals_by_name, pool)))
            if (op == "python-call" and isinstance(plan, Mapping) and
                    plan.get("binding_mode") in _FINITE_DISPATCH_MODES):
                bound_dispatch = (plan.get("binding_mode") ==
                                  "finite-bound-dispatch")
                lexical_dispatch = (plan.get("binding_mode") ==
                                     "finite-lexical-dispatch")
                guard = _finite_dispatch_guard_adapter_descriptor(plan)
                receiver = (_finite_dispatch_receiver_adapter_descriptor(plan)
                            if bound_dispatch else None)
                receiver_bytes = (() if receiver is None else
                                  (_uvar(adapter_ids[_canonical(receiver)]),))
                candidates = _require_list(
                    plan.get("candidates"), "finite dispatch candidates")
                candidate_bytes: list[bytes] = []
                for raw_candidate in candidates:
                    candidate = _require_dict(
                        raw_candidate, "finite dispatch candidate")
                    candidate_target = _require_string(
                        candidate.get("target"), "finite dispatch target")
                    candidate_arguments = _require_list(
                        candidate.get("call_argument_operands"),
                        "finite dispatch argument operands")
                    if bool(candidate.get(
                            "runtime_bound_receiver_required")) != bound_dispatch:
                        raise WholeProgramVMError(
                            "PZWV268", "finite bound receiver plan mismatch")
                    lexical_owner = candidate.get(
                        "lexical_owner_callable_id")
                    if (lexical_dispatch != (lexical_owner is not None) or
                            (lexical_owner is not None and
                             lexical_owner not in function_ids)):
                        raise WholeProgramVMError(
                            "PZWV272", "finite lexical owner plan mismatch")
                    candidate_bytes.append(
                        _uvar(function_ids[candidate_target]))
                    if lexical_dispatch:
                        candidate_bytes.append(
                            _uvar(function_ids[str(lexical_owner)]))
                    candidate_bytes.extend((
                        _uvar(len(candidate_arguments)),
                        _compact_call_operands(
                            candidate_arguments, candidate, locals_by_name, pool)))
                return b"".join((
                    _uvar(
                        _TARGET_CORE_GUARDED_BOUND_DISPATCH if bound_dispatch
                        else _TARGET_CORE_GUARDED_LEXICAL_DISPATCH
                        if lexical_dispatch else
                        _TARGET_CORE_GUARDED_DISPATCH),
                    _uvar(locals_by_name[destination] + 1),
                    _uvar(adapter_ids[_canonical(guard)]),
                    *receiver_bytes,
                    _compact_operand(
                        plan["callable_operand"], locals_by_name, pool),
                    _uvar(len(candidates)), *candidate_bytes))
            if target not in function_ids:
                raise WholeProgramVMError(
                    "PZWV265", "direct call target is absent")
            return (b"".join((
                _uvar(_TARGET_CORE_CALL), _uvar(locals_by_name[destination] + 1),
                _uvar(function_ids[target]), _uvar(len(call_arguments)),
                _compact_call_operands(
                    call_arguments, plan, locals_by_name, pool))))
        if op == "execute-expression-cfg":
            return (b"".join((
                _uvar(_TARGET_CORE_EXPRESSION),
                _uvar(locals_by_name[destination] + 1),
                _uvar(unit_ids[args[0]]))))
    descriptor = _adapter_descriptor("instruction", item)
    adapter = adapter_ids[_canonical(descriptor)]
    return b"".join((
        _uvar(_TARGET_ADAPTER_BASE + adapter),
        _uvar(0 if destination is None else locals_by_name[destination] + 1),
        _uvar(len(args)),
        *(_compact_operand(value, locals_by_name, pool) for value in args)))


def _encode_compact_terminator(
        item: dict[str, Any], locals_by_name: Mapping[str, int],
        block_ids: Mapping[str, int], pool: _CompactPool,
        adapter_ids: Mapping[bytes, int]) -> bytes:
    op = item["op"]
    args = item["arguments"]
    targets = item["targets"]
    if _terminator_is_target_core(item):
        if op == "jump":
            return _uvar(_TARGET_TERM_JUMP) + _uvar(block_ids[targets[0]])
        if op == "branch-truth":
            return (b"".join((
                _uvar(_TARGET_TERM_BRANCH),
                _compact_operand(args[0], locals_by_name, pool),
                _uvar(block_ids[targets[0]]), _uvar(block_ids[targets[1]]))))
        if op in ("return", "return-expression"):
            return (_uvar(_TARGET_TERM_RETURN) + _uvar(len(args)) +
                    (b"" if not args else
                     _compact_operand(args[0], locals_by_name, pool)))
        return (_uvar(_TARGET_TERM_YIELD_NEXT if op == "vm-yield-next" else _TARGET_TERM_YIELD) + _uvar(len(args)) +
                (b"" if not args else _compact_operand(args[0], locals_by_name, pool)) +
                _uvar(block_ids[targets[0]]))
    descriptor = _adapter_descriptor("terminator", item)
    adapter = adapter_ids[_canonical(descriptor)]
    return b"".join((
        _uvar(_TARGET_ADAPTER_BASE + adapter), _uvar(len(args)),
        *(_compact_operand(value, locals_by_name, pool) for value in args),
        _uvar(len(targets)),
        *(_uvar(block_ids[target]) for target in targets)))


def _encode_compact_unit(
        unit: dict[str, Any], pool: _CompactPool,
        function_ids: Mapping[str, int], unit_ids: Mapping[str, int],
        adapter_ids: Mapping[bytes, int]) -> tuple[bytes, dict[str, Any]]:
    locals_by_name, local_names = _unit_local_map(unit)
    blocks = unit["blocks"]
    block_ids = {block["name"]: index for index, block in enumerate(blocks)}
    if len(block_ids) != len(blocks) or unit["entry"] not in block_ids:
        raise WholeProgramVMError("PZWV214", f"invalid compact blocks in {unit['name']}")
    encoded_blocks: list[bytes] = []
    execution_rows = []
    for block in blocks:
        exception = block.get("exception_target")
        if exception is not None and exception not in block_ids:
            raise WholeProgramVMError("PZWV215", f"unknown exception block {exception}")
        body = bytearray(_uvar(0 if exception is None else block_ids[exception] + 1))
        body.extend(_uvar(len(block["instructions"])))
        for item in block["instructions"]:
            body.extend(_encode_compact_instruction(
                item, locals_by_name, pool, function_ids, unit_ids, adapter_ids))
        body.extend(_encode_compact_terminator(
            block["terminator"], locals_by_name, block_ids, pool, adapter_ids))
        encoded_blocks.append(bytes(body))
        execution_rows.append({
            "block": block["name"],
            "instruction_semantics": [
                _sha256_json({key: value for key, value in item.items()
                              if key != "span"})
                for item in block["instructions"]],
            "terminator_semantic_sha256": _sha256_json({
                key: value for key, value in block["terminator"].items()
                if key != "span"}),
        })
    parameters = []
    if unit["kind"] == _UNIT_FUNCTION:
        signature = unit["meta"].get("signature", {})
        raw_parameters = signature.get("parameters", []) if isinstance(signature, dict) else []
        parameters = [item["name"] for item in raw_parameters
                      if isinstance(item, dict) and isinstance(item.get("name"), str)]
    bound_names = list(dict.fromkeys([
        *parameters,
        *(item["arguments"][0]
          for block in blocks for item in block["instructions"]
          if item.get("op") == "store-name" and
          isinstance(item.get("arguments"), list) and item["arguments"] and
          isinstance(item["arguments"][0], str)),
    ]))
    frame_slot_count = len(local_names) + len(bound_names)
    # Header order is local SSA slots, exact frame slot bound, blocks, entry,
    # lexical-parent mode, then parameter name constants.
    prefix = bytearray()
    prefix.extend(_uvar(len(local_names)))
    prefix.extend(_uvar(frame_slot_count))
    prefix.extend(_uvar(len(blocks)))
    prefix.extend(_uvar(block_ids[unit["entry"]]))
    lexical_parent_required = (
        unit["kind"] == _UNIT_EXPRESSION or
        unit.get("lexical_parent_callable_id") is not None)
    prefix.extend(_uvar(1 if lexical_parent_required else 0))
    prefix.extend(_uvar(len(parameters)))
    for name in parameters:
        prefix.extend(_uvar(pool.add(name)))
    directory_start = len(prefix)
    prefix.extend(b"\0" * (3 * len(blocks)))
    cursor = len(prefix)
    for index, body in enumerate(encoded_blocks):
        prefix[directory_start + index * 3:directory_start + index * 3 + 3] = _u24(cursor)
        prefix.extend(body)
        cursor += len(body)
    manifest = {
        "unit": unit["name"], "kind": unit["kind"], "owner": unit["owner"],
        "local_id_to_proof_name": local_names,
        "parameter_name_constant_ids": [pool.add(name) for name in parameters],
        "bound_name_count": len(bound_names),
        "frame_slot_count": frame_slot_count,
        "lexical_parent_mode": (
            "immediate-owner-frame" if unit["kind"] == _UNIT_EXPRESSION else
            "runtime-guarded-owner-or-retained-closure"
            if unit.get("lexical_parent_callable_id") is not None else
            "none-function-is-not-dynamically-scoped"),
        "lexical_parent_callable_id": unit.get(
            "lexical_parent_callable_id"),
        "block_id_to_proof_name": [block["name"] for block in blocks],
        "execution_order_semantic_sha256": _sha256_json(execution_rows),
    }
    return bytes(prefix), manifest


def build_compact_target_vm(
        document: Mapping[str, Any], *,
        active_call_site_lowering: Mapping[str, Any] | None = None,
        whole_program_vm_call_abi: Mapping[str, Any] | None = None,
        object_store_ir: Mapping[str, Any] | None = None,
        ) -> tuple[
        bytes, dict[str, Any], tuple[dict[str, Any], ...], dict[str, Any]]:
    """Build the stripped executable PZVT image and its host proof manifest."""
    document = copy.deepcopy(_require_dict(dict(document), "proof document"))
    validated_call_abi = _validate_optional_call_abi_inputs(
        document, active_call_site_lowering, whole_program_vm_call_abi)
    if validated_call_abi is not None:
        active_call_site_lowering, whole_program_vm_call_abi = (
            validated_call_abi)
        document["active_call_site_lowering_semantic_sha256"] = (
            active_call_site_lowering["semantic_sha256"])
        document["whole_program_vm_call_abi_semantic_sha256"] = (
            whole_program_vm_call_abi["semantic_sha256"])
    functions, units = _unit_specs(document)
    function_ids = {item["callable_id"]: index
                    for index, item in enumerate(functions)}
    unit_ids = {item["name"]: index for index, item in enumerate(units)}
    if len(function_ids) != len(functions) or len(unit_ids) != len(units):
        raise WholeProgramVMError("PZWV216", "duplicate compact function/unit ID")
    if len(functions) >= 0xFFFF or len(units) >= 0xFFFF:
        raise WholeProgramVMError("PZWV217", "compact function/unit table overflow")
    units, call_lowering = _prepare_call_site_aware_units(
        document, functions, units,
        active_call_site_lowering=active_call_site_lowering,
        whole_program_vm_call_abi=whole_program_vm_call_abi)
    from .closure_lowering import lower_closure_definitions
    from .lambda_lowering import materialize_lambda_definitions
    lambda_lowering = materialize_lambda_definitions(functions, units)
    from .comprehension_lowering import materialize_list_comprehensions
    comprehension_lowering = materialize_list_comprehensions(functions, units)
    from .generator_lowering import lower_generator_next_bodies
    generator_lowering = lower_generator_next_bodies(functions, units)
    function_ids = {item["callable_id"]: index for index, item in enumerate(functions)}
    if len(function_ids) != len(functions) or len(functions) >= 0xFFFF:
        raise WholeProgramVMError("PZWV217", "lambda function table overflow/duplicate")
    closure_lowering = lower_closure_definitions(functions, units)
    units, object_store_lowering = _expand_object_store_units(
        units, object_store_ir)
    try:
        units, phi_lowering = lower_phi_units(units)
    except (PhiLoweringError, CFGSSAError) as exc:
        raise WholeProgramVMError("PZWV280", f"invalid phi edge lowering: {exc}") from exc
    unit_ids = {item["name"]: index for index, item in enumerate(units)}
    if len(unit_ids) != len(units) or len(units) >= 0xFFFF:
        raise WholeProgramVMError(
            "PZWV279", "object-store expansion duplicated/overflowed units")
    adapter_table, adapter_ids = _collect_adapter_table(
        units, function_ids, unit_ids)
    pool = _CompactPool()
    for function in functions:
        for constant in function["meta"].get("module_bootstrap_constants", ()):
            if not isinstance(constant, str):
                raise WholeProgramVMError("PZWV210", "module metadata constant must be a string")
            pool.add(constant)
    unit_blobs: list[bytes] = []
    unit_manifest: list[dict[str, Any]] = []
    for unit in units:
        blob, manifest = _encode_compact_unit(
            unit, pool, function_ids, unit_ids, adapter_ids)
        unit_blobs.append(blob)
        unit_manifest.append(manifest)

    function_table = b"".join(struct.pack("<H", item["unit"])
                              for item in functions)
    unit_directory = bytearray()
    unit_data = bytearray()
    for blob in unit_blobs:
        unit_directory.extend(_u24(len(unit_data)))
        unit_data.extend(blob)
    constant_directory = bytearray()
    constant_data = bytearray()
    for encoded in pool.encoded:
        constant_directory.extend(_u24(len(constant_data)))
        constant_data.extend(encoded)

    function_offset = _TARGET_HEADER.size
    unit_directory_offset = function_offset + len(function_table)
    constant_directory_offset = unit_directory_offset + len(unit_directory)
    constant_data_offset = constant_directory_offset + len(constant_directory)
    unit_data_offset = constant_data_offset + len(constant_data)
    proof_semantic = _sha256_json(document)
    payload = (function_table + bytes(unit_directory) +
               bytes(constant_directory) + bytes(constant_data) + bytes(unit_data))
    header = _TARGET_HEADER.pack(
        TARGET_BYTECODE_MAGIC, TARGET_BYTECODE_VERSION, 0, _TARGET_HEADER.size,
        _TARGET_HEADER.size + len(payload), zlib.crc32(payload) & 0xFFFFFFFF,
        bytes.fromhex(proof_semantic), len(functions), len(units),
        len(adapter_table), len(pool.values), function_offset,
        unit_directory_offset, constant_directory_offset,
        constant_data_offset, unit_data_offset, len(unit_data))
    bytecode = header + payload
    manifest = {
        "format": "pyz80.compact-target-vm-proof-manifest.v1",
        "proof_document_semantic_sha256": proof_semantic,
        "function_id_table": [item["callable_id"] for item in functions],
        "unit_table": unit_manifest,
        "adapter_table": list(adapter_table),
        "call_site_lowering": call_lowering["call_site_lowering"],
        "call_abi_binding": {
            "enabled": call_lowering["call_abi_input_enabled"],
            "active_call_site_lowering_semantic_sha256": call_lowering[
                "active_call_site_lowering_semantic_sha256"],
            "whole_program_vm_call_abi_semantic_sha256": call_lowering[
                "whole_program_vm_call_abi_semantic_sha256"],
            "occurrence_bindings_semantic_sha256": _sha256_json(
                call_lowering["call_site_lowering"]),
            "occurrences_bound_by_exact_cfg_path": call_lowering[
                "call_abi_input_enabled"],
        },
        "object_store_lowering": object_store_lowering,
        "phi_lowering": phi_lowering,
        "closure_lowering": closure_lowering,
        "lambda_lowering": lambda_lowering,
        "comprehension_lowering": comprehension_lowering,
        "generator_lowering": generator_lowering,
        "constant_pool_count": len(pool.values),
        "constant_pool_semantic_sha256": _sha256_json(pool.values),
        "target_omits": [
            "source-spans", "source-text", "JSON-attributes", "proof-names",
            "per-function-and-per-program-SHA256"],
    }
    compact = decode_compact_target_vm(
        bytecode, expected_proof_semantic_sha256=proof_semantic)
    coverage = {
        "function_id_table": [item["callable_id"] for item in functions],
        "function_call_signatures": [
            [{"name": p["name"], "kind": p.get("kind"), "has_default": p.get("default") is not None}
             for p in units[function["unit"]]["meta"]["signature"]["parameters"]]
            for function in functions],
        "positional_call_arities": [
            len(parameters) if all(p.get("kind") in ("positional-only", "positional-or-keyword")
                                  and p.get("default") is None for p in parameters) else 65535
            for function in functions
            for parameters in [units[function["unit"]]["meta"]["signature"]["parameters"]]],
        "definition_only_function_count": len(document.get("definition_callable_ids", ())) + len(lambda_lowering["definition_only_callable_ids"]) + len(comprehension_lowering["definition_only_callable_ids"]),
        "function_modules": [function["meta"].get("module") for function in functions],
        "lambda_lowering": lambda_lowering,
        "comprehension_lowering": comprehension_lowering,
        "generator_lowering": generator_lowering,
        "function_count": len(functions), "unit_count": len(units),
        "proven_reachable_function_count": len(
            document.get("proven_reachable_callable_ids", ())),
        "guarded_callable_function_count": len(
            document.get("guarded_callable_ids", ())),
        "block_count": sum(len(unit["blocks"]) for unit in units),
        "instruction_count": sum(len(block["instructions"])
                                 for unit in units for block in unit["blocks"]),
        "adapter_id_count": len(adapter_table),
        "constant_count": len(pool.values),
        "target_bytecode_bytes": len(bytecode),
        "proof_manifest_semantic_sha256": _sha256_json(manifest),
        "object_store_lowering_enabled": object_store_lowering["enabled"],
        "object_store_fragment_instruction_count": object_store_lowering[
            "expanded_fragment_count"],
        "object_store_expression_unit_count": object_store_lowering[
            "added_expression_unit_count"],
        "phi_instruction_count": phi_lowering["phi_instruction_count"],
        "phi_edge_copy_instruction_count": phi_lowering["edge_copy_instruction_count"],
        "phi_split_edge_count": phi_lowering["split_edge_count"],
        "phi_scratch_local_count": phi_lowering["scratch_local_count"],
        "compact_unit_labels": [{
            "kind": ("function" if unit["kind"] == _UNIT_FUNCTION
                     else "expression"),
            "owner": functions[unit["owner"]]["callable_id"],
            "name": unit["name"],
            "function_index": unit["owner"],
        } for unit in units],
        **{key: value for key, value in call_lowering.items()
           if key != "call_site_lowering" and not key.endswith("_ids")},
    }
    return bytecode, compact, adapter_table, {"manifest": manifest,
                                                "coverage": coverage}


def _decode_compact_operand(data: bytes, offset: int, end: int,
                            local_count: int, constant_count: int
                            ) -> tuple[dict[str, int], int]:
    encoded, offset = _read_uvar(data, offset, end)
    if encoded & 1:
        index = encoded >> 1
        if index >= constant_count:
            raise WholeProgramVMError("PZWV218", "compact constant operand overflow")
        return {"kind": "constant", "id": index}, offset
    index = encoded >> 1
    if index >= local_count:
        raise WholeProgramVMError("PZWV219", "compact local operand overflow")
    return {"kind": "local", "id": index}, offset


def decode_compact_target_vm(
        data: bytes, *, expected_proof_semantic_sha256: str | None = None
        ) -> dict[str, Any]:
    """Validate and decode the numeric executable PZVT image."""
    data = bytes(data)
    if len(data) < _TARGET_HEADER.size:
        raise WholeProgramVMError("PZWV220", "truncated compact target header")
    try:
        values = _TARGET_HEADER.unpack_from(data)
    except struct.error as exc:
        raise WholeProgramVMError("PZWV220", "truncated compact target header") from exc
    (magic, version, flags, header_size, total, crc, proof_digest,
     function_count, unit_count, adapter_count, constant_count,
     function_offset, unit_directory_offset, constant_directory_offset,
     constant_data_offset, unit_data_offset, unit_data_size) = values
    if (magic != TARGET_BYTECODE_MAGIC or version != TARGET_BYTECODE_VERSION or
            flags != 0 or header_size != _TARGET_HEADER.size or total != len(data)):
        raise WholeProgramVMError("PZWV221", "invalid compact target header")
    if (expected_proof_semantic_sha256 is not None and
            proof_digest.hex() != expected_proof_semantic_sha256):
        raise WholeProgramVMError(
            "PZWV246", "compact target proof-document hash binding mismatch")
    payload = data[header_size:]
    if zlib.crc32(payload) & 0xFFFFFFFF != crc:
        raise WholeProgramVMError("PZWV222", "compact target CRC mismatch")
    if not (function_offset == header_size and
            unit_directory_offset == function_offset + function_count * 2 and
            constant_directory_offset == unit_directory_offset + unit_count * 3 and
            constant_data_offset == constant_directory_offset + constant_count * 3 and
            constant_data_offset <= unit_data_offset and
            unit_data_offset + unit_data_size == len(data)):
        raise WholeProgramVMError("PZWV223", "invalid compact target sections")
    functions = [struct.unpack_from("<H", data, function_offset + index * 2)[0]
                 for index in range(function_count)]
    if any(unit >= unit_count for unit in functions):
        raise WholeProgramVMError("PZWV224", "compact function unit overflow")

    constants: list[object] = []
    for index in range(constant_count):
        relative = _read_u24(data, constant_directory_offset + index * 3)
        next_relative = (_read_u24(data, constant_directory_offset + (index + 1) * 3)
                         if index + 1 < constant_count else
                         unit_data_offset - constant_data_offset)
        start, end = constant_data_offset + relative, constant_data_offset + next_relative
        if not constant_data_offset <= start < end <= unit_data_offset:
            raise WholeProgramVMError("PZWV225", "invalid compact constant directory")
        value, consumed = _decode_target_constant(data, start, end)
        if consumed != end:
            raise WholeProgramVMError("PZWV226", "compact constant trailing bytes")
        constants.append(value)

    units = []
    for unit_index in range(unit_count):
        relative = _read_u24(data, unit_directory_offset + unit_index * 3)
        next_relative = (_read_u24(data, unit_directory_offset + (unit_index + 1) * 3)
                         if unit_index + 1 < unit_count else unit_data_size)
        start, end = unit_data_offset + relative, unit_data_offset + next_relative
        if not unit_data_offset <= start < end <= len(data):
            raise WholeProgramVMError("PZWV227", "invalid compact unit directory")
        local_count, cursor = _read_uvar(data, start, end)
        frame_slot_count, cursor = _read_uvar(data, cursor, end)
        block_count, cursor = _read_uvar(data, cursor, end)
        entry, cursor = _read_uvar(data, cursor, end)
        lexical_parent_mode, cursor = _read_uvar(data, cursor, end)
        if frame_slot_count < local_count or lexical_parent_mode not in (0, 1):
            raise WholeProgramVMError("PZWV228", "invalid compact frame slot contract")
        parameter_count, cursor = _read_uvar(data, cursor, end)
        parameters = []
        for _ in range(parameter_count):
            parameter, cursor = _read_uvar(data, cursor, end)
            if parameter >= constant_count:
                raise WholeProgramVMError("PZWV228", "compact parameter constant overflow")
            parameters.append(parameter)
        if not block_count or entry >= block_count or cursor + block_count * 3 > end:
            raise WholeProgramVMError("PZWV228", "invalid compact unit header")
        block_directory = cursor
        blocks = []
        for block_index in range(block_count):
            block_relative = _read_u24(data, block_directory + block_index * 3)
            block_end_relative = (_read_u24(
                data, block_directory + (block_index + 1) * 3)
                if block_index + 1 < block_count else end - start)
            at, block_end = start + block_relative, start + block_end_relative
            if not block_directory + block_count * 3 <= at < block_end <= end:
                raise WholeProgramVMError("PZWV229", "invalid compact block directory")
            exception_plus, at = _read_uvar(data, at, block_end)
            if exception_plus and exception_plus - 1 >= block_count:
                raise WholeProgramVMError("PZWV230", "compact exception target overflow")
            instruction_count, at = _read_uvar(data, at, block_end)
            instructions = []
            for _ in range(instruction_count):
                token, at = _read_uvar(data, at, block_end)
                item: dict[str, Any] = {"opcode": token}
                if token == _TARGET_CORE_CONSTANT:
                    item["destination"], at = _read_uvar(data, at, block_end)
                    item["arguments"] = []
                    operand, at = _decode_compact_operand(
                        data, at, block_end, local_count, constant_count)
                    item["arguments"].append(operand)
                elif token in (_TARGET_CORE_LOAD_NAME, _TARGET_CORE_LOAD_LOCAL_NAME):
                    item["destination"], at = _read_uvar(data, at, block_end)
                    name, at = _read_uvar(data, at, block_end)
                    fallback, at = _read_uvar(data, at, block_end)
                    if name >= constant_count:
                        raise WholeProgramVMError("PZWV231", "load-name constant overflow")
                    if fallback >= (function_count if token == _TARGET_CORE_LOAD_LOCAL_NAME else adapter_count):
                        raise WholeProgramVMError("PZWV231", "load-name adapter overflow")
                    item["name_constant"] = name
                    item["fallback_adapter_id"] = fallback
                    if token == _TARGET_CORE_LOAD_LOCAL_NAME:
                        item["owner_function"] = fallback
                elif token == _TARGET_CORE_STORE_NAME:
                    name, at = _read_uvar(data, at, block_end)
                    if name >= constant_count:
                        raise WholeProgramVMError("PZWV232", "store-name constant overflow")
                    item["name_constant"] = name
                    item["value"], at = _decode_compact_operand(
                        data, at, block_end, local_count, constant_count)
                elif token == _TARGET_CORE_BINARY_I32:
                    item["destination"], at = _read_uvar(data, at, block_end)
                    item["operator"], at = _read_uvar(data, at, block_end)
                    if item["operator"] not in _TARGET_BINARY_IDS.values():
                        raise WholeProgramVMError("PZWV233", "binary operator overflow")
                    item["left"], at = _decode_compact_operand(
                        data, at, block_end, local_count, constant_count)
                    item["right"], at = _decode_compact_operand(
                        data, at, block_end, local_count, constant_count)
                elif token == _TARGET_CORE_CALL:
                    item["destination_plus_one"], at = _read_uvar(data, at, block_end)
                    item["function"], at = _read_uvar(data, at, block_end)
                    count, at = _read_uvar(data, at, block_end)
                    if item["function"] >= function_count:
                        raise WholeProgramVMError("PZWV234", "call function overflow")
                    item["arguments"] = []
                    for _ in range(count):
                        operand, at = _decode_compact_operand(
                            data, at, block_end, local_count, constant_count)
                        item["arguments"].append(operand)
                elif token == _TARGET_CORE_EXPRESSION:
                    item["destination_plus_one"], at = _read_uvar(data, at, block_end)
                    item["unit"], at = _read_uvar(data, at, block_end)
                    if item["unit"] >= unit_count:
                        raise WholeProgramVMError("PZWV235", "expression unit overflow")
                elif token == _TARGET_CORE_CONSTRUCT:
                    item["destination_plus_one"], at = _read_uvar(
                        data, at, block_end)
                    item["allocation_adapter_id"], at = _read_uvar(
                        data, at, block_end)
                    if (not item["destination_plus_one"] or
                            item["allocation_adapter_id"] >= adapter_count):
                        raise WholeProgramVMError(
                            "PZWV236", "constructor destination/adapter overflow")
                    item["constructed_class"], at = _decode_compact_operand(
                        data, at, block_end, local_count, constant_count)
                    item["function"], at = _read_uvar(data, at, block_end)
                    count, at = _read_uvar(data, at, block_end)
                    if item["function"] >= function_count:
                        raise WholeProgramVMError(
                            "PZWV234", "constructor init function overflow")
                    item["arguments"] = []
                    for _ in range(count):
                        operand, at = _decode_compact_operand(
                            data, at, block_end, local_count, constant_count)
                        item["arguments"].append(operand)
                elif token == _TARGET_CORE_NOP:
                    item["arguments"] = []
                elif token == _TARGET_CORE_DATACLASS_INIT:
                    item["destination_plus_one"], at = _read_uvar(
                        data, at, block_end)
                    item["field_store_adapter_id"], at = _read_uvar(
                        data, at, block_end)
                    post_plus, at = _read_uvar(data, at, block_end)
                    item["post_init_function_plus_one"] = post_plus
                    count, at = _read_uvar(data, at, block_end)
                    if (not item["destination_plus_one"] or
                            item["field_store_adapter_id"] >= adapter_count or
                            post_plus > function_count):
                        raise WholeProgramVMError(
                            "PZWV236", "dataclass init operand overflow")
                    item["arguments"] = []
                    for _ in range(count):
                        operand, at = _decode_compact_operand(
                            data, at, block_end, local_count, constant_count)
                        item["arguments"].append(operand)
                elif token in (_TARGET_CORE_GUARDED_DISPATCH,
                                _TARGET_CORE_GUARDED_BOUND_DISPATCH,
                                _TARGET_CORE_GUARDED_LEXICAL_DISPATCH):
                    bound_dispatch = (
                        token == _TARGET_CORE_GUARDED_BOUND_DISPATCH)
                    lexical_dispatch = (
                        token == _TARGET_CORE_GUARDED_LEXICAL_DISPATCH)
                    item["destination_plus_one"], at = _read_uvar(
                        data, at, block_end)
                    item["guard_adapter_id"], at = _read_uvar(
                        data, at, block_end)
                    if (not item["destination_plus_one"] or
                            item["guard_adapter_id"] >= adapter_count):
                        raise WholeProgramVMError(
                            "PZWV269", "guarded dispatch destination/adapter overflow")
                    if bound_dispatch:
                        item["receiver_adapter_id"], at = _read_uvar(
                            data, at, block_end)
                        if item["receiver_adapter_id"] >= adapter_count:
                            raise WholeProgramVMError(
                                "PZWV269", "guarded bound receiver adapter overflow")
                    item["callable"], at = _decode_compact_operand(
                        data, at, block_end, local_count, constant_count)
                    candidate_count, at = _read_uvar(data, at, block_end)
                    if not candidate_count or candidate_count > 0xFF:
                        raise WholeProgramVMError(
                            "PZWV269", "guarded dispatch candidate count overflow")
                    item["candidates"] = []
                    for _ in range(candidate_count):
                        target, at = _read_uvar(data, at, block_end)
                        lexical_owner = None
                        if lexical_dispatch:
                            lexical_owner, at = _read_uvar(
                                data, at, block_end)
                        argument_count, at = _read_uvar(data, at, block_end)
                        if (target >= function_count or
                                (lexical_owner is not None and
                                 lexical_owner >= function_count) or
                                argument_count > 0xFF or
                                (bound_dispatch and argument_count >= 0xFF)):
                            raise WholeProgramVMError(
                                "PZWV269", "guarded dispatch candidate overflow")
                        arguments = []
                        for _ in range(argument_count):
                            operand, at = _decode_compact_operand(
                                data, at, block_end, local_count,
                                constant_count)
                            arguments.append(operand)
                        item["candidates"].append({
                            "function": target, "arguments": arguments,
                            "runtime_bound_receiver_required": bound_dispatch,
                            "lexical_owner_function": lexical_owner})
                elif token >= _TARGET_ADAPTER_BASE or token in (_TARGET_CORE_POSITIONAL_CLOSURE_CALL, _TARGET_CORE_KEYWORD_CLOSURE_CALL):
                    if token in (_TARGET_CORE_POSITIONAL_CLOSURE_CALL, _TARGET_CORE_KEYWORD_CLOSURE_CALL):
                        item["adapter_id"], at = _read_uvar(data, at, block_end)
                    else:
                        item["adapter_id"] = token - _TARGET_ADAPTER_BASE
                    if item["adapter_id"] >= adapter_count:
                        raise WholeProgramVMError("PZWV236", "instruction adapter overflow")
                    item["destination_plus_one"], at = _read_uvar(data, at, block_end)
                    count, at = _read_uvar(data, at, block_end)
                    if token in (_TARGET_CORE_POSITIONAL_CLOSURE_CALL, _TARGET_CORE_KEYWORD_CLOSURE_CALL) and not 1 <= count <= 255:
                        raise WholeProgramVMError("PZWV236", "positional closure argument overflow")
                    item["arguments"] = []
                    for _ in range(count):
                        operand, at = _decode_compact_operand(
                            data, at, block_end, local_count, constant_count)
                        item["arguments"].append(operand)
                else:
                    raise WholeProgramVMError("PZWV237", f"unknown compact opcode {token}")
                destination = item.get("destination", 0)
                if "destination" in item and destination >= local_count:
                    raise WholeProgramVMError("PZWV238", "compact destination overflow")
                destination_plus = item.get("destination_plus_one", 0)
                if destination_plus > local_count:
                    raise WholeProgramVMError("PZWV238", "compact destination overflow")
                instructions.append(item)
            token, at = _read_uvar(data, at, block_end)
            term: dict[str, Any] = {"opcode": token}
            if token == _TARGET_TERM_JUMP:
                target, at = _read_uvar(data, at, block_end)
                term["targets"] = [target]
                term["arguments"] = []
            elif token == _TARGET_TERM_BRANCH:
                operand, at = _decode_compact_operand(
                    data, at, block_end, local_count, constant_count)
                first, at = _read_uvar(data, at, block_end)
                second, at = _read_uvar(data, at, block_end)
                term["arguments"], term["targets"] = [operand], [first, second]
            elif token in (_TARGET_TERM_RETURN, _TARGET_TERM_YIELD, _TARGET_TERM_YIELD_NEXT):
                count, at = _read_uvar(data, at, block_end)
                if count > 1:
                    raise WholeProgramVMError("PZWV239", "compact return/yield arity")
                term["arguments"] = []
                if count:
                    operand, at = _decode_compact_operand(
                        data, at, block_end, local_count, constant_count)
                    term["arguments"].append(operand)
                term["targets"] = []
                if token in (_TARGET_TERM_YIELD, _TARGET_TERM_YIELD_NEXT):
                    target, at = _read_uvar(data, at, block_end)
                    term["targets"].append(target)
            elif token >= _TARGET_ADAPTER_BASE:
                term["adapter_id"] = token - _TARGET_ADAPTER_BASE
                if term["adapter_id"] >= adapter_count:
                    raise WholeProgramVMError("PZWV240", "terminator adapter overflow")
                count, at = _read_uvar(data, at, block_end)
                term["arguments"] = []
                for _ in range(count):
                    operand, at = _decode_compact_operand(
                        data, at, block_end, local_count, constant_count)
                    term["arguments"].append(operand)
                count, at = _read_uvar(data, at, block_end)
                term["targets"] = []
                for _ in range(count):
                    target, at = _read_uvar(data, at, block_end)
                    term["targets"].append(target)
            else:
                raise WholeProgramVMError("PZWV241", f"unknown compact terminator {token}")
            if any(target >= block_count for target in term["targets"]):
                raise WholeProgramVMError("PZWV242", "compact branch target overflow")
            if at != block_end:
                raise WholeProgramVMError("PZWV243", "compact block trailing bytes")
            blocks.append({
                "exception_target": None if not exception_plus else exception_plus - 1,
                "instructions": instructions, "terminator": term,
            })
        units.append({"local_count": local_count, "entry_block": entry,
                      "frame_slot_count": frame_slot_count,
                      "lexical_parent_mode": lexical_parent_mode,
                      "parameter_name_constants": parameters,
                      "blocks": blocks})
    return {
        "format": COMPACT_TARGET_VM_FORMAT,
        "proof_document_semantic_sha256": proof_digest.hex(),
        "adapter_count": adapter_count,
        "constants": constants, "functions": functions, "units": units,
    }


def build_whole_program_vm(
        active_call_graph: Mapping[str, Any], *,
        active_call_site_lowering: Mapping[str, Any] | None = None,
        whole_program_vm_call_abi: Mapping[str, Any] | None = None,
        object_store_ir: Mapping[str, Any] | None = None,
        ) -> WholeProgramVMArtifact:
    """Compile a validated active call graph into deterministic bytecode."""
    validated_object_store = _validate_object_store_report(
        active_call_graph, object_store_ir)
    document = _normalise_graph(active_call_graph)
    validated_call_abi = _validate_optional_call_abi_inputs(
        document, active_call_site_lowering, whole_program_vm_call_abi)
    if validated_call_abi is not None:
        validated_lowering, validated_abi = validated_call_abi
        guarded_rows = _guarded_candidate_rows(validated_abi)
        if guarded_rows:
            # Rebuild the proof document from the authenticated source graph;
            # guarded candidates are an explicit suffix, never additions to
            # the source-proven reachable prefix.
            document = _normalise_graph(
                active_call_graph, guarded_callable_rows=guarded_rows)
            validated_call_abi = _validate_optional_call_abi_inputs(
                document, validated_lowering, validated_abi)
            if validated_call_abi is None:  # pragma: no cover - invariant
                raise WholeProgramVMError(
                    "PZWV271", "guarded ABI validation unexpectedly vanished")
            validated_lowering, validated_abi = validated_call_abi
        # The lossless PZVM proof and compact PZVT digest both bind the exact
        # validated reports consumed for per-occurrence direct calls.
        document["active_call_site_lowering_semantic_sha256"] = (
            validated_lowering["semantic_sha256"])
        document["whole_program_vm_call_abi_semantic_sha256"] = (
            validated_abi["semantic_sha256"])
    if validated_object_store is not None:
        document["object_store_ir_semantic_sha256"] = (
            validated_object_store["semantic_sha256"])
    proof_bytecode, coverage = _encode(document)
    decoded = decode_whole_program_vm(proof_bytecode)
    if decoded != document:
        raise WholeProgramVMError("PZWV048", "encoder/decoder round-trip differs")
    semantic = _sha256_json(document)
    (target_bytecode, compact_document, adapter_table,
     compact_result) = build_compact_target_vm(
         document,
         active_call_site_lowering=(validated_call_abi[0]
                                    if validated_call_abi is not None else None),
         whole_program_vm_call_abi=(validated_call_abi[1]
                                    if validated_call_abi is not None else None),
         object_store_ir=validated_object_store)
    if compact_document["proof_document_semantic_sha256"] != semantic:
        raise WholeProgramVMError("PZWV244", "compact target proof binding mismatch")
    target_coverage = compact_result["coverage"]
    target_coverage["proof_bytecode_bytes"] = len(proof_bytecode)
    target_coverage["size_reduction_bytes"] = (
        len(proof_bytecode) - len(target_bytecode))
    target_coverage["size_reduction_ratio"] = (
        len(proof_bytecode) / len(target_bytecode))
    target_coverage["target_under_256_kib"] = len(target_bytecode) < 256 * 1024
    target_coverage["max_frame_slot_count"] = max(
        (unit["frame_slot_count"] for unit in compact_document["units"]),
        default=0)
    raw_call_graph = _require_dict(
        dict(active_call_graph).get("call_graph"), "call_graph")
    reachable_ids = set(document["proven_reachable_callable_ids"])
    serialized_function_ids = {
        str(row["callable_id"]) for row in document["functions"]}
    reachable_graph_sites = [
        row for row in raw_call_graph.get("call_sites", [])
        if isinstance(row, dict) and row.get("caller") in reachable_ids]
    expected_internal_site_ids = {
        str(row["call_site_id"])
        for row in reachable_graph_sites
        if isinstance(row.get("resolution"), dict) and
        row["resolution"].get("proven") is True and
        any(target in reachable_ids
            for target in row["resolution"].get("targets", []))}
    reachable_finite_site_ids = {
        str(row["call_site_id"])
        for row in reachable_graph_sites
        if isinstance(row.get("resolution"), dict) and
        row["resolution"].get("kind") == "finite-dynamic-dispatch" and
        any(target in serialized_function_ids
            for target in row["resolution"].get("targets", []))}

    all_cfg_instructions = []
    for function in document["functions"]:
        cfg = function["row"]["cfg"]
        for owner in [cfg, *cfg["expression_programs"]]:
            for block in owner["blocks"]:
                all_cfg_instructions.extend(block["instructions"])
    explicit_vm_calls = sum(
        item.get("op") == "vm-call" for item in all_cfg_instructions)
    python_call_instructions = sum(
        item.get("op") == "python-call" for item in all_cfg_instructions)
    lowered_internal = int(target_coverage["direct_call_site_count"])
    expected_internal = len(expected_internal_site_ids)
    target_coverage.update({
        "active_exact_internal_call_site_count": expected_internal,
        "active_internal_call_sites_lowered": lowered_internal,
        "active_internal_call_sites_unlowered": max(
            0, expected_internal - lowered_internal),
        "active_explicit_vm_call_instruction_count": explicit_vm_calls,
        "active_python_call_instruction_count": python_call_instructions,
        "active_python_call_instructions_lowered": target_coverage[
            "direct_call_instruction_count"],
        "active_finite_dispatch_site_count": len(reachable_finite_site_ids),
        "active_finite_dispatch_sites_lowered": target_coverage.get(
            "abi_finite_dispatch_site_count", 0),
        "active_interprocedural_execution_closed": (
            expected_internal == lowered_internal and
            len(reachable_finite_site_ids) == target_coverage.get(
                "abi_finite_dispatch_site_count", 0) and
            target_coverage["missing_call_graph_instruction_count"] == 0),
    })
    blockers = (
        {"code": "PZWVLIVE001",
         "detail": "Python operation/host-boundary callbacks are not bound and proved."},
        {"code": "PZWVLIVE002",
         "detail": "The VM is not final-linked into the target image."},
        {"code": "PZWVLIVE003",
         "detail": "Pinned Z80 stack and frame-time bounds for the complete game are absent."},
        {"code": "PZWVLIVE004",
         "detail": ("Validated generator factories and next/iter/any/tuple consumers require "
                    "PyZ80Target_AttachGenerators; final target integration is not proved. General send, "
                    "throw, finally and yield-from protocols remain unimplemented.")},
        {"code": "PZWVLIVE005",
         "detail": ("Validated ABI-eligible free, bound-method, common-dispatch "
                    "and classmethod occurrences are direct numeric calls; exact "
                    "constructors use core allocate/bind/init/return semantics. "
                    "Super proxies, unsupported closure forms, omitted defaults, "
                    "star arguments, unbindable finite dispatch, host boundaries and "
                    "unresolved calls remain occurrence-specific adapters; "
                    "active interprocedural execution is not yet closed.")},
    )
    return WholeProgramVMArtifact(
        proof_bytecode=proof_bytecode, target_bytecode=target_bytecode,
        document=document, compact_document=compact_document,
        adapter_table=adapter_table, semantic_sha256=semantic,
        proof_bytecode_sha256=hashlib.sha256(proof_bytecode).hexdigest(),
        target_bytecode_sha256=hashlib.sha256(target_bytecode).hexdigest(),
        coverage=coverage, target_coverage=target_coverage,
        live=False, live_blockers=blockers)


def whole_program_vm_status(artifact: WholeProgramVMArtifact, *,
                            project_root: "str | Any") -> dict[str, Any]:
    """Return deterministic integration status without writing ``Build``.

    ``project_root`` is explicit so the main translator can hash/stage these
    files in its own atomic generation transaction.  Absolute host paths are
    intentionally absent from the returned status.
    """
    from pathlib import Path

    root = Path(project_root).resolve()
    runtime_sources = []
    for relative in RUNTIME_SOURCE_PATHS:
        path = root / relative
        if not path.is_file():
            raise WholeProgramVMError(
                "PZWV049", f"whole-program VM runtime source absent: {relative}")
        payload = path.read_bytes()
        runtime_sources.append({
            "path": relative,
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        })
    binding = {
        "artifact_semantic_sha256": artifact.semantic_sha256,
        "proof_bytecode_sha256": artifact.proof_bytecode_sha256,
        "target_bytecode_sha256": artifact.target_bytecode_sha256,
        "runtime_sources": runtime_sources,
    }
    return {
        "format": WHOLE_PROGRAM_VM_STATUS_FORMAT,
        "active_call_graph_semantic_sha256": artifact.document[
            "active_call_graph_semantic_sha256"],
        "artifact_semantic_sha256": artifact.semantic_sha256,
        "host_proof": {
            "format": WHOLE_PROGRAM_VM_FORMAT,
            "version": BYTECODE_VERSION,
            "bytes": len(artifact.proof_bytecode),
            "sha256": artifact.proof_bytecode_sha256,
            "deployment": False,
        },
        "target_bytecode": {
            "format": COMPACT_TARGET_VM_FORMAT,
            "version": TARGET_BYTECODE_VERSION,
            "bytes": len(artifact.target_bytecode),
            "sha256": artifact.target_bytecode_sha256,
            "addressing": "uint32-logical-offset-through-bank-reader",
        },
        "proof_coverage": dict(artifact.coverage),
        "target_coverage": dict(artifact.target_coverage),
        "adapter_table": [copy.deepcopy(item) for item in artifact.adapter_table],
        "function_id_table": list(artifact.target_coverage["function_id_table"]),
        "runtime_sources": runtime_sources,
        "runtime_binding_sha256": _sha256_json(binding),
        "execution_contract": {
            "iterative_c_interpreter": True,
            "c_recursion_for_vm_calls": False,
            "caller_owned_bounded_arena": True,
            "arena_locals_per_frame_width_bits": 16,
            "frame_slot_count_is_ssa_plus_unique_bound_names": True,
            "expected_proof_sha256_required_by_c_init": True,
            "unknown_operations_fail_closed": True,
            "source_order_preserved": True,
            "python_call_adapters_are_call_site_specific": True,
            "call_abi_consumer_enabled": artifact.target_coverage[
                "call_abi_input_enabled"],
            "call_abi_occurrences_bound_by_exact_cfg_path": artifact.target_coverage[
                "call_abi_input_enabled"],
            "call_abi_only_replaces_invocation": True,
            "constructor_allocate_bind_init_return_core": True,
            "constructor_allocation_is_single_target_adapter": True,
            "constructor_init_none_return_enforced": True,
            "abi_constructor_call_instruction_count": artifact.target_coverage[
                "abi_constructor_call_instruction_count"],
            "abi_eligible_call_instruction_count": artifact.target_coverage[
                "abi_eligible_call_instruction_count"],
            "abi_lowered_call_instruction_count": artifact.target_coverage[
                "abi_lowered_call_instruction_count"],
            "abi_unlowered_call_instruction_count": artifact.target_coverage[
                "abi_unlowered_call_instruction_count"],
            "abi_finite_dispatch_instruction_count": artifact.target_coverage[
                "abi_finite_dispatch_instruction_count"],
            "abi_finite_bound_dispatch_instruction_count":
                artifact.target_coverage[
                    "abi_finite_bound_dispatch_instruction_count"],
            "abi_finite_lexical_dispatch_instruction_count":
                artifact.target_coverage[
                    "abi_finite_lexical_dispatch_instruction_count"],
            "finite_dispatch_uses_runtime_identity_guard": True,
            "finite_dispatch_unknown_identity_fails_closed": True,
            "finite_bound_callback_receiver_is_runtime_checked": True,
            "finite_lexical_dispatch_environment": (
                "retained callable environment with scope hooks; "
                "one exact active owner without scope hooks"),
            "guarded_candidates_are_not_static_reachability_edges": True,
            "guarded_callable_function_count": artifact.target_coverage[
                "guarded_callable_function_count"],
            "guarded_body_calls_remain_site_specific_adapters": True,
            "guarded_body_adapter_instruction_count":
                artifact.target_coverage[
                    "guarded_body_adapter_instruction_count"],
            "abi_eligible_call_site_count": artifact.target_coverage[
                "abi_eligible_call_site_count"],
            "abi_lowered_call_site_count": artifact.target_coverage[
                "abi_lowered_call_site_count"],
            "abi_unlowered_call_site_count": artifact.target_coverage[
                "abi_unlowered_call_site_count"],
            "active_suspend_yield_protocol_executable": False,
            "active_internal_call_sites_lowered": artifact.target_coverage[
                "active_internal_call_sites_lowered"],
            "active_exact_internal_call_site_count": artifact.target_coverage[
                "active_exact_internal_call_site_count"],
            "active_internal_call_sites_unlowered": artifact.target_coverage[
                "active_internal_call_sites_unlowered"],
            "active_finite_dispatch_sites_lowered": artifact.target_coverage[
                "active_finite_dispatch_sites_lowered"],
            "active_interprocedural_execution_closed": artifact.target_coverage[
                "active_interprocedural_execution_closed"],
        },
        "live": artifact.live,
        "live_blockers": [dict(item) for item in artifact.live_blockers],
    }


def render_whole_program_vm_status(artifact: WholeProgramVMArtifact, *,
                                   project_root: "str | Any") -> bytes:
    """Render status bytes suitable for a caller-owned atomic transaction."""
    return (json.dumps(
        whole_program_vm_status(artifact, project_root=project_root),
        ensure_ascii=False, sort_keys=True, indent=2,
    ) + "\n").encode("utf-8")


Adapter = Callable[[str, list[Any], dict[str, Any], dict[str, Any]], Any]


@dataclasses.dataclass
class _OracleFrame:
    unit: dict[str, Any]
    block: str
    instruction: int
    locals: dict[str, Any]
    return_destination: str | None


class OracleGenerator:
    """Persistent generator state used by :class:`WholeProgramVMOracle`."""

    def __init__(self, oracle: "WholeProgramVMOracle", frames: list[_OracleFrame]) -> None:
        self._oracle = oracle
        self._frames = frames
        self._done = False

    def resume(self, value: Any = None, *, step_limit: int = 100000) -> Any:
        if self._done:
            raise StopIteration
        status, result = self._oracle._execute(
            self._frames, step_limit=step_limit, allow_yield=True,
            send_value=value)
        if status == "return":
            self._done = True
            raise StopIteration(result)
        return result


class WholeProgramVMOracle:
    """Iterative reference executor for decoded bytecode.

    It intentionally implements only layout-independent primitives.  All
    Python object operations require ``adapter`` and fail closed otherwise.
    """

    def __init__(self, image: bytes | WholeProgramVMArtifact, *,
                 adapter: Adapter | None = None, max_call_depth: int = 32) -> None:
        data = (image.proof_bytecode if isinstance(image, WholeProgramVMArtifact)
                else bytes(image))
        self.document = decode_whole_program_vm(data)
        self.adapter = adapter
        self.max_call_depth = max_call_depth
        self.functions = {item["callable_id"]: item for item in self.document["functions"]}
        self.units: dict[str, dict[str, Any]] = {}
        for item in self.document["functions"]:
            cfg = item["row"]["cfg"]
            self.units[item["callable_id"]] = cfg
            for program in cfg["expression_programs"]:
                self.units[program["program_id"]] = program

    def _new_frame(self, unit_name: str, arguments: Sequence[Any],
                   destination: str | None) -> _OracleFrame:
        if unit_name not in self.units:
            raise WholeProgramVMError("PZWV101", f"unknown unit {unit_name}")
        unit = self.units[unit_name]
        locals_: dict[str, Any] = {}
        if unit_name in self.functions:
            parameters = unit.get("signature", {}).get("parameters", [])
            if len(arguments) > len(parameters):
                raise WholeProgramVMError("PZWV102", "too many VM arguments")
            for spec, value in zip(parameters, arguments):
                locals_[spec["name"]] = value
        return _OracleFrame(unit, unit["entry"], 0, locals_, destination)

    @staticmethod
    def _blocks(frame: _OracleFrame) -> dict[str, dict[str, Any]]:
        return {block["name"]: block for block in frame.unit["blocks"]}

    @staticmethod
    def _resolve(value: Any, frames: Sequence[_OracleFrame]) -> Any:
        if isinstance(value, str) and value.startswith("%"):
            for frame in reversed(frames):
                if value in frame.locals:
                    return frame.locals[value]
            raise WholeProgramVMError("PZWV103", f"unbound SSA value {value}")
        if isinstance(value, list):
            return [WholeProgramVMOracle._resolve(item, frames) for item in value]
        if isinstance(value, dict):
            return {key: WholeProgramVMOracle._resolve(item, frames)
                    for key, item in value.items()}
        return value

    def _adapter(self, instruction: dict[str, Any], arguments: list[Any]) -> Any:
        if self.adapter is None:
            raise WholeProgramVMError(
                "PZWV104", f"no adapter for {instruction['op']}")
        return self.adapter(
            instruction["op"], arguments,
            instruction.get("attributes", {}), instruction.get("span", {}))

    def _execute(self, frames: list[_OracleFrame], *, step_limit: int,
                 allow_yield: bool, send_value: Any = None) -> tuple[str, Any]:
        del send_value  # reserved in the ABI; yield-result binding is adapter-owned
        steps = 0
        while frames:
            if steps >= step_limit:
                raise WholeProgramVMError("PZWV105", "oracle step limit exceeded")
            steps += 1
            frame = frames[-1]
            block = self._blocks(frame)[frame.block]
            if frame.instruction < len(block["instructions"]):
                instruction = block["instructions"][frame.instruction]
                frame.instruction += 1
                op = instruction["op"]
                raw = instruction["arguments"]
                result: Any = None
                writes = instruction.get("destination")
                if op == "constant":
                    result = raw[0]
                elif op == "load-name":
                    name = raw[0]
                    found = False
                    for owner in reversed(frames):
                        if name in owner.locals:
                            result, found = owner.locals[name], True
                            break
                    if not found:
                        result = self._adapter(instruction, [name])
                elif op == "store-name":
                    frame.locals[raw[0]] = self._resolve(raw[1], frames)
                elif op == "vm-binary-i32":
                    operator, left, right = raw
                    left = int(self._resolve(left, frames))
                    right = int(self._resolve(right, frames))
                    operations = {
                        "add": lambda: left + right,
                        "sub": lambda: left - right,
                        "mul": lambda: left * right,
                        "floordiv": lambda: left // right,
                        "mod": lambda: left % right,
                        "eq": lambda: left == right,
                        "lt": lambda: left < right,
                        "le": lambda: left <= right,
                    }
                    if operator not in operations:
                        raise WholeProgramVMError("PZWV106", f"unknown i32 op {operator}")
                    result = operations[operator]()
                elif op in ("vm-call", "execute-expression-cfg"):
                    target = raw[0]
                    values = ([self._resolve(item, frames) for item in raw[1:]]
                              if op == "vm-call" else [])
                    if len(frames) >= self.max_call_depth:
                        raise WholeProgramVMError("PZWV107", "call-frame arena overflow")
                    frames.append(self._new_frame(target, values, writes))
                    continue
                else:
                    result = self._adapter(
                        instruction,
                        [self._resolve(item, frames) for item in raw])
                if writes is not None:
                    frame.locals[writes] = result
                continue

            term = block["terminator"]
            op = term["op"]
            if op == "jump":
                frame.block, frame.instruction = term["targets"][0], 0
            elif op == "branch-truth":
                condition = self._resolve(term["arguments"][0], frames)
                frame.block = term["targets"][0 if bool(condition) else 1]
                frame.instruction = 0
            elif op in ("return", "return-expression"):
                value = (self._resolve(term["arguments"][0], frames)
                         if term["arguments"] else None)
                finished = frames.pop()
                if not frames:
                    return "return", value
                if finished.return_destination is not None:
                    frames[-1].locals[finished.return_destination] = value
            elif op in ("yield", "yield-value"):
                if not allow_yield:
                    raise WholeProgramVMError("PZWV108", "yield outside generator resume")
                value = (self._resolve(term["arguments"][0], frames)
                         if term["arguments"] else None)
                if len(term["targets"]) != 1:
                    raise WholeProgramVMError("PZWV109", "yield requires one resume target")
                frame.block, frame.instruction = term["targets"][0], 0
                return "yield", value
            else:
                synthetic = {"op": op, "attributes": {}, "span": term.get("span", {})}
                self._adapter(synthetic,
                              [self._resolve(item, frames) for item in term["arguments"]])
                raise WholeProgramVMError(
                    "PZWV110", f"adapter terminator {op} did not transfer control")
        raise WholeProgramVMError("PZWV111", "empty execution stack")

    def run(self, callable_id: str, arguments: Sequence[Any] = (), *,
            step_limit: int = 100000) -> Any:
        frames = [self._new_frame(callable_id, arguments, None)]
        status, value = self._execute(
            frames, step_limit=step_limit, allow_yield=False)
        assert status == "return"
        return value

    def generator(self, callable_id: str,
                  arguments: Sequence[Any] = ()) -> OracleGenerator:
        return OracleGenerator(
            self, [self._new_frame(callable_id, arguments, None)])


CompactAdapter = Callable[[int, list[Any], dict[str, Any]], Any]


@dataclasses.dataclass
class _CompactFrame:
    unit: int
    block: int
    instruction: int
    locals: list[Any]
    assigned: list[bool]
    names: dict[int, Any]
    return_destination: int | None
    lexical_parent_depth: int | None
    require_none_return: bool = False


class CompactTargetVMGenerator:
    def __init__(self, oracle: "CompactTargetVMOracle",
                 frames: list[_CompactFrame]) -> None:
        self.oracle = oracle
        self.frames = frames
        self.done = False

    def resume(self, value: Any = None, *, step_limit: int = 100000) -> Any:
        del value
        if self.done:
            raise StopIteration
        status, result = self.oracle._execute(
            self.frames, step_limit=step_limit, allow_yield=True)
        if status == "return":
            self.done = True
            raise StopIteration(result)
        return result


class CompactTargetVMOracle:
    """Iterative oracle that executes the stripped numeric PZVT image."""

    def __init__(self, image: bytes | WholeProgramVMArtifact, *,
                 adapter: CompactAdapter | None = None,
                 max_call_depth: int = 32) -> None:
        data = image.target_bytecode if isinstance(image, WholeProgramVMArtifact) else bytes(image)
        self.program = decode_compact_target_vm(
            data,
            expected_proof_semantic_sha256=(
                image.semantic_sha256
                if isinstance(image, WholeProgramVMArtifact) else None))
        self.adapter = adapter
        self.max_call_depth = max_call_depth
        self.artifact = image if isinstance(image, WholeProgramVMArtifact) else None
        self.function_ids = ({identifier: index for index, identifier in enumerate([
            *image.document["proven_reachable_callable_ids"],
            *image.document.get("guarded_callable_ids", ()),
        ])}
            if isinstance(image, WholeProgramVMArtifact) else {})

    def _function_index(self, function: str | int) -> int:
        if isinstance(function, int):
            index = function
        else:
            if function not in self.function_ids:
                raise WholeProgramVMError("PZWV251", f"unknown compact function {function}")
            index = self.function_ids[function]
        if index < 0 or index >= len(self.program["functions"]):
            raise WholeProgramVMError("PZWV251", f"unknown compact function {function}")
        return index

    def _new_frame(self, unit: int, destination: int | None,
                   arguments: Sequence[Any] = (), *,
                   lexical_parent_depth: int | None = None,
                   require_none_return: bool = False) -> _CompactFrame:
        spec = self.program["units"][unit]
        count = spec["local_count"]
        parameters = spec["parameter_name_constants"]
        if len(arguments) != len(parameters):
            raise WholeProgramVMError("PZWV262", "compact call argument arity mismatch")
        if bool(spec["lexical_parent_mode"]) != (
                lexical_parent_depth is not None):
            raise WholeProgramVMError(
                "PZWV272", "compact lexical parent contract mismatch")
        frame = _CompactFrame(
            unit=unit, block=spec["entry_block"], instruction=0,
            locals=[None] * count, assigned=[False] * count, names={},
            return_destination=destination,
            lexical_parent_depth=lexical_parent_depth,
            require_none_return=require_none_return)
        frame.names.update(zip(parameters, arguments))
        return frame

    def _operand(self, operand: dict[str, int],
                 frames: Sequence[_CompactFrame]) -> Any:
        if operand["kind"] == "constant":
            return self.program["constants"][operand["id"]]
        index = operand["id"]
        # SSA identifiers are unit-local.  Looking through caller frames would
        # be dynamic scoping and can silently read an unrelated slot which
        # happens to have the same dense numeric ID.
        frame = frames[-1]
        if index < len(frame.locals) and frame.assigned[index]:
            return frame.locals[index]
        raise WholeProgramVMError("PZWV252", f"unbound compact local {index}")

    @staticmethod
    def _store(frame: _CompactFrame, destination: int, value: Any) -> None:
        if destination < 0 or destination >= len(frame.locals):
            raise WholeProgramVMError("PZWV253", "compact local arena overflow")
        frame.locals[destination] = value
        frame.assigned[destination] = True

    def _invoke(self, adapter_id: int, arguments: list[Any]) -> Any:
        if self.adapter is None:
            raise WholeProgramVMError("PZWV254", f"no compact adapter {adapter_id}")
        descriptor: dict[str, Any] = {}
        if self.artifact is not None:
            descriptor = self.artifact.adapter_table[adapter_id]
        return self.adapter(adapter_id, arguments, descriptor)

    def _execute(self, frames: list[_CompactFrame], *, step_limit: int,
                 allow_yield: bool) -> tuple[str, Any]:
        reverse_binary = {value: key for key, value in _TARGET_BINARY_IDS.items()}
        for _step in range(step_limit):
            if not frames:
                raise WholeProgramVMError("PZWV255", "empty compact frame stack")
            frame = frames[-1]
            block = self.program["units"][frame.unit]["blocks"][frame.block]
            if frame.instruction < len(block["instructions"]):
                item = block["instructions"][frame.instruction]
                frame.instruction += 1
                opcode = item["opcode"]
                if opcode == _TARGET_CORE_CONSTANT:
                    self._store(frame, item["destination"],
                                self._operand(item["arguments"][0], frames))
                elif opcode in (_TARGET_CORE_LOAD_NAME, _TARGET_CORE_LOAD_LOCAL_NAME):
                    name = item["name_constant"]
                    found = False
                    owner_depth = len(frames) - 1
                    visited: set[int] = set()
                    while owner_depth not in visited:
                        visited.add(owner_depth)
                        owner = frames[owner_depth]
                        if name in owner.names:
                            value, found = owner.names[name], True
                            break
                        if (opcode == _TARGET_CORE_LOAD_LOCAL_NAME and owner.unit ==
                                self.program["functions"][item["owner_function"]]):
                            break
                        parent = owner.lexical_parent_depth
                        if parent is None or parent < 0 or parent >= owner_depth:
                            break
                        owner_depth = parent
                    if not found:
                        if opcode == _TARGET_CORE_LOAD_LOCAL_NAME:
                            raise WholeProgramVMError("PZWV261", "unbound Python local")
                        value = self._invoke(
                            item["fallback_adapter_id"],
                            [self.program["constants"][name]])
                    self._store(frame, item["destination"], value)
                elif opcode == _TARGET_CORE_STORE_NAME:
                    frame.names[item["name_constant"]] = self._operand(item["value"], frames)
                elif opcode == _TARGET_CORE_BINARY_I32:
                    left = int(self._operand(item["left"], frames))
                    right = int(self._operand(item["right"], frames))
                    operator = reverse_binary[item["operator"]]
                    operations = {
                        "add": lambda: left + right, "sub": lambda: left - right,
                        "mul": lambda: left * right,
                        "floordiv": lambda: left // right, "mod": lambda: left % right,
                        "eq": lambda: left == right, "lt": lambda: left < right,
                        "le": lambda: left <= right,
                    }
                    self._store(frame, item["destination"], operations[operator]())
                elif opcode in (_TARGET_CORE_CALL, _TARGET_CORE_EXPRESSION):
                    if len(frames) >= self.max_call_depth:
                        raise WholeProgramVMError("PZWV256", "compact call arena overflow")
                    if opcode == _TARGET_CORE_CALL:
                        unit = self.program["functions"][item["function"]]
                        arguments = [self._operand(arg, frames)
                                     for arg in item["arguments"]]
                    else:
                        unit = item["unit"]
                        arguments = []
                    destination_plus = item["destination_plus_one"]
                    frames.append(self._new_frame(
                        unit, None if not destination_plus else destination_plus - 1,
                        arguments,
                        lexical_parent_depth=(
                            len(frames) - 1
                            if self.program["units"][unit]["lexical_parent_mode"]
                            else None)))
                elif opcode == _TARGET_CORE_CONSTRUCT:
                    if len(frames) >= self.max_call_depth:
                        raise WholeProgramVMError(
                            "PZWV256", "compact call arena overflow")
                    allocated = self._invoke(
                        item["allocation_adapter_id"],
                        [self._operand(item["constructed_class"], frames)])
                    destination = item["destination_plus_one"] - 1
                    self._store(frame, destination, allocated)
                    arguments = [allocated, *[
                        self._operand(arg, frames)
                        for arg in item["arguments"]]]
                    unit = self.program["functions"][item["function"]]
                    frames.append(self._new_frame(
                        unit, None, arguments,
                        lexical_parent_depth=None,
                        require_none_return=True))
                elif opcode == _TARGET_CORE_NOP:
                    pass
                elif opcode == _TARGET_CORE_DATACLASS_INIT:
                    arguments = [self._operand(arg, frames)
                                 for arg in item["arguments"]]
                    if not arguments:
                        raise WholeProgramVMError(
                            "PZWV262", "dataclass init has no self argument")
                    result = self._invoke(
                        item["field_store_adapter_id"], arguments)
                    if result is not None:
                        raise WholeProgramVMError(
                            "PZWV267", "dataclass field adapter returned non-None")
                    destination = item["destination_plus_one"] - 1
                    self._store(frame, destination, None)
                    post_plus = item["post_init_function_plus_one"]
                    if post_plus:
                        if len(frames) >= self.max_call_depth:
                            raise WholeProgramVMError(
                                "PZWV256", "compact call arena overflow")
                        unit = self.program["functions"][post_plus - 1]
                        frames.append(self._new_frame(
                            unit, destination, [arguments[0]],
                            lexical_parent_depth=None,
                            require_none_return=True))
                elif opcode in (_TARGET_CORE_GUARDED_DISPATCH,
                                 _TARGET_CORE_GUARDED_BOUND_DISPATCH,
                                 _TARGET_CORE_GUARDED_LEXICAL_DISPATCH):
                    if len(frames) >= self.max_call_depth:
                        raise WholeProgramVMError(
                            "PZWV256", "compact call arena overflow")
                    callable_value = self._operand(item["callable"], frames)
                    selected = self._invoke(
                        item["guard_adapter_id"], [callable_value])
                    if (type(selected) is not int or selected < 0 or
                            selected >= len(item["candidates"])):
                        raise WholeProgramVMError(
                            "PZWV270", "finite dispatch guard returned invalid index")
                    candidate = item["candidates"][selected]
                    arguments = [self._operand(arg, frames)
                                 for arg in candidate["arguments"]]
                    if opcode == _TARGET_CORE_GUARDED_BOUND_DISPATCH:
                        receiver = self._invoke(
                            item["receiver_adapter_id"],
                            [callable_value, selected])
                        arguments.insert(0, receiver)
                    unit = self.program["functions"][candidate["function"]]
                    lexical_parent_depth = None
                    if opcode == _TARGET_CORE_GUARDED_LEXICAL_DISPATCH:
                        owner_function = candidate.get(
                            "lexical_owner_function")
                        if (not isinstance(owner_function, int) or
                                not 0 <= owner_function < len(
                                    self.program["functions"])):
                            raise WholeProgramVMError(
                                "PZWV272", "finite lexical owner is invalid")
                        owner_unit = self.program["functions"][owner_function]
                        matches = [
                            depth for depth, active in enumerate(frames)
                            if active.unit == owner_unit]
                        if len(matches) != 1:
                            raise WholeProgramVMError(
                                "PZWV272",
                                "finite lexical owner frame is absent/ambiguous")
                        lexical_parent_depth = matches[0]
                    frames.append(self._new_frame(
                        unit, item["destination_plus_one"] - 1, arguments,
                        lexical_parent_depth=lexical_parent_depth))
                elif opcode >= _TARGET_ADAPTER_BASE or opcode in (_TARGET_CORE_POSITIONAL_CLOSURE_CALL, _TARGET_CORE_KEYWORD_CLOSURE_CALL):
                    arguments = [self._operand(arg, frames) for arg in item["arguments"]]
                    result = self._invoke(item["adapter_id"], arguments)
                    if item["destination_plus_one"]:
                        self._store(frame, item["destination_plus_one"] - 1, result)
                else:
                    raise WholeProgramVMError("PZWV257", f"unknown compact opcode {opcode}")
                continue

            term = block["terminator"]
            opcode = term["opcode"]
            if opcode == _TARGET_TERM_JUMP:
                frame.block, frame.instruction = term["targets"][0], 0
            elif opcode == _TARGET_TERM_BRANCH:
                value = self._operand(term["arguments"][0], frames)
                frame.block = term["targets"][0 if bool(value) else 1]
                frame.instruction = 0
            elif opcode == _TARGET_TERM_RETURN:
                value = (self._operand(term["arguments"][0], frames)
                         if term["arguments"] else None)
                finished = frames.pop()
                if finished.require_none_return and value is not None:
                    raise WholeProgramVMError(
                        "PZWV267", "constructor __init__ returned non-None")
                if not frames:
                    return "return", value
                if finished.return_destination is not None:
                    self._store(frames[-1], finished.return_destination, value)
            elif opcode in (_TARGET_TERM_YIELD, _TARGET_TERM_YIELD_NEXT):
                if not allow_yield:
                    raise WholeProgramVMError("PZWV258", "compact yield outside generator")
                value = (self._operand(term["arguments"][0], frames)
                         if term["arguments"] else None)
                frame.block, frame.instruction = term["targets"][0], 0
                return "yield", value
            elif opcode >= _TARGET_ADAPTER_BASE:
                arguments = [self._operand(arg, frames) for arg in term["arguments"]]
                self._invoke(term["adapter_id"], arguments)
                raise WholeProgramVMError(
                    "PZWV259", "compact adapter terminator cannot guess control transfer")
            else:
                raise WholeProgramVMError("PZWV260", f"unknown compact term {opcode}")
        raise WholeProgramVMError("PZWV261", "compact oracle step limit exceeded")

    def run(self, function: str | int, arguments: Sequence[Any] = (), *,
            step_limit: int = 100000) -> Any:
        index = self._function_index(function)
        frames = [self._new_frame(
            self.program["functions"][index], None, arguments)]
        status, value = self._execute(frames, step_limit=step_limit, allow_yield=False)
        assert status == "return"
        return value

    def generator(self, function: str | int,
                  arguments: Sequence[Any] = ()) -> CompactTargetVMGenerator:
        index = self._function_index(function)
        return CompactTargetVMGenerator(
            self, [self._new_frame(
                self.program["functions"][index], None, arguments)])


__all__ = [
    "BYTECODE_MAGIC",
    "BYTECODE_VERSION",
    "COMPACT_TARGET_VM_FORMAT",
    "RUNTIME_SOURCE_PATHS",
    "WHOLE_PROGRAM_VM_FORMAT",
    "WHOLE_PROGRAM_VM_STATUS_FORMAT",
    "TARGET_BYTECODE_MAGIC",
    "TARGET_BYTECODE_VERSION",
    "OracleGenerator",
    "CompactTargetVMGenerator",
    "CompactTargetVMOracle",
    "WholeProgramVMArtifact",
    "WholeProgramVMError",
    "WholeProgramVMOracle",
    "build_whole_program_vm",
    "build_compact_target_vm",
    "decode_compact_target_vm",
    "decode_whole_program_vm",
    "render_whole_program_vm_status",
    "whole_program_vm_status",
]
