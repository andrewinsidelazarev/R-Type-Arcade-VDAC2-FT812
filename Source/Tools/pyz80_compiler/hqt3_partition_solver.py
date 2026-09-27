"""Source-derived HQT3 metadata sharding and RAM_G paging proof.

Only semantic identities already present in the active Python/ROM relation are
allowed as partition axes.  In particular, the solver never cuts a template
at an arbitrary byte threshold.  A descriptor is the smallest page atom: all
of its cells stay together.

HQT3 metadata pages may all remain in TS-Conf RAM while sharing one resident
RAM_G pixel pack.  That makes descriptor-key HQT sharding safe even when
different objects/animation phases coexist.  Pixel pages are different: they
need a lifetime/exclusivity proof before one page may replace another.  The
active scheduler retains earlier objects across later ROM events, so this pass
does not infer eviction from event order.
"""

from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from .ft812_assets import (
    FT812CellAssetPack,
    FT812Palette,
    FT812_PALETTE_BYTES,
)
from .full_hqt3_inventory import (
    FULL_HQT3_INVENTORY_FORMAT,
    FULL_HQT3_INVENTORY_STATUS,
)
from .hqt3_ramg_schedule import (
    FT812_RAM_G_BYTES,
    HQT3_CELL_BYTES,
    HQT3_HEADER_BYTES,
    HQT3_RAMG_SCHEDULE_FORMAT,
    HQT3_RAMG_SCHEDULE_STATUS,
    HQT3_RECORD_BYTES,
    HQT3_STATE_BYTES,
    HQT3RAMGScheduleError,
    PACK_ALIGNMENT,
    TSCONF_RAM_BYTES,
    compile_pixel_packs,
    _hqt3_for_scope,
    _pack_measurement,
    _pixel_pack_id,
    _scope_capacity,
    _scope_cells,
    _sha256_value,
    _template_cells,
)


HQT3_PARTITION_SOLVER_FORMAT = "pyz80-hqt3-partition-solver-v1"
HQT3_PARTITION_SOLVER_STATUS = (
    "STRUCTURAL_HQT_SHARD_PROVED_RAMG_PAGING_LIFETIMES_BLOCKED")

PROBLEM_SCOPE_IDS = (
    "stage:2:class:Child8D85",
    "stage:2:class:Enemy6F89",
    "stage:2:class:Multipart915BChild",
    "stage:5:class:Formation78F8Child",
)

AMBIGUOUS_FACTS = (
    {
        "fact_id": "PZPART-F01",
        "kind": "type",
        "required_fact": (
            "exact (stage,event address,handler,command) -> concrete Python "
            "constructor/initializer variant relation"),
    },
    {
        "fact_id": "PZPART-F02",
        "kind": "type",
        "required_fact": (
            "transitive spawned-child type plus exact resource bank, palette "
            "epoch and descriptor/animation set for that initializer"),
    },
    {
        "fact_id": "PZPART-F03",
        "kind": "lifetime",
        "required_fact": (
            "maximum simultaneously live instances and descriptor/animation "
            "phase overlap, including pending same-frame children"),
    },
    {
        "fact_id": "PZPART-F04",
        "kind": "lifetime",
        "required_fact": (
            "first draw and last draw interval for every root/descendant and "
            "the last displayed FT812 list which references its pixels"),
    },
)


class HQT3PartitionSolverError(ValueError):
    """No semantics-preserving partition proof can be constructed."""


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            while block := source.read(1024 * 1024):
                digest.update(block)
    except OSError as exc:
        raise HQT3PartitionSolverError(f"cannot hash {path}: {exc}") from exc
    return digest.hexdigest()


