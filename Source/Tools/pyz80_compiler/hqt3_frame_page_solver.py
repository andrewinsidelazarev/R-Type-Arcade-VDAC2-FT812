"""Frame-local HQT3/RAM_G page feasibility proof.

This pass deliberately stops one level before a runtime cache implementation.
It derives immutable page atoms only from the active Python/ROM descriptor
identity and measures those atoms with the same lossless FT812 compiler used by
the upstream HQT3 passes.  Event order is never treated as an eviction proof.

The important distinction in this report is between:

* a finite *record* bound (228 draw records), which is already proved; and
* a byte-exact set of pages used by those records in two consecutive FT812
  display-list generations, which is not yet proved.

Without the second fact it is unsound to claim that paging fits RAM_G.  The
report therefore supplies strict conditional lower bounds, conservative
finite upper estimates, and the exact missing lifetime/state facts.
"""

from __future__ import annotations

import ast
import hashlib
import json
import struct
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .active_call_graph import (
    ACTIVE_CALL_GRAPH_FORMAT,
    ACTIVE_CALL_GRAPH_STATUS,
    ActiveCallGraphError,
    validate_active_call_graph_report,
)
from .frame_record_bound import FRAME_RECORD_BOUND_FORMAT
from .frame_sprite_fragment_envelope import (
    FRAME_SPRITE_FRAGMENT_ENVELOPE_FORMAT,
)
from .full_hqt3_inventory import (
    FULL_HQT3_INVENTORY_FORMAT,
    FULL_HQT3_INVENTORY_STATUS,
)
from .hqt3_partition_solver import (
    HQT3_PARTITION_SOLVER_FORMAT,
    HQT3_PARTITION_SOLVER_STATUS,
    PROBLEM_SCOPE_IDS,
    _descriptor_page_rows,
    _pseudo_scope,
)
from .hqt3_ramg_schedule import (
    FT812_RAM_G_BYTES,
    HQT3_RAMG_SCHEDULE_FORMAT,
    HQT3_RAMG_SCHEDULE_STATUS,
    TSCONF_RAM_BYTES,
    _compile_pixel_pack,
    _scope_cells,
    _sha256_value,
)


HQT3_FRAME_PAGE_SOLVER_FORMAT = "pyz80-hqt3-frame-page-solver-v1"
HQT3_FRAME_PAGE_SOLVER_STATUS = (
    "EXACT_PAGE_ATOMS_AND_COLD_MISS_FLOOR_LIFETIME_UPPER_BOUND_BLOCKED")

FRAME_RATE_HZ = 55
FRAME_PERIOD_MICROSECONDS = 1_000_000 / FRAME_RATE_HZ
DISPLAY_LIST_GENERATIONS = 2
FRAME_RECORD_LIMIT = 228
EXACT_NONFIT_EVENT_ID = "stage:2:event:BCAB"
EXACT_NONFIT_REQUIREMENT_ID = "event-requirement:ee3156c5af19be0f99b57b2b"
RAMG_OVERSIZED_SCOPE_IDS = (
    "stage:2:class:Enemy6F89",
    "stage:2:class:Multipart915BChild",
    "stage:5:class:Formation78F8Child",
)
HQT_STATE_OVERFLOW_SCOPE_IDS = (
    "stage:2:class:Child8D85",
    "stage:2:class:Enemy6F89",
    "stage:5:class:Formation78F8Child",
)


class HQT3FramePageSolverError(ValueError):
    """The frame-page proof input changed or a claim cannot be derived."""


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def _value_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            while block := source.read(1024 * 1024):
                digest.update(block)
    except OSError as exc:
        raise HQT3FramePageSolverError(f"cannot hash {path}: {exc}") from exc
    return digest.hexdigest()


