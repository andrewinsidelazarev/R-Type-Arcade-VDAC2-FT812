"""Per-unit SSA visibility index shared by call analysis and emission.

Indexes live for one translation pass only.  No cached proof can survive a
source edit.  A value with multiple reachable definitions is never promoted
to a unique definition, even if only one definition dominates the use.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from typing import Any


class CFGSSAError(ValueError):
    pass


class DominatingDefinitions:
    def __init__(self, unit: Mapping[str, Any]) -> None:
        blocks = unit.get("blocks")
        if not isinstance(blocks, list) or not blocks:
            raise CFGSSAError("CFG has no block list")
        names = [row.get("name") if isinstance(row, Mapping) else None
                 for row in blocks]
        if (any(not isinstance(name, str) for name in names) or
                len(set(names)) != len(names) or unit.get("entry") not in names):
            raise CFGSSAError("CFG block names/entry are malformed")
        ids = {name: index for index, name in enumerate(names)}
        entry = ids[unit["entry"]]
        edges: list[list[int]] = []
        predecessors: list[set[int]] = [set() for _ in blocks]
        for index, block in enumerate(blocks):
            term = block.get("terminator")
            targets = term.get("targets") if isinstance(term, Mapping) else None
            instructions = block.get("instructions")
            if (not isinstance(targets, list) or any(
                    not isinstance(target, str) or target not in ids
                    for target in targets) or not isinstance(instructions, list)
                    or any(not isinstance(row, Mapping) for row in instructions)):
                raise CFGSSAError("CFG instructions/edges are malformed")
            successors = [ids[target] for target in targets]
            edges.append(successors)
            for successor in successors:
                predecessors[successor].add(index)
        reachable = {entry}
        pending = [entry]
        while pending:
            for successor in edges[pending.pop()]:
                if successor not in reachable:
                    reachable.add(successor)
                    pending.append(successor)
        # Integer bitsets avoid repeated allocation of large Python sets.
        all_bits = sum(1 << index for index in reachable)
        dom = {index: (1 << entry if index == entry else all_bits)
               for index in reachable}
        changed = True
        order = sorted(reachable - {entry})
        while changed:
            changed = False
            for index in order:
                incoming = predecessors[index] & reachable
                shared = all_bits
                for predecessor in incoming:
                    shared &= dom[predecessor]
                updated = (1 << index) | shared
                if updated != dom[index]:
                    dom[index] = updated
                    changed = True
        definitions: dict[str, list[tuple[int, int, Mapping[str, Any]]]] = (
            defaultdict(list))
        for block_index in sorted(reachable):
            for index, row in enumerate(blocks[block_index]["instructions"]):
                destination = row.get("destination")
                if isinstance(destination, str):
                    definitions[destination].append((block_index, index, row))
        self.blocks = blocks
        self.dominators = dom
        self.definitions = definitions

    def at(self, block: int, instruction: int) -> dict[str, list[Mapping[str, Any]]]:
        if (block not in self.dominators or
                not 0 <= instruction < len(self.blocks[block]["instructions"])):
            raise CFGSSAError("CFG use is out of range or unreachable")
        strict = self.dominators[block] & ~(1 << block)
        result = {}
        for name, locations in self.definitions.items():
            if len(locations) > 1:
                result[name] = [row for _, _, row in locations]
                continue
            owner, index, row = locations[0]
            if (owner == block and index < instruction) or (strict & (1 << owner)):
                result[name] = [row]
        return result