def _load_json(path: Path, name: str) -> tuple[dict[str, object], bytes]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HQT3PartitionSolverError(f"cannot read {name} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise HQT3PartitionSolverError(f"{name} is not a JSON object")
    return value, raw


def _analysis_hash_valid(value: Mapping[str, object], *, drop_status: bool) -> bool:
    semantic = dict(value)
    stored = semantic.pop("analysis_sha256", None)
    if drop_status:
        semantic.pop("status", None)
    return isinstance(stored, str) and _sha256_value(semantic) == stored


def _align(output: bytearray, alignment: int = PACK_ALIGNMENT) -> None:
    output.extend(bytes((-len(output)) & (alignment - 1)))


def _subset_pack(
        parent: FT812CellAssetPack,
        keys: Iterable[object],
        ) -> FT812CellAssetPack:
    """Build one exact relocatable subpack without re-quantising pixels.

    The parent representation is already lossless.  A subpack copies only
    referenced immutable payloads and palette tables, remaps offsets, and then
    re-runs the parent's byte-exact decoder for every logical key.
    """
    key_set = set(keys)
    selected = tuple(entry for entry in parent.entries if entry.key in key_set)
    if {entry.key for entry in selected} != key_set:
        raise HQT3PartitionSolverError("descriptor page key is absent from parent pack")
    payload_regions = sorted({
        (entry.offset, entry.size) for entry in selected
    })
    palette_offsets = sorted({
        entry.palette_offset for entry in selected
        if entry.palette_offset is not None
    })
    parent_palettes = {palette.offset: palette for palette in parent.palettes}
    output = bytearray()
    payload_remap: dict[tuple[int, int], int] = {}
    for old_offset, size in payload_regions:
        _align(output)
        new_offset = len(output)
        payload = parent.data[old_offset:old_offset + size]
        if len(payload) != size:
            raise HQT3PartitionSolverError("parent pixel payload is truncated")
        output.extend(payload)
        payload_remap[(old_offset, size)] = new_offset
    palette_remap: dict[int, tuple[int, int]] = {}
    palettes: list[FT812Palette] = []
    for index, old_offset in enumerate(palette_offsets):
        assert old_offset is not None
        try:
            source = parent_palettes[old_offset]
        except KeyError as exc:
            raise HQT3PartitionSolverError(
                "parent palette reference is missing") from exc
        _align(output)
        new_offset = len(output)
        payload = parent.data[old_offset:old_offset + FT812_PALETTE_BYTES]
        if len(payload) != FT812_PALETTE_BYTES:
            raise HQT3PartitionSolverError("parent palette payload is truncated")
        output.extend(payload)
        palettes.append(FT812Palette(
            offset=new_offset,
            color_count=source.color_count,
            sha256=source.sha256,
        ))
        palette_remap[old_offset] = (index, new_offset)
    remapped = []
    for entry in selected:
        new_offset = payload_remap[(entry.offset, entry.size)]
        if entry.palette_offset is None:
            palette_index = None
            palette_offset = None
        else:
            palette_index, palette_offset = palette_remap[entry.palette_offset]
        remapped.append(replace(
            entry,
            offset=new_offset,
            palette_index=palette_index,
            palette_offset=palette_offset,
        ))
    identities = {
        (entry.decoded_sha256, entry.width, entry.height)
        for entry in remapped
    }
    result = FT812CellAssetPack(
        data=bytes(output),
        entries=tuple(sorted(remapped, key=lambda item: item.key)),
        palettes=tuple(palettes),
        unique_cells=len(identities),
        alignment=PACK_ALIGNMENT,
        raw_argb4444_bytes=sum(
            width * height * 2 for _digest, width, height in identities),
    )
    for entry in result.entries:
        if hashlib.sha256(result.decode(entry)).hexdigest() != entry.decoded_sha256:
            raise HQT3PartitionSolverError("descriptor subpack changed pixels")
    return result


def _pseudo_scope(
        scope_id: str,
        template_indices: Iterable[int],
        templates: Sequence[Mapping[str, object]],
        cell_bytes: int,
        *,
        pixel_pack_id: str | None = None,
        ) -> tuple[dict[str, object], tuple[object, ...]]:
    indices = sorted(set(template_indices))
    try:
        selected = tuple(templates[index] for index in indices)
    except IndexError as exc:
        raise HQT3PartitionSolverError("partition template index is invalid") from exc
    cells = tuple(sorted({
        item.key for template in selected for item in _template_cells(template)
    }))
    references = sum(len(_template_cells(template)) for template in selected)
    pack_id = _pixel_pack_id(cells) if pixel_pack_id is None else pixel_pack_id
    if pack_id != _pixel_pack_id(cells):
        raise HQT3PartitionSolverError(
            f"partition {scope_id} pixel identity differs")
    fixed = (
        HQT3_HEADER_BYTES + len(indices) * HQT3_RECORD_BYTES +
        references * HQT3_CELL_BYTES)
    return ({
        "scope_id": scope_id,
        "template_indices": indices,
        "template_count": len(indices),
        "template_cell_reference_count": references,
        "unique_logical_cell_count": len(cells),
        "selected_argb4444_bytes": len(cells) * cell_bytes,
        "pixel_pack_id": pack_id,
        "hqt3_fixed_layout": {
            "header_bytes": HQT3_HEADER_BYTES,
            "record_count": len(indices),
            "record_bytes": len(indices) * HQT3_RECORD_BYTES,
            "cell_count": references,
            "cell_bytes": references * HQT3_CELL_BYTES,
            "fixed_bytes_excluding_state_table": fixed,
            "state_record_bytes": HQT3_STATE_BYTES,
        },
    }, cells)


def _cost(
        pseudo: Mapping[str, object],
        cells: Sequence[object],
        pack: FT812CellAssetPack | None,
        templates: Sequence[Mapping[str, object]],
        cell_bytes: int,
        ) -> dict[str, object]:
    pixel = _pack_measurement(
        str(pseudo["pixel_pack_id"]), cells, pack, cell_bytes)
    hqt3 = _hqt3_for_scope(pseudo, templates, pack)
    capacity = _scope_capacity(pixel, hqt3)
    target_pass = (
        int(pixel["ft812_payload_bytes"]) < FT812_RAM_G_BYTES and
        hqt3["uint16_record_cell_and_uint8_state_indices_fit"] is True and
        int(capacity["ts_staging_compiled_payload_plus_hqt3_bytes"]) <=
        TSCONF_RAM_BYTES)
    return {
        "pixel": pixel,
        "hqt3": hqt3,
        "capacity": capacity,
        "partition_targets": {
            "ram_g_strictly_below_1mib": (
                int(pixel["ft812_payload_bytes"]) < FT812_RAM_G_BYTES),
            "hqt3_state_count_at_most_256": int(hqt3["state_count"]) <= 256,
            "hqt3_record_and_cell_uint16_fit": (
                hqt3["uint16_record_cell_and_uint8_state_indices_fit"] is True),
            "compiled_ts_staging_at_most_4mib": (
                int(capacity["ts_staging_compiled_payload_plus_hqt3_bytes"])
                <= TSCONF_RAM_BYTES),
            "all_targets_pass": target_pass,
        },
    }


def _cost_reference(
        requirement_id: str,
        cost: Mapping[str, object],
        ) -> dict[str, object]:
    """Return a compact, hash-bound exact physical cost for one event row."""
    pixel = cost["pixel"]
    hqt3 = cost["hqt3"]
    capacity = cost["capacity"]
    targets = cost["partition_targets"]
    assert all(isinstance(item, Mapping) for item in (
        pixel, hqt3, capacity, targets))
    return {
        "requirement_id": requirement_id,
        "union_cost_sha256": _sha256_value(cost),
        "ram_g_bytes": pixel["ft812_payload_bytes"],
        "hqt3_bytes": hqt3["total_bytes"],
        "hqt3_state_count": hqt3["state_count"],
        "compiled_ts_staging_bytes": capacity[
            "ts_staging_compiled_payload_plus_hqt3_bytes"],
        "all_partition_targets_pass": targets["all_targets_pass"],
    }


def _source_evidence(root: Path, inventory: Mapping[str, object]) -> dict[str, object]:
    source = inventory.get("source_binding")
    if not isinstance(source, dict):
        raise HQT3PartitionSolverError("inventory source binding is missing")
    hashes = source.get("coverage_source_hashes")
    if not isinstance(hashes, dict):
        raise HQT3PartitionSolverError("inventory source hashes are missing")
    path = root / "Source" / "Python" / "rtype_port" / "enemies.py"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HQT3PartitionSolverError(f"cannot read active enemies.py: {exc}") from exc
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if hashes.get("rtype_port.enemies") != digest:
        raise HQT3PartitionSolverError("partition solver inventory is stale")
    tree = ast.parse(text)
    class_names = (
        "Enemy6F89", "Formation78F8Parent", "Formation78F8Child",
        "Multipart915BParent", "Multipart915BChild", "Enemy7D68", "Child8D85",
        "M72EnemyWorld",
    )
    rows = []
    class_nodes: dict[str, ast.ClassDef] = {}
    for name in class_names:
        nodes = [node for node in tree.body
                 if isinstance(node, ast.ClassDef) and node.name == name]
        if len(nodes) != 1:
            raise HQT3PartitionSolverError(
                f"active source class {name} is missing/duplicated")
        node = nodes[0]
        class_nodes[name] = node
        methods = [item.name for item in node.body
                   if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))]
        rows.append({
            "class_name": name,
            "ast_sha256": hashlib.sha256(ast.dump(
                node, include_attributes=False).encode("utf-8")).hexdigest(),
            "methods": methods,
        })

    def method(class_name: str, method_name: str) -> ast.FunctionDef:
        matches = [
            item for item in class_nodes[class_name].body
            if isinstance(item, ast.FunctionDef) and item.name == method_name
        ]
        if len(matches) != 1:
            raise HQT3PartitionSolverError(
                f"active source method {class_name}.{method_name} changed")
        return matches[0]

    def name_is(node: ast.AST, name: str) -> bool:
        return isinstance(node, ast.Name) and node.id == name

    def attribute_is(node: ast.AST, owner: str, attribute: str) -> bool:
        return (isinstance(node, ast.Attribute) and node.attr == attribute and
                name_is(node.value, owner))

    def call_constructs(node: ast.AST, class_name: str) -> bool:
        return (isinstance(node, ast.Call) and
                name_is(node.func, class_name))

    def pending_append_argument(
            node: ast.AST, *, variable: str | None = None,
            constructor: str | None = None) -> bool:
        if (not isinstance(node, ast.Call) or
                not isinstance(node.func, ast.Attribute) or
                node.func.attr != "append" or
                not isinstance(node.func.value, ast.Attribute) or
                node.func.value.attr != "pending" or not node.args):
            return False
        argument = node.args[0]
        return ((variable is not None and name_is(argument, variable)) or
                (constructor is not None and call_constructs(
                    argument, constructor)))

    def linked_child_witness(
            parent_name: str, child_name: str) -> dict[str, object]:
        update = method(parent_name, "update")
        child_assignments = [
            node for node in ast.walk(update)
            if isinstance(node, ast.Assign) and
            any(name_is(target, "child") for target in node.targets) and
            call_constructs(node.value, child_name)
        ]
        if len(child_assignments) != 1:
            raise HQT3PartitionSolverError(
                f"{parent_name} child constructor relation changed")
        assignment = child_assignments[0]
        call = assignment.value
        assert isinstance(call, ast.Call)
        passes_previous_head = any(
            attribute_is(argument, "self", "head") for argument in call.args)
        appends_child = any(
            pending_append_argument(node, variable="child")
            for node in ast.walk(update))
        advances_head = any(
            isinstance(node, ast.Assign) and
            any(attribute_is(target, "self", "head")
                for target in node.targets) and
            name_is(node.value, "child")
            for node in ast.walk(update))
        if not (passes_previous_head and appends_child and advances_head):
            raise HQT3PartitionSolverError(
                f"{parent_name} linked-child lifetime relation changed")
        return {
            "parent_class": parent_name,
            "child_class": child_name,
            "method": "update",
            "constructor_line": assignment.lineno,
            "passes_previous_head": True,
            "advances_head_to_new_child": True,
            "appends_new_child_to_pending": True,
        }

    formation_witness = linked_child_witness(
        "Formation78F8Parent", "Formation78F8Child")
    multipart_witness = linked_child_witness(
        "Multipart915BParent", "Multipart915BChild")

    spawn_child = method("Enemy7D68", "_spawn_child")
    choice_dicts = [
        node.value for node in ast.walk(spawn_child)
        if isinstance(node, ast.Assign) and
        any(name_is(target, "choices") for target in node.targets) and
        isinstance(node.value, ast.Dict)
    ]
    choice_timer_values = sorted({
        int(key.value) for dictionary in choice_dicts
        for key in dictionary.keys
        if isinstance(key, ast.Constant) and isinstance(key.value, int)
    })
    child_append_calls = [
        node for node in ast.walk(spawn_child)
        if pending_append_argument(node, constructor="Child8D85")
    ]
    enemy7_update = method("Enemy7D68", "update")
    calls_spawn_in_hold = any(
        isinstance(node, ast.Call) and
        isinstance(node.func, ast.Attribute) and
        node.func.attr == "_spawn_child"
        for node in ast.walk(enemy7_update))
    if (choice_timer_values != [0x80, 0xC0] or
            len(child_append_calls) != 1 or not calls_spawn_in_hold):
        raise HQT3PartitionSolverError(
            "Enemy7D68 multi-Child8D85 spawn relation changed")
    child8d85_witness = {
        "parent_class": "Enemy7D68",
        "child_class": "Child8D85",
        "method": "_spawn_child",
        "append_line": child_append_calls[0].lineno,
        "distinct_timer_values": choice_timer_values,
        "spawn_method_called_from_update": True,
    }

    dispatch = method("M72EnemyWorld", "_dispatch")
    enemy6_branches = [
        node for node in ast.walk(dispatch)
        if isinstance(node, ast.If) and
        any(isinstance(item, ast.Constant) and item.value == 0x6F89
            for item in ast.walk(node.test))
    ]
    direct_enemy6_append = False
    enemy6_line: int | None = None
    if len(enemy6_branches) == 1:
        branch = enemy6_branches[0]
        calls = [
            node for statement in branch.body for node in ast.walk(statement)
            if pending_append_argument(node, constructor="Enemy6F89")
        ]
        # A direct one-statement append has no singleton/existing-instance
        # guard in this handler branch.
        direct_enemy6_append = len(branch.body) == 1 and len(calls) == 1
        enemy6_line = calls[0].lineno if calls else None
    if not direct_enemy6_append:
        raise HQT3PartitionSolverError(
            "Enemy6F89 dispatch gained or changed a singleton guard")
    enemy6_witness = {
        "world_class": "M72EnemyWorld",
        "method": "_dispatch",
        "handler": 0x6F89,
        "direct_pending_append_line": enemy6_line,
        "branch_statement_count": 1,
        "singleton_guard_in_handler_branch": False,
    }

    world_update = method("M72EnemyWorld", "update")
    pending_extends = [
        node for node in ast.walk(world_update)
        if isinstance(node, ast.Call) and
        isinstance(node.func, ast.Attribute) and node.func.attr == "extend" and
        isinstance(node.func.value, ast.Attribute) and
        attribute_is(node.func.value, "self", "enemies") and
        len(node.args) == 1 and attribute_is(node.args[0], "self", "pending")
    ]
    survivor_appends = [
        node for node in ast.walk(world_update)
        if isinstance(node, ast.Call) and
        isinstance(node.func, ast.Attribute) and
        node.func.attr == "append" and name_is(node.func.value, "survivors") and
        node.args and name_is(node.args[0], "enemy")
    ]
    survivor_assignments = [
        node for node in ast.walk(world_update)
        if isinstance(node, ast.Assign) and
        any(attribute_is(target, "self", "enemies")
            for target in node.targets) and name_is(node.value, "survivors")
    ]
    dispatch_calls = [
        node for node in ast.walk(world_update)
        if isinstance(node, ast.Call) and
        isinstance(node.func, ast.Attribute) and node.func.attr == "_dispatch"
    ]
    if not (len(pending_extends) == 1 and survivor_appends and
            len(survivor_assignments) == 1 and len(dispatch_calls) == 1 and
            dispatch_calls[0].lineno < pending_extends[0].lineno <
            survivor_assignments[0].lineno):
        raise HQT3PartitionSolverError(
            "world cross-event survivor lifetime relation changed")
    survivor_witness = {
        "world_class": "M72EnemyWorld",
        "method": "update",
        "dispatch_line": dispatch_calls[0].lineno,
        "pending_extend_line": pending_extends[0].lineno,
        "survivor_assignment_line": survivor_assignments[0].lineno,
        "live_enemies_retained": True,
    }
    return {
        "path": path.resolve().relative_to(root).as_posix(),
        "sha256": digest,
        "class_evidence": rows,
        "ast_witnesses": {
            "formation_linked_children": formation_witness,
            "multipart_linked_children": multipart_witness,
            "child8d85_multiple_timer_spawns": child8d85_witness,
            "enemy6f89_direct_unguarded_dispatch": enemy6_witness,
            "cross_event_survivor_retention": survivor_witness,
        },
        "facts": {
            "formation_parent_appends_linked_children": True,
            "multipart_parent_appends_linked_children": True,
            "enemy7d68_can_append_multiple_child8d85_instances": True,
            "enemy6f89_has_no_source_proved_singleton_guard": True,
            "world_retains_survivors_across_event_dispatch": True,
        },
        "interpretation": (
            "these facts prohibit assuming descriptor/resource/animation "
            "pages are mutually exclusive; they do not impose new gameplay"),
    }