def _load_json(path: Path, name: str) -> tuple[dict[str, object], bytes]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HQT3FramePageSolverError(f"cannot read {name} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise HQT3FramePageSolverError(f"{name} is not a JSON object")
    return value, raw


def _analysis_hash_valid(value: Mapping[str, object], *, drop_status: bool) -> bool:
    semantic = dict(value)
    stored = semantic.pop("analysis_sha256", None)
    if drop_status:
        semantic.pop("status", None)
    return isinstance(stored, str) and _sha256_value(semantic) == stored


def _dict(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise HQT3FramePageSolverError(f"{name} is missing")
    return value


def _list(value: object, name: str) -> list[object]:
    if not isinstance(value, list):
        raise HQT3FramePageSolverError(f"{name} is missing")
    return value


def _ast_sha256(node: ast.AST) -> str:
    return hashlib.sha256(ast.dump(
        node, annotate_fields=True, include_attributes=False,
    ).encode("utf-8")).hexdigest()


def _class(tree: ast.Module, name: str) -> ast.ClassDef:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise HQT3FramePageSolverError(f"active class {name} disappeared")


def _method(owner: ast.ClassDef, name: str) -> ast.FunctionDef:
    for node in owner.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise HQT3FramePageSolverError(f"active method {owner.name}.{name} disappeared")


def _self_literal(method: ast.FunctionDef, attribute: str) -> tuple[object, int]:
    for node in ast.walk(method):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        value = node.value
        for target in targets:
            if (isinstance(target, ast.Attribute) and
                    isinstance(target.value, ast.Name) and
                    target.value.id == "self" and target.attr == attribute):
                try:
                    return ast.literal_eval(value), node.lineno
                except (ValueError, TypeError) as exc:
                    raise HQT3FramePageSolverError(
                        f"self.{attribute} is no longer literal") from exc
    raise HQT3FramePageSolverError(f"self.{attribute} assignment disappeared")


def _class_literal(owner: ast.ClassDef, attribute: str) -> tuple[object, int]:
    for node in owner.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if any(isinstance(target, ast.Name) and target.id == attribute
               for target in targets):
            try:
                return ast.literal_eval(node.value), node.lineno
            except (ValueError, TypeError) as exc:
                raise HQT3FramePageSolverError(
                    f"{owner.name}.{attribute} is no longer literal") from exc
    raise HQT3FramePageSolverError(
        f"{owner.name}.{attribute} assignment disappeared")


def _call_names(method: ast.FunctionDef) -> list[tuple[str, int]]:
    rows: list[tuple[str, int]] = []
    for node in ast.walk(method):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        if isinstance(target, ast.Name):
            name = target.id
        elif isinstance(target, ast.Attribute):
            parts = [target.attr]
            value = target.value
            while isinstance(value, ast.Attribute):
                parts.append(value.attr)
                value = value.value
            if isinstance(value, ast.Name):
                parts.append(value.id)
            name = ".".join(reversed(parts))
        else:
            continue
        rows.append((name, node.lineno))
    return sorted(rows, key=lambda item: item[1])


def _source_evidence(
        root: Path,
        inventory: Mapping[str, object],
        call_graph: Mapping[str, object],
        rom: bytes,
        ) -> dict[str, object]:
    source_path = root / "Source" / "Python" / "rtype_port" / "enemies.py"
    try:
        source_raw = source_path.read_bytes()
        source = source_raw.decode("utf-8")
        tree = ast.parse(source, filename=str(source_path))
    except (OSError, UnicodeError, SyntaxError) as exc:
        raise HQT3FramePageSolverError(
            f"cannot parse active enemies.py: {exc}") from exc
    source_hash = hashlib.sha256(source_raw).hexdigest()
    binding = _dict(inventory.get("source_binding"), "inventory source binding")
    if source_hash != binding.get("enemies_source_sha256"):
        raise HQT3FramePageSolverError("active enemies.py differs from inventory")

    world = _class(tree, "M72EnemyWorld")
    world_update = _method(world, "update")
    dispatch = _method(world, "_dispatch")
    parent = _class(tree, "Multipart915BParent")
    parent_init = _method(parent, "__init__")
    parent_update = _method(parent, "update")
    child = _class(tree, "Multipart915BChild")
    child_init = _method(child, "__init__")
    pending = _class(tree, "M72PendingList")
    pending_append = _method(pending, "append")
    enemy = _class(tree, "Enemy")

    sequence, sequence_line = _self_literal(parent_init, "sequence")
    timer, timer_line = _self_literal(parent_init, "timer")
    if sequence != 0x40C6 or timer != 1:
        raise HQT3FramePageSolverError("Multipart915BParent first-spawn literals changed")
    initializers, initializer_line = _class_literal(child, "INITIALIZERS")
    if not isinstance(initializers, dict) or initializers.get(0x9246) != (
            "first", 0x40, 0x419E):
        raise HQT3FramePageSolverError("Multipart915BChild initial descriptor changed")

    update_calls = _call_names(world_update)
    parent_calls = _call_names(parent_update)
    dispatch_calls = _call_names(dispatch)
    pending_calls = _call_names(pending_append)
    if not any(name.endswith("_dispatch") for name, _line in update_calls):
        raise HQT3FramePageSolverError("world event dispatch call disappeared")
    if not any(name.endswith("enemies.extend") for name, _line in update_calls):
        raise HQT3FramePageSolverError("pending-to-live extension disappeared")
    if not any(name == "Multipart915BChild" for name, _line in parent_calls):
        raise HQT3FramePageSolverError("multipart child construction disappeared")
    if not any(name.endswith("pending.append") for name, _line in parent_calls):
        raise HQT3FramePageSolverError("multipart pending append disappeared")
    if not any(name == "Multipart915BParent" for name, _line in dispatch_calls):
        raise HQT3FramePageSolverError("$915B dispatch construction disappeared")
    if not any(name.endswith("enemy.update") for name, _line in pending_calls):
        raise HQT3FramePageSolverError("same-pass pending update rule disappeared")

    if len(rom) != 0x100000:
        raise HQT3FramePageSolverError("active World ROM size changed")

    def word(address: int) -> int:
        return struct.unpack_from("<H", rom, 0x10000 + (address & 0xFFFF))[0]

    command = word(0xBCAB + 2)
    dispatch_offset = (command >> 9) & 0x7E
    handler = word(0xB92D + dispatch_offset)
    first_initializer = word(0x40C6)
    first_delay = word(0x40C8)
    if (command != 0x7404 or handler != 0x915B or
            first_initializer != 0x9246 or first_delay != 10):
        raise HQT3FramePageSolverError("BCAB ROM witness changed")

    inventory_rows = _dict(
        call_graph.get("callable_inventory"), "active callable inventory")
    callables = _list(inventory_rows.get("callables"), "active callables")
    graph = _dict(call_graph.get("call_graph"), "active call graph")
    reachable_value = _list(
        graph.get("proven_reachable_callable_ids"), "reachable callable IDs")
    reachable = {str(item) for item in reachable_value}
    wanted = {
        "M72EnemyWorld.update",
        "M72EnemyWorld._dispatch",
        "Multipart915BParent.__init__",
        "Multipart915BParent.update",
        "Multipart915BChild.__init__",
        "Multipart915BChild.update",
        "Enemy6F89.update",
        "Formation78F8Parent.update",
        "Formation78F8Child.update",
    }
    active_rows: list[dict[str, object]] = []
    found: set[str] = set()
    for raw in callables:
        row = _dict(raw, "active callable row")
        qualname = row.get("qualname")
        if qualname not in wanted:
            continue
        callable_id = row.get("callable_id")
        if not isinstance(callable_id, str):
            raise HQT3FramePageSolverError("active callable ID is malformed")
        found.add(str(qualname))
        active_rows.append({
            "qualname": qualname,
            "callable_id": callable_id,
            "ast_sha256": row.get("ast_sha256"),
            "proven_reachable_by_exact_call_edges": callable_id in reachable,
        })
    if found != wanted:
        raise HQT3FramePageSolverError("active callable witness set changed")

    scheduler_default = None
    scheduler_line = None
    for node in enemy.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "scheduler_priority":
                scheduler_default = ast.literal_eval(node.value)
                scheduler_line = node.lineno
                break
    if scheduler_default != 0x8010:
        raise HQT3FramePageSolverError("Enemy scheduler priority default changed")

    return {
        "path": source_path.relative_to(root).as_posix(),
        "sha256": source_hash,
        "class_method_ast_sha256": {
            "M72EnemyWorld.update": _ast_sha256(world_update),
            "M72EnemyWorld._dispatch": _ast_sha256(dispatch),
            "M72PendingList.append": _ast_sha256(pending_append),
            "Multipart915BParent.__init__": _ast_sha256(parent_init),
            "Multipart915BParent.update": _ast_sha256(parent_update),
            "Multipart915BChild.__init__": _ast_sha256(child_init),
        },
        "bcab_rom_witness": {
            "event_address": 0xBCAB,
            "command": command,
            "dispatch_offset": dispatch_offset,
            "handler": handler,
            "parent_sequence": sequence,
            "parent_timer": timer,
            "first_initializer": first_initializer,
            "first_delay_frames": first_delay,
            "first_child_resource_type": 0x40,
            "first_child_descriptor": 0x419E,
            "sequence_assignment_line": sequence_line,
            "timer_assignment_line": timer_line,
            "initializer_table_line": initializer_line,
            "scheduler_priority_default": scheduler_default,
            "scheduler_priority_line": scheduler_line,
            "allocation_success_required": True,
        },
        "active_callable_witnesses": sorted(
            active_rows, key=lambda item: str(item["qualname"])),
        "active_call_graph_exactly_reaches_complete_child_chain": all(
            row["proven_reachable_by_exact_call_edges"] for row in active_rows),
        "interpretation": (
            "BCAB and the first descriptor are exact source/ROM facts; the "
            "call graph does not yet prove the complete dynamic update/child "
            "chain, so no whole-lifetime residency claim follows"),
    }


def _compact_atom(page: Mapping[str, object]) -> dict[str, object]:
    cost = _dict(page.get("full_page_cost"), "page cost")
    pixel = _dict(cost.get("pixel"), "page pixel cost")
    hqt = _dict(cost.get("hqt3"), "page HQT3")
    targets = _dict(cost.get("partition_targets"), "page targets")
    bank = _dict(page.get("bank"), "page bank")
    if (page.get("axis") != "exact-bank-plus-rom-descriptor" or
            page.get("template_atomic") is not True or
            page.get("arbitrary_size_cut") is not False or
            page.get("runtime_eviction_permitted") is not False or
            targets.get("all_targets_pass") is not True):
        raise HQT3FramePageSolverError("non-semantic or non-fitting page atom")
    row = {
        "page_id": page.get("partition_id"),
        "template_index": page.get("template_index"),
        "bank_key": bank.get("encoded_hqt3_key"),
        "bank_kind": bank.get("kind"),
        "bank_value": bank.get("value"),
        "descriptor_address": page.get("descriptor_address"),
        "resource_types": page.get("resource_types"),
        "ram_g_bytes": pixel.get("ft812_payload_bytes"),
        "pixel_sha256": pixel.get("relocatable_payload_sha256"),
        "hqt3_bytes": hqt.get("total_bytes"),
        "hqt3_records": hqt.get("record_count"),
        "hqt3_cells": hqt.get("cell_reference_count"),
        "hqt3_states": hqt.get("state_count"),
        "hqt3_indices_fit": hqt.get(
            "uint16_record_cell_and_uint8_state_indices_fit"),
        "semantic_axis": "exact-bank-plus-rom-descriptor",
        "arbitrary_size_cut": False,
        "eviction_inferred": False,
    }
    integers = (
        row["template_index"], row["bank_key"], row["descriptor_address"],
        row["ram_g_bytes"], row["hqt3_bytes"], row["hqt3_records"],
        row["hqt3_cells"], row["hqt3_states"],
    )
    if (not all(isinstance(item, int) and item >= 0 for item in integers) or
            not isinstance(row["page_id"], str) or
            not isinstance(row["pixel_sha256"], str) or
            row["ram_g_bytes"] >= FT812_RAM_G_BYTES or
            row["hqt3_indices_fit"] is not True or
            row["hqt3_records"] > 0xFFFF or row["hqt3_cells"] > 0xFFFF or
            row["hqt3_states"] > 256):
        raise HQT3FramePageSolverError("page atom physical fields are invalid")
    return row


def _atom_summary(
        scope_id: str,
        rows: Sequence[Mapping[str, object]],
        max_records_per_object: int,
        ) -> dict[str, object]:
    if not rows:
        raise HQT3FramePageSolverError(f"{scope_id} has no page atoms")
    sizes = sorted((int(row["ram_g_bytes"]) for row in rows), reverse=True)
    page_ref_limit = min(
        len(rows), FRAME_RECORD_LIMIT, 94 * max_records_per_object)
    one_generation_upper = sum(sizes[:page_ref_limit])
    return {
        "scope_id": scope_id,
        "page_atom_count": len(rows),
        "page_atom_domain_sha256": _value_sha256(list(rows)),
        "all_atoms_semantic": True,
        "all_atoms_individually_strict_ram_g_fit": True,
        "minimum_atom_bytes": min(sizes),
        "maximum_atom_bytes": max(sizes),
        "maximum_atom_page_ids": sorted(
            str(row["page_id"]) for row in rows
            if int(row["ram_g_bytes"]) == max(sizes)),
        "max_records_per_object": max_records_per_object,
        "pool_slot_upper_bound": 94,
        "page_reference_upper_bound": page_ref_limit,
        "one_generation_sum_of_largest_distinct_atoms_bytes": (
            one_generation_upper),
        "two_generation_sum_without_cross_frame_dedup_bytes": (
            DISPLAY_LIST_GENERATIONS * one_generation_upper),
        "upper_estimate_is_reachability_tight": False,
        "exact_per_frame_page_set_proved": False,
    }


def _class_record_limits(bound: Mapping[str, object]) -> dict[str, int]:
    multiplicity = _dict(bound.get("object_multiplicity"), "object multiplicity")
    rows = _list(multiplicity.get("classes"), "class multiplicities")
    wanted = {
        "Child8D85",
        "Enemy6F89",
        "Multipart915BChild",
        "Formation78F8Child",
    }
    result: dict[str, int] = {}
    for raw in rows:
        row = _dict(raw, "class multiplicity row")
        name = row.get("class_name")
        if name not in wanted:
            continue
        count = row.get("max_records_per_object")
        if not isinstance(count, int) or count < 1:
            raise HQT3FramePageSolverError("class record multiplicity changed")
        result[str(name)] = count
    if set(result) != wanted:
        raise HQT3FramePageSolverError("problem class record bounds disappeared")
    return result


def _binding(
        root: Path,
        path: Path,
        raw: bytes,
        value: Mapping[str, object],
        semantic_key: str,
        ) -> dict[str, object]:
    return {
        "path": path.relative_to(root).as_posix(),
        "file_sha256": hashlib.sha256(raw).hexdigest(),
        semantic_key: value.get(semantic_key),
        "format": value.get("format"),
        "status": value.get("status"),
    }


def analyze_hqt3_frame_page_solver(
        project_root: Path,
        *,
        inventory_path: Path | None = None,
        schedule_path: Path | None = None,
        partition_path: Path | None = None,
        frame_bound_path: Path | None = None,
        frame_envelope_path: Path | None = None,
        call_graph_path: Path | None = None,
        ) -> dict[str, object]:
    root = Path(project_root).resolve()
    build = root / "Build"
    paths = {
        "inventory": (build / "rtype_python_full_hqt3_inventory_status.json"
                      if inventory_path is None else Path(inventory_path).resolve()),
        "schedule": (build / "rtype_python_hqt3_ramg_schedule_status.json"
                     if schedule_path is None else Path(schedule_path).resolve()),
        "partition": (build / "rtype_python_hqt3_partition_solver_status.json"
                      if partition_path is None else Path(partition_path).resolve()),
        "frame_bound": (build / "rtype_python_frame_record_bound_status.json"
                       if frame_bound_path is None else Path(frame_bound_path).resolve()),
        "frame_envelope": (
            build / "rtype_python_frame_sprite_fragment_envelope_status.json"
            if frame_envelope_path is None else Path(frame_envelope_path).resolve()),
        "call_graph": (build / "rtype_python_active_call_graph_status.json"
                       if call_graph_path is None else Path(call_graph_path).resolve()),
    }
    loaded = {name: _load_json(path, name) for name, path in paths.items()}
    inventory, inventory_raw = loaded["inventory"]
    schedule, schedule_raw = loaded["schedule"]
    partition, partition_raw = loaded["partition"]
    bound, bound_raw = loaded["frame_bound"]
    envelope, envelope_raw = loaded["frame_envelope"]
    call_graph, call_graph_raw = loaded["call_graph"]

    if (inventory.get("format") != FULL_HQT3_INVENTORY_FORMAT or
            inventory.get("status") != FULL_HQT3_INVENTORY_STATUS or
            not _analysis_hash_valid(inventory, drop_status=True)):
        raise HQT3FramePageSolverError("full HQT3 inventory binding changed")
    if (schedule.get("format") != HQT3_RAMG_SCHEDULE_FORMAT or
            schedule.get("status") != HQT3_RAMG_SCHEDULE_STATUS or
            not _analysis_hash_valid(schedule, drop_status=False)):
        raise HQT3FramePageSolverError("RAM_G schedule binding changed")
    if (partition.get("format") != HQT3_PARTITION_SOLVER_FORMAT or
            partition.get("status") != HQT3_PARTITION_SOLVER_STATUS or
            not _analysis_hash_valid(partition, drop_status=False)):
        raise HQT3FramePageSolverError("partition solver binding changed")
    if (bound.get("format") != FRAME_RECORD_BOUND_FORMAT or
            bound.get("proof_complete") is not True or
            bound.get("certified_frame_max_records") != FRAME_RECORD_LIMIT):
        raise HQT3FramePageSolverError("frame record bound changed")
    if (envelope.get("format") != FRAME_SPRITE_FRAGMENT_ENVELOPE_FORMAT or
            _dict(envelope.get("record_envelope"), "frame envelope").get(
                "certified_frame_max_records") != FRAME_RECORD_LIMIT):
        raise HQT3FramePageSolverError("frame sprite envelope changed")
    if (call_graph.get("format") != ACTIVE_CALL_GRAPH_FORMAT or
            call_graph.get("status") != ACTIVE_CALL_GRAPH_STATUS or
            call_graph.get("live") is not False):
        raise HQT3FramePageSolverError("active call graph binding changed")
    try:
        validate_active_call_graph_report(root, call_graph)
    except ActiveCallGraphError as exc:
        raise HQT3FramePageSolverError(
            f"active call graph validation failed: {exc}") from exc

    schedule_binding = _dict(
        schedule.get("inventory_binding"), "schedule inventory binding")
    if (schedule_binding.get("file_sha256") !=
            hashlib.sha256(inventory_raw).hexdigest() or
            schedule_binding.get("analysis_sha256") !=
            inventory.get("analysis_sha256")):
        raise HQT3FramePageSolverError("schedule is stale against inventory")
    partition_binding = _dict(
        partition.get("input_binding"), "partition input binding")
    if (partition_binding.get("inventory_file_sha256") !=
            hashlib.sha256(inventory_raw).hexdigest() or
            partition_binding.get("schedule_file_sha256") !=
            hashlib.sha256(schedule_raw).hexdigest()):
        raise HQT3FramePageSolverError("partition is stale against its inputs")

    source_binding = _dict(inventory.get("source_binding"), "source binding")
    rom_path = root / str(source_binding.get("rom_path", ""))
    try:
        rom = rom_path.read_bytes()
    except OSError as exc:
        raise HQT3FramePageSolverError(f"cannot read active ROM: {exc}") from exc
    if hashlib.sha256(rom).hexdigest() != source_binding.get("rom_sha256"):
        raise HQT3FramePageSolverError("active World ROM differs from inventory")
    source_evidence = _source_evidence(root, inventory, call_graph, rom)

    catalog = _dict(inventory.get("global_catalog"), "global catalogue")
    templates_raw = _list(catalog.get("templates"), "global templates")
    templates = tuple(_dict(row, "global template") for row in templates_raw)
    load_plan = _dict(inventory.get("load_plan"), "load plan")
    scopes_raw = _list(load_plan.get("scopes"), "load scopes")
    scopes = tuple(_dict(row, "load scope") for row in scopes_raw)
    scope_by_id = {str(row.get("scope_id")): row for row in scopes}
    events = [_dict(row, "load event") for row in
              _list(load_plan.get("events"), "load events")]
    event = next((row for row in events
                  if row.get("event_id") == EXACT_NONFIT_EVENT_ID), None)
    if event is None or event.get("correlation_exact") is not True:
        raise HQT3FramePageSolverError("exact BCAB event disappeared")

    problems = [_dict(row, "partition problem scope") for row in
                _list(partition.get("problem_scopes"), "problem scopes")]
    problem_by_id = {str(row.get("scope_id")): row for row in problems}
    if set(problem_by_id) != set(PROBLEM_SCOPE_IDS):
        raise HQT3FramePageSolverError("partition problem scope set changed")
    class_limits = _class_record_limits(bound)
    scope_summaries: list[dict[str, object]] = []
    all_problem_atoms: list[dict[str, object]] = []
    for scope_id in PROBLEM_SCOPE_IDS:
        pages = [_dict(row, f"{scope_id} page") for row in
                 _list(problem_by_id[scope_id].get("descriptor_pages"),
                       f"{scope_id} pages")]
        atoms = [_compact_atom(page) for page in pages]
        all_problem_atoms.extend(atoms)
        class_name = scope_id.rsplit(":", 1)[-1]
        summary = _atom_summary(
            scope_id, atoms, class_limits[class_name])
        original = _dict(problem_by_id[scope_id].get("original"),
                         f"{scope_id} original")
        summary.update({
            "original_scope_ram_g_bytes": original.get("ram_g_bytes"),
            "original_scope_ram_g_fit": original.get("ram_g_strict_fit"),
            "original_scope_hqt3_state_count": original.get("hqt3_state_count"),
            "original_scope_hqt3_state_fit": original.get("hqt3_state_fit"),
            "ram_g_oversized_scope": scope_id in RAMG_OVERSIZED_SCOPE_IDS,
            "hqt_state_overflow_scope": scope_id in HQT_STATE_OVERFLOW_SCOPE_IDS,
        })
        scope_summaries.append(summary)

    event_indices = sorted({
        int(index)
        for scope_id in _list(event.get("class_scope_ids"), "BCAB class scopes")
        for index in _list(scope_by_id[str(scope_id)].get("template_indices"),
                           f"{scope_id} template indices")
    })
    event_requirement = next((
        _dict(row, "event requirement")
        for row in _list(partition.get("event_union_requirements"),
                         "event union requirements")
        if isinstance(row, dict) and
        row.get("requirement_id") == EXACT_NONFIT_REQUIREMENT_ID
    ), None)
    if event_requirement is None:
        raise HQT3FramePageSolverError("BCAB physical requirement disappeared")
    requirement_cost = _dict(event_requirement.get("union_cost"),
                             "BCAB union cost")
    requirement_pixel = _dict(requirement_cost.get("pixel"), "BCAB pixels")
    requirement_capacity = _dict(requirement_cost.get("capacity"),
                                  "BCAB capacity")
    cell_bytes = source_binding.get("sprite_cell_argb4444_bytes")
    width = source_binding.get("sprite_cell_width")
    height = source_binding.get("sprite_cell_height")
    if (not all(isinstance(item, int) and item > 0
                for item in (cell_bytes, width, height)) or
            cell_bytes != width * height * 2):
        raise HQT3FramePageSolverError("sprite cell geometry changed")
    pseudo, event_cells = _pseudo_scope(
        "event-union:" + EXACT_NONFIT_EVENT_ID,
        event_indices, templates, int(cell_bytes),
        pixel_pack_id=str(event.get("pack_id")))
    event_pack = _compile_pixel_pack(root, event_cells, int(width), int(height))
    if event_pack is None:
        raise HQT3FramePageSolverError("BCAB event pack is unexpectedly empty")
    if (len(event_pack.data) != requirement_pixel.get("ft812_payload_bytes") or
            event_pack.sha256 != requirement_pixel.get(
                "relocatable_payload_sha256")):
        raise HQT3FramePageSolverError("BCAB lossless pack differs from partition")
    event_pages, event_page_summary = _descriptor_page_rows(
        pseudo, templates, event_pack, int(cell_bytes))
    event_atoms = [_compact_atom(page) for page in event_pages]
    event_summary = _atom_summary(EXACT_NONFIT_EVENT_ID, event_atoms, 2)

    first_descriptor = int(_dict(
        source_evidence.get("bcab_rom_witness"), "BCAB witness")
        ["first_child_descriptor"])
    first_atoms = [row for row in event_atoms
                   if row["descriptor_address"] == first_descriptor and
                   row["bank_kind"] == "palette-fallback" and
                   0x40 in _list(row.get("resource_types"), "resource types")]
    if len(first_atoms) != 16 or {row["bank_value"] for row in first_atoms} != set(
            range(16)):
        raise HQT3FramePageSolverError("BCAB first-child palette page set changed")
    cold_min = min(int(row["ram_g_bytes"]) for row in first_atoms)
    cold_max = max(int(row["ram_g_bytes"]) for row in first_atoms)

    # A semantic (bank, descriptor) may have a different lossless physical
    # encoding in a different compiled parent-pack epoch (palette/payload
    # deduplication is pack-local).  Keep that epoch in the physical identity;
    # silently equating the two encodings would forge a relocation proof.
    all_atoms_by_id: dict[str, dict[str, object]] = {}
    for atom in [*all_problem_atoms, *event_atoms]:
        identity = (
            f"{atom['bank_key']}:{atom['descriptor_address']}:"
            f"{atom['pixel_sha256']}")
        previous = all_atoms_by_id.setdefault(identity, atom)
        if previous["ram_g_bytes"] != atom["ram_g_bytes"]:
            raise HQT3FramePageSolverError("physical page identity collision")
    capability_floor = max(
        int(row["ram_g_bytes"]) for row in all_atoms_by_id.values())

    exact_rows = [_dict(row, "exact event obligation") for row in
                  _list(partition.get("exact_event_partition_obligations"),
                        "exact event obligations")]
    bcab_obligation = next((row for row in exact_rows
                            if row.get("event_id") == EXACT_NONFIT_EVENT_ID), None)
    if (bcab_obligation is None or
            bcab_obligation.get("single_union_partition_meets_targets") is not False or
            bcab_obligation.get("eviction_permitted") is not False):
        raise HQT3FramePageSolverError("BCAB non-fit/eviction boundary changed")

    frame_envelope = _dict(envelope.get("record_envelope"), "record envelope")
    active_callable_exact = source_evidence[
        "active_call_graph_exactly_reaches_complete_child_chain"] is True
    blockers = [
        {
            "code": "PZPAGE501",
            "scope": "exact-concrete-frame-page-set",
            "reason": (
                "228 bounds record count, but object state/palette epoch to "
                "exact descriptor-page identity is not yet solved for every "
                "reachable post-update/pre-draw snapshot"),
        },
        {
            "code": "PZPAGE502",
            "scope": "object-and-page-lifetimes",
            "reason": (
                "first draw, last draw and simultaneous linked-child/page "
                "overlap are absent; retained survivors forbid event eviction"),
        },
        {
            "code": "PZPAGE503",
            "scope": "ft812-display-list-retirement-fence",
            "reason": (
                "the last displayed list referencing each page has no target "
                "retirement acknowledgement, so overwrite is not permitted"),
        },
        {
            "code": "PZPAGE504",
            "scope": "double-buffer-union-capacity",
            "reason": (
                "the byte-exact union of current and next frame page sets is "
                "unknown and therefore cannot be proved strictly below 1 MiB"),
        },
        {
            "code": "PZPAGE505",
            "scope": "upload-bandwidth-and-deadline",
            "reason": (
                "no measured TS DMA -> FT812 bytes/second, setup latency or "
                "per-VBlank upload window is bound to the generated runtime"),
        },
        {
            "code": "PZPAGE506",
            "scope": "runtime-page-cache-and-relocation",
            "reason": (
                "page allocator, multi-HQT resolver, bitmap/palette relocation "
                "and atomic epoch publication are not target-bound"),
        },
        {
            "code": "PZPAGE508",
            "scope": "whole-tsconf-allocation",
            "reason": (
                "isolated compiled page/event staging fits 4 MiB, but code, "
                "audio, object state and simultaneous stage storage are not "
                "allocated together"),
        },
    ]
    if not active_callable_exact:
        blockers.append({
            "code": "PZPAGE507",
            "scope": "active-call-graph-dynamic-chain",
            "reason": (
                "the active graph inventories the relevant functions but does "
                "not prove every dynamic parent.update -> child.__init__ edge"),
        })
    blockers.sort(key=lambda row: str(row["code"]))

    report: dict[str, object] = {
        "format": HQT3_FRAME_PAGE_SOLVER_FORMAT,
        "status": HQT3_FRAME_PAGE_SOLVER_STATUS,
        "live": False,
        "physical_feasibility_decision": "UNDECIDED_LIFETIME_AND_BANDWIDTH_BLOCKED",
        "input_binding": {
            "inventory": _binding(root, paths["inventory"], inventory_raw,
                                  inventory, "analysis_sha256"),
            "schedule": _binding(root, paths["schedule"], schedule_raw,
                                 schedule, "analysis_sha256"),
            "partition": _binding(root, paths["partition"], partition_raw,
                                  partition, "analysis_sha256"),
            "frame_record_bound": _binding(
                root, paths["frame_bound"], bound_raw, bound, "status"),
            "frame_sprite_fragment_envelope": _binding(
                root, paths["frame_envelope"], envelope_raw, envelope,
                "semantic_sha256"),
            "active_call_graph": _binding(
                root, paths["call_graph"], call_graph_raw, call_graph,
                "semantic_sha256"),
            "active_rom": {
                "path": rom_path.relative_to(root).as_posix(),
                "sha256": hashlib.sha256(rom).hexdigest(),
            },
            "page_compiler_modules": {
                "hqt3_partition_solver.py": _file_sha256(
                    Path(__file__).with_name("hqt3_partition_solver.py")),
                "hqt3_ramg_schedule.py": _file_sha256(
                    Path(__file__).with_name("hqt3_ramg_schedule.py")),
            },
        },
        "hardware_contract": {
            "frame_rate_hz": FRAME_RATE_HZ,
            "frame_period_microseconds": FRAME_PERIOD_MICROSECONDS,
            "ft812_ram_g_capacity_bytes": FT812_RAM_G_BYTES,
            "ft812_ram_g_strict_max_payload_bytes": FT812_RAM_G_BYTES - 1,
            "tsconf_ram_capacity_bytes": TSCONF_RAM_BYTES,
            "display_list_generations_retained_for_safe_publication": (
                DISPLAY_LIST_GENERATIONS),
            "displayed_page_overwrite_before_retirement_permitted": False,
        },
        "source_evidence": source_evidence,
        "frame_record_contract": {
            "certified_frame_max_records": FRAME_RECORD_LIMIT,
            "object_records": frame_envelope.get("object_records"),
            "transient_records": frame_envelope.get("transient_records"),
            "record_bound_proof_complete": bound.get("proof_complete"),
            "record_bound_kind": bound.get("bound_kind"),
            "one_record_selects_at_most_one_descriptor_page": True,
            "maximum_distinct_page_references_per_frame": FRAME_RECORD_LIMIT,
            "exact_page_identity_sequence_proved": False,
        },
        "problem_scope_page_catalogs": scope_summaries,
        "exact_bcab_page_catalog": {
            **event_summary,
            "requirement_id": EXACT_NONFIT_REQUIREMENT_ID,
            "class_scope_ids": list(event.get("class_scope_ids", [])),
            "template_count": len(event_indices),
            "template_indices_sha256": _value_sha256(event_indices),
            "union_ram_g_bytes": requirement_pixel.get("ft812_payload_bytes"),
            "union_hqt3_bytes": _dict(
                requirement_cost.get("hqt3"), "BCAB HQT3").get("total_bytes"),
            "union_compiled_ts_staging_bytes": requirement_capacity.get(
                "ts_staging_compiled_payload_plus_hqt3_bytes"),
            "union_ram_g_overflow_bytes": int(
                requirement_pixel["ft812_payload_bytes"]) - FT812_RAM_G_BYTES,
            "single_union_strict_ram_g_fit": False,
            "page_atoms": event_atoms,
        },
        "strict_lower_bounds": {
            "catalog_cache_capability_floor_bytes": capability_floor,
            "catalog_cache_capability_floor_meaning": (
                "a cache which supports every measured semantic atom must fit "
                "at least its largest single immutable atom; this is not a "
                "simultaneous-residency claim"),
            "bcab_first_child": {
                "conditional_on_event_and_successful_object_allocation": True,
                "descriptor_address": first_descriptor,
                "resource_type": 0x40,
                "palette_slot_candidates": list(range(16)),
                "candidate_page_ids": sorted(
                    str(row["page_id"]) for row in first_atoms),
                "cold_miss_upload_min_bytes": cold_min,
                "cold_miss_upload_max_bytes": cold_max,
                "cold_miss_minimum_average_bytes_per_second_at_55hz": (
                    cold_min * FRAME_RATE_HZ),
                "cold_miss_maximum_average_bytes_per_second_at_55hz": (
                    cold_max * FRAME_RATE_HZ),
                "preloaded_page_upload_bytes_in_draw_frame": 0,
            },
        },
        "double_buffer_capacity": {
            "required_resident_relation": "pages(frame_n) UNION pages(frame_n+1)",
            "retirement_fence_required_before_overwrite": True,
            "event_order_used_as_eviction_proof": False,
            "exact_current_frame_bytes": None,
            "exact_next_frame_bytes": None,
            "exact_two_generation_union_bytes": None,
            "strict_fit_proved": False,
            "conservative_scope_upper_estimates_use_sum_of_largest_atoms": True,
            "conservative_upper_estimates_are_not_residency_plans": True,
        },
        "upload_bandwidth": {
            "frame_rate_hz": FRAME_RATE_HZ,
            "deadline_microseconds_if_uploaded_in_one_game_frame": (
                FRAME_PERIOD_MICROSECONDS),
            "transport_measured_bytes_per_second": None,
            "transport_setup_latency_microseconds": None,
            "transport_available_window_microseconds": None,
            "cold_miss_floor_from_bcab_bytes": cold_min,
            "cold_miss_floor_required_average_bytes_per_second": (
                cold_min * FRAME_RATE_HZ),
            "largest_measured_atom_bytes": capability_floor,
            "largest_atom_one_per_frame_required_average_bytes_per_second": (
                capability_floor * FRAME_RATE_HZ),
            "deadline_proved": False,
        },
        "hqt_width_contract": {
            "global_template_count": catalog.get("template_count"),
            "global_template_id_uint16_fit": (
                isinstance(catalog.get("template_count"), int) and
                int(catalog["template_count"]) <= 0xFFFF),
            "page_atom_record_count_max": max(
                int(row["hqt3_records"]) for row in all_atoms_by_id.values()),
            "page_atom_cell_count_max": max(
                int(row["hqt3_cells"]) for row in all_atoms_by_id.values()),
            "page_atom_state_count_max": max(
                int(row["hqt3_states"]) for row in all_atoms_by_id.values()),
            "all_page_atom_indices_fit": all(
                row["hqt3_indices_fit"] is True
                for row in all_atoms_by_id.values()),
            "frame_record_count_uint8_fit": FRAME_RECORD_LIMIT <= 0xFF,
        },
        "tsconf_staging": {
            "bcab_compiled_bundle_bytes": requirement_capacity.get(
                "ts_staging_compiled_payload_plus_hqt3_bytes"),
            "bcab_compiled_bundle_isolated_fit": (
                int(requirement_capacity[
                    "ts_staging_compiled_payload_plus_hqt3_bytes"])
                <= TSCONF_RAM_BYTES),
            "all_schedule_scopes_compiled_isolated_fit": (
                _dict(schedule.get("scope_pack_census"), "scope census").get(
                    "ts_compiled_isolated_nonfit_count") == 0),
            "whole_machine_code_audio_state_and_staging_fit_proved": False,
        },
        "minimum_missing_facts": [
            {
                "fact_id": "PZPAGE-F01",
                "kind": "state",
                "required_fact": (
                    "for each of at most 228 draw records, the exact runtime "
                    "bank/palette epoch, descriptor and selected page ID"),
            },
            {
                "fact_id": "PZPAGE-F02",
                "kind": "lifetime",
                "required_fact": (
                    "first-draw and last-draw frame for every live object, "
                    "linked child and same-frame pending allocation"),
            },
            {
                "fact_id": "PZPAGE-F03",
                "kind": "lifetime",
                "required_fact": (
                    "byte-exact pages(frame_n) UNION pages(frame_n+1) after "
                    "deduplicating shared immutable cells"),
            },
            {
                "fact_id": "PZPAGE-F04",
                "kind": "hardware-fence",
                "required_fact": (
                    "target acknowledgement that the last displayed FT812 "
                    "list referencing a page has retired"),
            },
            {
                "fact_id": "PZPAGE-F05",
                "kind": "bandwidth",
                "required_fact": (
                    "measured worst-case TS DMA/SPI bytes per second, setup "
                    "latency and upload window at 55 Hz"),
            },
            {
                "fact_id": "PZPAGE-F06",
                "kind": "allocation",
                "required_fact": (
                    "whole 4 MiB TS allocation including code, audio, object "
                    "state, HQT tables, source packs and page-cache metadata"),
            },
        ],
        "resident_combinations": [],
        "eviction_inferences": [],
        "blockers": blockers,
        "proof_boundaries": {
            "active_python_rom_and_call_graph_bound": True,
            "three_ram_g_oversized_scopes_identified": True,
            "exact_bcab_nonfit_union_reproduced_losslessly": True,
            "descriptor_bank_pages_are_semantic_not_size_cuts": True,
            "all_measured_page_atoms_individually_fit_ram_g": True,
            "hqt_page_index_widths_fit": True,
            "frame_record_upper_bound_228_bound": True,
            "conditional_bcab_first-child_cold-miss_floor_proved": True,
            "exact_per_frame_page_sets_proved": False,
            "two_generation_ram_g_fit_proved": False,
            "upload_deadline_proved": False,
            "pixel_eviction_permitted": False,
            "active_call_graph_complete_child_chain_proved": active_callable_exact,
            "whole_tsconf_allocation_proved": False,
        },
    }
    semantic = dict(report)
    report["analysis_sha256"] = _sha256_value(semantic)
    return report


__all__ = [
    "DISPLAY_LIST_GENERATIONS",
    "EXACT_NONFIT_EVENT_ID",
    "EXACT_NONFIT_REQUIREMENT_ID",
    "FRAME_RATE_HZ",
    "FRAME_RECORD_LIMIT",
    "HQT3_FRAME_PAGE_SOLVER_FORMAT",
    "HQT3_FRAME_PAGE_SOLVER_STATUS",
    "HQT3FramePageSolverError",
    "RAMG_OVERSIZED_SCOPE_IDS",
    "analyze_hqt3_frame_page_solver",
]
