"""Generic semantic-domain to FT812 resident-working-set planner.

The frontend owns semantic facts such as "stage 3 enemies" or "Force beam
state".  This module deliberately knows none of those names.  It receives the
finite cell domain for every fact plus the combinations proven simultaneously
resident by the frontend, then compiles each combination with the exact FT812
asset backend.  Unknown, empty, or uncovered domains fail closed.

This separates three concerns which previously became hand-maintained lists:

1. the Python analyser proves finite semantic domains;
2. this planner proves complete resident combinations and byte limits;
3. a target adapter serialises the resulting immutable packs and transitions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from .assets import AssetCompileError, CellBankSpec, CellKey
from .ft812_assets import (
    FT812AssetPackBudget,
    FT812CellAssetPack,
    compile_ft812_cell_assets,
)


FT812_WORKING_SET_PLAN_FORMAT = "pyz80-ft812-working-sets-v1"


@dataclass(frozen=True, order=True)
class FT812WorkingSetSpec:
    """One frontend-proven combination which must fit RAM_G at once."""

    name: str
    domains: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.name:
            raise AssetCompileError("FT812 working-set name cannot be empty")
        if not self.domains:
            raise AssetCompileError(
                f"FT812 working set {self.name!r} has no semantic domains")
        if any(not domain for domain in self.domains):
            raise AssetCompileError(
                f"FT812 working set {self.name!r} has an empty domain name")
        if tuple(sorted(set(self.domains))) != self.domains:
            raise AssetCompileError(
                f"FT812 working set {self.name!r} domains must be unique/sorted")


@dataclass(frozen=True)
class FT812WorkingSet:
    """One exact compiled resident combination."""

    name: str
    domains: tuple[str, ...]
    pack: FT812CellAssetPack

    def report(self) -> dict[str, object]:
        result = self.pack.report()
        result.update({
            "name": self.name,
            "domains": list(self.domains),
        })
        return result


@dataclass(frozen=True)
class FT812WorkingSetPlan:
    """Complete proof that every frontend domain has a resident owner."""

    domain_counts: tuple[tuple[str, int], ...]
    sets: tuple[FT812WorkingSet, ...]

    def report(self) -> dict[str, object]:
        return {
            "format": FT812_WORKING_SET_PLAN_FORMAT,
            "domain_counts": dict(self.domain_counts),
            "working_set_count": len(self.sets),
            "sets": [working_set.report() for working_set in self.sets],
        }


def compile_ft812_working_sets(
        domains: Mapping[str, Iterable[CellKey]],
        banks: Iterable[CellBankSpec],
        specifications: Iterable[FT812WorkingSetSpec],
        budget: FT812AssetPackBudget,
        *,
        project_root=None,
        ) -> FT812WorkingSetPlan:
    """Compile all frontend-proven simultaneous-residency combinations."""
    domain_map: dict[str, tuple[CellKey, ...]] = {}
    for name, requested in domains.items():
        if not name:
            raise AssetCompileError("FT812 semantic domain name cannot be empty")
        keys = tuple(sorted(set(requested)))
        if not keys:
            raise AssetCompileError(
                f"FT812 semantic domain {name!r} has no cells")
        domain_map[name] = keys
    if not domain_map:
        raise AssetCompileError("FT812 working-set plan has no semantic domains")

    spec_tuple = tuple(sorted(specifications))
    if not spec_tuple:
        raise AssetCompileError("FT812 working-set plan has no combinations")
    if len({spec.name for spec in spec_tuple}) != len(spec_tuple):
        raise AssetCompileError("duplicate FT812 working-set name")

    known = set(domain_map)
    referenced = {domain for spec in spec_tuple for domain in spec.domains}
    unknown = sorted(referenced - known)
    if unknown:
        raise AssetCompileError(
            "FT812 working sets reference unknown domains: " +
            ", ".join(unknown))
    uncovered = sorted(known - referenced)
    if uncovered:
        raise AssetCompileError(
            "FT812 semantic domains have no resident working set: " +
            ", ".join(uncovered))

    bank_tuple = tuple(banks)
    compiled: list[FT812WorkingSet] = []
    for spec in spec_tuple:
        requested = {
            key for domain in spec.domains for key in domain_map[domain]
        }
        try:
            pack = compile_ft812_cell_assets(
                requested, bank_tuple, budget, project_root=project_root)
        except AssetCompileError as exc:
            raise AssetCompileError(
                f"FT812 working set {spec.name!r} failed: {exc}") from exc
        # Independent ownership assertion: each requested semantic key must
        # be present, even when physical payloads were deduplicated.
        actual = {entry.key for entry in pack.entries}
        if actual != requested:
            raise AssetCompileError(
                f"FT812 working set {spec.name!r} lost semantic cells")
        compiled.append(FT812WorkingSet(spec.name, spec.domains, pack))

    return FT812WorkingSetPlan(
        domain_counts=tuple(
            (name, len(keys)) for name, keys in sorted(domain_map.items())),
        sets=tuple(compiled),
    )


__all__ = [
    "FT812_WORKING_SET_PLAN_FORMAT",
    "FT812WorkingSet",
    "FT812WorkingSetPlan",
    "FT812WorkingSetSpec",
    "compile_ft812_working_sets",
]