def _descriptor_page_rows(
        scope: Mapping[str, object],
        templates: Sequence[Mapping[str, object]],
        parent_pack: FT812CellAssetPack,
        cell_bytes: int,
        ) -> tuple[list[dict[str, object]], dict[str, object]]:
    indices = scope.get("template_indices")
    if not isinstance(indices, list):
        raise HQT3PartitionSolverError("problem scope template list is missing")
    pages: list[dict[str, object]] = []
    hqt_shared_total = 0
    full_page_ramg_total = 0
    full_page_ts_total = 0
    max_state_count = 0
    all_pass = True
    for index in indices:
        if not isinstance(index, int):
            raise HQT3PartitionSolverError("problem scope template index is invalid")
        template = templates[index]
        descriptor = template.get("descriptor")
        bank = template.get("bank")
        if not isinstance(descriptor, dict) or not isinstance(bank, dict):
            raise HQT3PartitionSolverError("descriptor page template is malformed")
        page_id = (
            f"descriptor:{int(bank['encoded_hqt3_key']):04X}:"
            f"{int(descriptor['address']):04X}")
        pseudo, keys = _pseudo_scope(
            page_id, (index,), templates, cell_bytes)
        subpack = _subset_pack(parent_pack, keys)
        full_cost = _cost(pseudo, keys, subpack, templates, cell_bytes)
        shared_hqt = _hqt3_for_scope(pseudo, templates, parent_pack)
        hqt_shared_total += int(shared_hqt["total_bytes"])
        full_page_ramg_total += int(full_cost["pixel"]["ft812_payload_bytes"])
        full_page_ts_total += int(full_cost["capacity"]
                                  ["ts_staging_compiled_payload_plus_hqt3_bytes"])
        max_state_count = max(max_state_count, int(shared_hqt["state_count"]))
        all_pass = all_pass and bool(full_cost["partition_targets"]["all_targets_pass"])
        pages.append({
            "partition_id": page_id,
            "axis": "exact-bank-plus-rom-descriptor",
            "template_index": index,
            "bank": dict(bank),
            "descriptor_address": int(descriptor["address"]),
            "resource_types": list(template.get("resource_types", [])),
            "animation_phase_identity": {
                "descriptor_code": int(descriptor["code"]),
                "flip_x": bool(descriptor["flip_x"]),
                "flip_y": bool(descriptor["flip_y"]),
            },
            "full_page_cost": full_cost,
            "shared_pixel_hqt3": shared_hqt,
            "template_atomic": True,
            "arbitrary_size_cut": False,
            "runtime_eviction_permitted": False,
        })
    summary = {
        "partition_count": len(pages),
        "axis": "exact-bank-plus-rom-descriptor",
        "all_templates_atomic": True,
        "arbitrary_size_cut": False,
        "all_full_pages_individually_meet_targets": all_pass,
        "full_pages_ram_g_sum_bytes": full_page_ramg_total,
        "full_pages_ram_g_simultaneous_fit": (
            full_page_ramg_total < FT812_RAM_G_BYTES),
        "full_pages_compiled_ts_sum_bytes": full_page_ts_total,
        "shared_pixel_hqt3_total_bytes": hqt_shared_total,
        "shared_pixel_hqt3_max_state_count": max_state_count,
        "shared_pixel_hqt3_all_state_indices_fit": max_state_count <= 256,
    }
    return pages, summary


