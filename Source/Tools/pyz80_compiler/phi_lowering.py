"""Destroy SSA phi nodes on their incoming edges, before target encoding.

No object adapter can implement phi: eagerly resolving all its arguments
already reads the unexecuted branch. Edge copies read only the taken input.
They preserve value identity and need no predecessor register in the Z80 VM.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any

from .cfg_ssa import DominatingDefinitions


class PhiLoweringError(ValueError):
    pass


def lower_phi_units(units: Sequence[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict]:
    output = []
    records = []
    phi_count = copy_count = split_count = scratch_count = 0
    for original in units:
        if not any(item.get("op") == "phi" for block in original["blocks"]
                   for item in block["instructions"]):
            output.append(original)
            continue
        unit = copy.deepcopy(original)
        proof = DominatingDefinitions(unit)
        blocks = unit["blocks"]
        by_name = {block["name"]: block for block in blocks}
        ids = {block["name"]: index for index, block in enumerate(blocks)}
        predecessors = {name: set() for name in by_name}
        for block in blocks:
            for target in block["terminator"]["targets"]:
                predecessors[target].add(block["name"])
        used_names = set(proof.definitions) | set(by_name)

        def fresh(prefix: str) -> str:
            index = 0
            while f"{prefix}{index}" in used_names:
                index += 1
            name = f"{prefix}{index}"
            used_names.add(name)
            return name

        # Validate the complete original CFG before changing any edge.
        plans = []
        for target in blocks:
            phis = []
            seen_non_phi = False
            for item in target["instructions"]:
                if item.get("op") != "phi":
                    seen_non_phi = True
                    continue
                if seen_non_phi:
                    raise PhiLoweringError("phi must precede ordinary instructions")
                name = target["name"]
                if name == unit["entry"] or ids[name] not in proof.dominators:
                    raise PhiLoweringError("phi block has no proven incoming execution edge")
                destination = item.get("destination")
                if (not isinstance(destination, str) or not destination.startswith("%") or
                        len(proof.definitions.get(destination, ())) != 1):
                    raise PhiLoweringError("phi destination is missing or not unique SSA")
                arguments = item.get("arguments")
                attributes = item.get("attributes", {})
                if (not isinstance(arguments, list) or not arguments or len(arguments) % 2 or
                        not isinstance(attributes, Mapping) or
                        attributes.get("incoming_count", len(arguments) // 2) != len(arguments) // 2):
                    raise PhiLoweringError("phi incoming layout is malformed")
                incoming = {}
                for offset in range(0, len(arguments), 2):
                    predecessor, value = arguments[offset:offset + 2]
                    if (not isinstance(predecessor, str) or predecessor in incoming or
                            predecessor not in predecessors[name]):
                        raise PhiLoweringError("phi incoming edge is missing, duplicated or not a predecessor")
                    if not isinstance(value, str) or not value.startswith("%"):
                        raise PhiLoweringError("phi value must be a proven SSA reference")
                    definitions = proof.definitions.get(value, ())
                    if len(definitions) != 1:
                        raise PhiLoweringError("phi input has no unique SSA definition")
                    owner, _, _ = definitions[0]
                    if not proof.dominators.get(ids[predecessor], 0) & (1 << owner):
                        raise PhiLoweringError("phi input is not defined on its incoming edge")
                    incoming[predecessor] = value
                if set(incoming) != predecessors[name]:
                    raise PhiLoweringError("phi must cover every predecessor exactly once")
                if any(block.get("exception_target") == name for block in blocks):
                    raise PhiLoweringError("exception-edge phi needs an exception transfer contract")
                phis.append((item, incoming))
            if phis:
                plans.append((target, phis))

        # Remove phi groups first, including loop headers that are predecessors.
        for target, phis in plans:
            target["instructions"] = target["instructions"][len(phis):]
        for target, phis in plans:
            phi_count += len(phis)
            name = target["name"]
            for predecessor in sorted(predecessors[name], key=ids.__getitem__):
                pred = by_name[predecessor]
                pending = {item["destination"]: incoming[predecessor]
                           for item, incoming in phis
                           if item["destination"] != incoming[predecessor]}
                moves = []

                def move(destination: str, value: str) -> None:
                    moves.append({"op": "vm-copy", "destination": destination,
                                  "value_kind": "py-value", "arguments": [value]})

                # Parallel-copy scheduling: never overwrite a still-needed source.
                # A cycle needs one saved old value, not C recursion or Python calls.
                while pending:
                    sources = set(pending.values())
                    ready = next((dest for dest in pending if dest not in sources), None)
                    if ready is not None:
                        move(ready, pending.pop(ready))
                        continue
                    saved = next(iter(pending))
                    temporary = fresh("%phi_saved_")
                    scratch_count += 1
                    move(temporary, saved)
                    pending = {dest: temporary if value == saved else value
                               for dest, value in pending.items()}
                copy_count += len(moves)
                if not moves:
                    edge_name = None
                elif (pred["terminator"]["op"] == "jump" and
                      pred["terminator"]["targets"] == [name] and
                      not pred["terminator"].get("arguments")):
                    pred["instructions"].extend(moves)
                    edge_name = predecessor
                else:
                    edge_name = fresh("phi_edge_")
                    split_count += 1
                    blocks.append({"name": edge_name, "instructions": moves,
                                   "terminator": {"op": "jump", "arguments": [],
                                                  "targets": [name]}})
                    pred["terminator"]["targets"] = [
                        edge_name if value == name else value
                        for value in pred["terminator"]["targets"]]
                records.append({"unit": unit["name"], "predecessor": predecessor,
                                "target": name, "copy_block": edge_name,
                                "copies": moves,
                                "source_phi": [item for item, _ in phis]})
        # Target-only sequence numbers; original source instructions remain in proof.
        sequence = 0
        for block in blocks:
            for item in block["instructions"]:
                item["sequence"] = sequence
                sequence += 1
        output.append(unit)
    return output, {"format": "pyz80.phi-edge-lowering.v1",
                    "phi_instruction_count": phi_count,
                    "edge_copy_instruction_count": copy_count,
                    "split_edge_count": split_count,
                    "scratch_local_count": scratch_count,
                    "edges": records}