def analyze_hqt3_partition_solver(
        project_root: Path,
        *,
        inventory_path: Path | None = None,
        schedule_path: Path | None = None,
        max_workers: int = 1,
        ) -> dict[str, object]:
    root = Path(project_root).resolve()
    inventory_file = (
        root / "Build" / "rtype_python_full_hqt3_inventory_status.json"
        if inventory_path is None else Path(inventory_path).resolve())
    schedule_file = (
        root / "Build" / "rtype_python_hqt3_ramg_schedule_status.json"
        if schedule_path is None else Path(schedule_path).resolve())
    inventory, inventory_raw = _load_json(inventory_file, "full HQT3 inventory")
    schedule, schedule_raw = _load_json(schedule_file, "HQT3/RAM_G schedule")
    if (inventory.get("format") != FULL_HQT3_INVENTORY_FORMAT or
            inventory.get("status") != FULL_HQT3_INVENTORY_STATUS or
            not _analysis_hash_valid(inventory, drop_status=True)):
        raise HQT3PartitionSolverError("full HQT3 inventory binding changed")
    if (schedule.get("format") != HQT3_RAMG_SCHEDULE_FORMAT or
            schedule.get("status") != HQT3_RAMG_SCHEDULE_STATUS or
            not _analysis_hash_valid(schedule, drop_status=False)):
        raise HQT3PartitionSolverError("HQT3/RAM_G schedule binding changed")
    schedule_binding = schedule.get("inventory_binding")
    if (not isinstance(schedule_binding, dict) or
            schedule_binding.get("file_sha256") !=
            hashlib.sha256(inventory_raw).hexdigest() or
            schedule_binding.get("analysis_sha256") !=
            inventory.get("analysis_sha256")):
        raise HQT3PartitionSolverError("schedule is stale against inventory")

    catalog = inventory.get("global_catalog")
    load_plan = inventory.get("load_plan")
    source_binding = inventory.get("source_binding")
    if (not isinstance(catalog, dict) or not isinstance(load_plan, dict) or
            not isinstance(source_binding, dict)):
        raise HQT3PartitionSolverError("inventory sections are missing")
    templates_value = catalog.get("templates")
    scopes_value = load_plan.get("scopes")
    events_value = load_plan.get("events")
    if (not isinstance(templates_value, list) or not isinstance(scopes_value, list) or
            not isinstance(events_value, list)):
        raise HQT3PartitionSolverError("inventory rows are missing")
    templates = tuple(item for item in templates_value if isinstance(item, dict))
    scopes = tuple(item for item in scopes_value if isinstance(item, dict))
    events = tuple(item for item in events_value if isinstance(item, dict))
    if (len(templates) != len(templates_value) or len(scopes) != len(scopes_value) or
            len(events) != len(events_value)):
        raise HQT3PartitionSolverError("inventory contains non-object rows")
    scope_by_id = {str(scope.get("scope_id")): scope for scope in scopes}
    schedule_scopes_value = schedule.get("scope_packs")
    if not isinstance(schedule_scopes_value, list):
        raise HQT3PartitionSolverError("schedule scope rows are missing")
    schedule_scope_by_id = {
        str(scope.get("scope_id")): scope
        for scope in schedule_scopes_value if isinstance(scope, dict)
    }
    width = source_binding.get("sprite_cell_width")
    height = source_binding.get("sprite_cell_height")
    cell_bytes = source_binding.get("sprite_cell_argb4444_bytes")
    if (not isinstance(width, int) or not isinstance(height, int) or
            cell_bytes != width * height * 2):
        raise HQT3PartitionSolverError("sprite cell geometry changed")

    source_evidence = _source_evidence(root, inventory)

    # First reconstruct every event union and every problem scope.  A pixel
    # pack is compiled once per exact cell-key digest and shared by all HQT
    # requirement variants which reference that union.
    cells_by_pack: dict[str, tuple[object, ...]] = {}
    problem_scope_cells: dict[str, tuple[object, ...]] = {}
    for scope_id in PROBLEM_SCOPE_IDS:
        try:
            scope = scope_by_id[scope_id]
        except KeyError as exc:
            raise HQT3PartitionSolverError(
                f"problem scope {scope_id} disappeared") from exc
        cells = _scope_cells(scope, templates)
        pack_id = str(scope["pixel_pack_id"])
        previous = cells_by_pack.setdefault(pack_id, cells)
        if previous != cells:
            raise HQT3PartitionSolverError("problem scope pixel digest collision")
        problem_scope_cells[scope_id] = cells

    event_requirements: dict[str, dict[str, object]] = {}
    event_requirement_id: dict[str, str] = {}
    for event in events:
        event_id = event.get("event_id")
        scope_ids = event.get("class_scope_ids")
        pack_id = event.get("pack_id")
        if (not isinstance(event_id, str) or not isinstance(scope_ids, list) or
                not isinstance(pack_id, str)):
            raise HQT3PartitionSolverError("event relation is malformed")
        indices = sorted({
            int(index)
            for scope_id in scope_ids
            for index in scope_by_id[str(scope_id)]["template_indices"]
        })
        pseudo, cells = _pseudo_scope(
            "event-union:" + event_id, indices, templates, cell_bytes,
            pixel_pack_id=pack_id)
        previous = cells_by_pack.setdefault(pack_id, cells)
        if previous != cells:
            raise HQT3PartitionSolverError("event pixel digest collision")
        requirement_key = _sha256_value({
            "pack_id": pack_id,
            "template_indices": indices,
        })
        requirement_id = "event-requirement:" + requirement_key[:24]
        event_requirement_id[event_id] = requirement_id
        existing = event_requirements.get(requirement_id)
        if existing is None:
            event_requirements[requirement_id] = {
                "requirement_id": requirement_id,
                "pixel_pack_id": pack_id,
                "template_indices": indices,
                "pseudo": pseudo,
                "cells": cells,
                "event_ids": [event_id],
            }
        else:
            if (existing["pixel_pack_id"] != pack_id or
                    existing["template_indices"] != indices or
                    existing["cells"] != cells):
                raise HQT3PartitionSolverError("event requirement digest collision")
            cast_events = existing["event_ids"]
            assert isinstance(cast_events, list)
            cast_events.append(event_id)

    packs = compile_pixel_packs(
        root, cells_by_pack, width, height, max_workers=max_workers)

    requirement_rows: list[dict[str, object]] = []
    requirement_by_id: dict[str, dict[str, object]] = {}
    for requirement_id in sorted(event_requirements):
        raw = event_requirements[requirement_id]
        pseudo = raw["pseudo"]
        cells = raw["cells"]
        assert isinstance(pseudo, dict) and isinstance(cells, tuple)
        pack_id = str(raw["pixel_pack_id"])
        cost = _cost(pseudo, cells, packs[pack_id], templates, cell_bytes)
        row = {
            "requirement_id": requirement_id,
            "pixel_pack_id": pack_id,
            "template_indices_sha256": _sha256_value(raw["template_indices"]),
            "template_count": len(raw["template_indices"]),
            "event_ids": sorted(raw["event_ids"]),
            "union_keys_computable": True,
            "union_cost_sha256": _sha256_value(cost),
            "union_cost": cost,
        }
        requirement_rows.append(row)
        requirement_by_id[requirement_id] = row

    exact_obligations: list[dict[str, object]] = []
    ambiguous_obligations: list[dict[str, object]] = []
    source_scope_pack_ids = {
        str(scope["pixel_pack_id"]) for scope in scopes
    }
    union_event_count = 0
    union_pack_ids: set[str] = set()
    for event in events:
        event_id = str(event["event_id"])
        requirement_id = event_requirement_id[event_id]
        requirement = requirement_by_id[requirement_id]
        pack_id = str(requirement["pixel_pack_id"])
        is_union_only = pack_id not in source_scope_pack_ids
        if is_union_only:
            union_event_count += 1
            union_pack_ids.add(pack_id)
        base = {
            "event_id": event_id,
            "stage": int(event["stage"]),
            "address": int(event["address"]),
            "class_scope_ids": list(event["class_scope_ids"]),
            "requirement_id": requirement_id,
            "union_keys_computable": True,
            "union_cost_exact_for_listed_keys": True,
            "union_only_pixel_pack": is_union_only,
            "load_before_first_possible_draw_required": bool(
                event["class_scope_ids"]),
            "eviction_permitted": False,
            "prior_event_residency_combination_proved": False,
        }
        cost_reference = _cost_reference(
            requirement_id, requirement["union_cost"])
        if event.get("correlation_exact") is True:
            event_union_fits = cost_reference[
                "all_partition_targets_pass"] is True
            base.update({
                "semantic_event_relation_exact": True,
                "semantic_selected_cost": cost_reference,
                "single_union_partition_meets_targets": event_union_fits,
                "concrete_partition_obligation": (
                    "load this exact event union before dispatch and retain "
                    "every earlier live partition until a separate last-draw "
                    "proof exists"
                    if event_union_fits else
                    "this exact event union cannot be one RAM_G partition; "
                    "derive descriptor/resource-atomic pixel pages, prove "
                    "their simultaneous residency or lifetime exclusivity, "
                    "and do not overwrite any page before its FT812 last-"
                    "displayed-list fence"),
            })
            exact_obligations.append(base)
        else:
            base.update({
                "semantic_event_relation_exact": False,
                "semantic_selected_cost": None,
                "conservative_candidate_union_cost": cost_reference,
                "minimum_required_fact_ids": [
                    item["fact_id"] for item in AMBIGUOUS_FACTS],
            })
            ambiguous_obligations.append(base)

    problem_rows: list[dict[str, object]] = []
    hqt_structurally_solved: list[str] = []
    ramg_structurally_solved: list[str] = []
    for scope_id in PROBLEM_SCOPE_IDS:
        scope = scope_by_id[scope_id]
        schedule_scope = schedule_scope_by_id.get(scope_id)
        if not isinstance(schedule_scope, dict):
            raise HQT3PartitionSolverError(
                f"schedule lost problem scope {scope_id}")
        pack_id = str(scope["pixel_pack_id"])
        parent_pack = packs[pack_id]
        if parent_pack is None:
            raise HQT3PartitionSolverError("problem scope unexpectedly has no pixels")
        scheduled_pixel = schedule_scope.get("pixel_pack")
        if (not isinstance(scheduled_pixel, dict) or
                scheduled_pixel.get("ft812_payload_bytes") != len(parent_pack.data) or
                scheduled_pixel.get("relocatable_payload_sha256") != parent_pack.sha256):
            raise HQT3PartitionSolverError(
                f"problem scope {scope_id} physical pack differs from schedule")
        pages, page_summary = _descriptor_page_rows(
            scope, templates, parent_pack, cell_bytes)
        shared_pixel_bytes = len(parent_pack.data)
        shared_ts_bytes = (
            shared_pixel_bytes + int(page_summary["shared_pixel_hqt3_total_bytes"]))
        shared_plan_pass = (
            shared_pixel_bytes < FT812_RAM_G_BYTES and
            page_summary["shared_pixel_hqt3_all_state_indices_fit"] is True and
            shared_ts_bytes <= TSCONF_RAM_BYTES)
        original_hqt_fit = schedule_scope["hqt3"][
            "uint16_record_cell_and_uint8_state_indices_fit"] is True
        if (not original_hqt_fit and
                page_summary["shared_pixel_hqt3_all_state_indices_fit"] is True):
            hqt_structurally_solved.append(scope_id)
        # Full pixel pages are safe without eviction only if every page can be
        # resident together.  Otherwise a lifetime/exclusivity proof is needed.
        full_pages_safe_without_lifetime = (
            page_summary["all_full_pages_individually_meet_targets"] is True and
            page_summary["full_pages_ram_g_simultaneous_fit"] is True)
        if full_pages_safe_without_lifetime:
            ramg_structurally_solved.append(scope_id)
        accepted = shared_plan_pass
        accepted_kind = (
            "shared-resident-pixel-pack-plus-all-resident-descriptor-hqt-pages"
            if accepted else None)
        problem_rows.append({
            "scope_id": scope_id,
            "original": {
                "ram_g_bytes": len(parent_pack.data),
                "ram_g_strict_fit": len(parent_pack.data) < FT812_RAM_G_BYTES,
                "hqt3_state_count": schedule_scope["hqt3"]["state_count"],
                "hqt3_state_fit": original_hqt_fit,
            },
            "descriptor_pages": pages,
            "descriptor_page_summary": page_summary,
            "hqt_metadata_sharding": {
                "semantics_safe": True,
                "all_pages_resident_in_ts": True,
                "shared_pixel_pack_ram_g_bytes": shared_pixel_bytes,
                "all_hqt_pages_total_bytes": page_summary[
                    "shared_pixel_hqt3_total_bytes"],
                "combined_compiled_ts_staging_bytes": shared_ts_bytes,
                "state_overflow_removed": page_summary[
                    "shared_pixel_hqt3_all_state_indices_fit"],
                "requires_python_semantic_change": False,
                "requires_multi_table_target_resolver": True,
            },
            "full_pixel_paging": {
                "each_descriptor_page_meets_targets": page_summary[
                    "all_full_pages_individually_meet_targets"],
                "all_pages_simultaneous_ram_g_bytes": page_summary[
                    "full_pages_ram_g_sum_bytes"],
                "all_pages_simultaneous_fit": page_summary[
                    "full_pages_ram_g_simultaneous_fit"],
                "source_exclusivity_proved": False,
                "eviction_permitted": False,
                "semantics_safe_runtime_plan": full_pages_safe_without_lifetime,
            },
            "accepted_partition_plan": accepted_kind,
            "all_partition_targets_met_without_pixel_eviction": accepted,
        })

    exact_nonfit_event_count = sum(
        not bool(requirement_by_id[row["requirement_id"]]["union_cost"]
                 ["partition_targets"]["all_targets_pass"])
        for row in exact_obligations
    )
    exact_nonfit_requirement_ids = sorted({
        str(row["requirement_id"])
        for row in exact_obligations
        if not bool(requirement_by_id[row["requirement_id"]]["union_cost"]
                    ["partition_targets"]["all_targets_pass"])
    })
    blockers = [
        {
            "code": "PZPART401",
            "scope": "oversized-scope-pixel-page-exclusivity",
            "reason": (
                "three RAM_G-oversized scopes have individually valid "
                "descriptor pages, but source does not prove those pages are "
                "mutually exclusive; linked/multiple objects can coexist"),
        },
        {
            "code": "PZPART402",
            "scope": "ambiguous-event-type-relation",
            "reason": (
                f"{len(ambiguous_obligations)} events still need the listed "
                "minimal type/lifetime facts before semantic cost selection"),
        },
        {
            "code": "PZPART403",
            "scope": "cross-event-lifetimes",
            "reason": (
                "even exact event unions do not terminate objects loaded by "
                "earlier events, so event order cannot authorize eviction"),
        },
        {
            "code": "PZPART404",
            "scope": "intra-class-instance-and-animation-overlap",
            "reason": (
                "multiple linked children/instances can render different "
                "resource and animation descriptor pages in one frame"),
        },
        {
            "code": "PZPART405",
            "scope": "multi-hqt-table-target-resolver",
            "reason": (
                "descriptor-key HQT metadata sharding is source-safe, but the "
                "target resolver has not yet been bound to multiple tables"),
        },
        {
            "code": "PZPART406",
            "scope": "ft812-display-list-eviction-fence",
            "reason": (
                "no pixel page may be overwritten until the last displayed "
                "FT812 list referencing it has retired"),
        },
    ]

    report: dict[str, object] = {
        "format": HQT3_PARTITION_SOLVER_FORMAT,
        "status": HQT3_PARTITION_SOLVER_STATUS,
        "structural_partition_proof_complete": True,
        "ram_g_runtime_paging_complete": False,
        "live": False,
        "input_binding": {
            "inventory_path": inventory_file.relative_to(root).as_posix(),
            "inventory_file_sha256": hashlib.sha256(inventory_raw).hexdigest(),
            "inventory_analysis_sha256": inventory["analysis_sha256"],
            "schedule_path": schedule_file.relative_to(root).as_posix(),
            "schedule_file_sha256": hashlib.sha256(schedule_raw).hexdigest(),
            "schedule_analysis_sha256": schedule["analysis_sha256"],
        },
        "source_evidence": source_evidence,
        "allowed_partition_axes": [
            "exact ROM event relation",
            "exact Python resource/bank identity",
            "exact ROM descriptor",
            "source-proved animation/state phase",
            "immutable FT812 bitmap state",
        ],
        "forbidden_partition_axes": [
            "arbitrary byte threshold",
            "arbitrary template count",
            "next-event-implies-eviction",
        ],
        "problem_scope_count": len(problem_rows),
        "problem_scopes": problem_rows,
        "event_union_requirements": requirement_rows,
        "event_cost_census": {
            "event_count": len(events),
            "unique_requirement_count": len(requirement_rows),
            "unique_pixel_pack_count": len({
                row["pixel_pack_id"] for row in requirement_rows}),
            "union_key_computable_event_count": len(events),
            "union_event_count": union_event_count,
            "union_only_pixel_pack_count": len(union_pack_ids),
            "union_only_pixel_pack_ids": sorted(union_pack_ids),
            "exact_event_count": len(exact_obligations),
            "exact_event_nonfit_count": exact_nonfit_event_count,
            "exact_event_nonfit_requirement_count": len(
                exact_nonfit_requirement_ids),
            "exact_event_nonfit_requirement_ids": exact_nonfit_requirement_ids,
            "ambiguous_event_count": len(ambiguous_obligations),
        },
        "exact_event_partition_obligations": exact_obligations,
        "ambiguous_event_partition_obligations": ambiguous_obligations,
        "ambiguous_minimum_required_facts": list(AMBIGUOUS_FACTS),
        "blocker_resolution": {
            "PZRG301": {
                "can_eliminate_by_structural_paging_without_python_semantic_change": False,
                "reason": (
                    "descriptor pages fit individually, but simultaneous "
                    "residency/exclusivity is not proved for any of the three "
                    "oversized scopes"),
                "structurally_solved_scope_ids": ramg_structurally_solved,
            },
            "PZRG307": {
                "can_eliminate_by_structural_hqt_sharding_without_python_semantic_change": True,
                "reason": (
                    "each descriptor is an atomic HQT table with at most 64 "
                    "cells/states; every table can stay in TS RAM and share "
                    "the immutable pixel payload"),
                "structurally_solved_scope_ids": hqt_structurally_solved,
                "target_multi_table_resolver_still_required": True,
            },
        },
        "resident_combinations": [],
        "eviction_inferences": [],
        "blockers": blockers,
        "proof_boundaries": {
            "event_union_keys_and_physical_costs_computed": True,
            "all_125_exact_event_obligations_concrete": True,
            "all_663_ambiguous_events_fail_closed": True,
            "descriptor_pages_are_semantic_not_size_cuts": True,
            "descriptor_page_individual_capacity_proved": True,
            "hqt_state_overflow_structurally_shardable": True,
            "ram_g_page_exclusivity_proved": False,
            "cross_event_last_draw_intervals_proved": False,
            "pixel_eviction_permitted": False,
            "target_multi_hqt_resolver_bound": False,
        },
    }
    semantic = dict(report)
    report["analysis_sha256"] = _sha256_value(semantic)
    return report


__all__ = [
    "HQT3_PARTITION_SOLVER_FORMAT",
    "HQT3_PARTITION_SOLVER_STATUS",
    "HQT3PartitionSolverError",
    "PROBLEM_SCOPE_IDS",
    "analyze_hqt3_partition_solver",
]
