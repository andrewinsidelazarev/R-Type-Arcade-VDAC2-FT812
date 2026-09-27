"""Fail-closed sprite working-set planning for the active Python program.

``sprite_coverage`` proves which descriptor/resource pairs are reachable.  It
does *not* prove that the whole stage union, or even two consecutive event
closures, are simultaneously alive.  This module preserves that distinction:

* common and stage/class pair relations are converted to exact logical cells;
* event reachability envelopes are formed only by unioning already-related
  class pairs (there is no descriptor/resource Cartesian product);
* identical logical event envelopes share one immutable pack definition;
* every unique definition is measured by the lossless FT812 asset backend;
* the active Force resource manager is audited to replace its false sixteen-
  palette fallback union with sixteen mutually-exclusive type-$3D epochs;
* resident combinations remain unissued when scheduler lifetime overlap is
  not present in the coverage proof.

The resulting blocked plan is intentional and useful: it is a complete asset
inventory with exact byte measurements plus the smallest missing semantic
invariants.  A target adapter must never reinterpret an event envelope as a
resident-set certificate.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from .assets import AssetCompileError, CellBankSpec, CellKey, CellSourceKey
from .ft812_assets import FT812AssetPackBudget, compile_ft812_cell_assets
from .sprite_coverage import (
    ACTIVE_ROOT_MODULE,
    CoverageReport,
    DescriptorResourcePair,
    PythonBankKey,
    SpriteCoverageError,
    analyze_sprite_coverage,
)


SPRITE_WORKING_SET_PLAN_FORMAT = "pyz80-sprite-working-sets-v2"
FORCE_PALETTE_EPOCH_FORMAT = "pyz80-force-p3d-palette-epoch-v1"
FORCE_P3D_RESOURCE_TYPE = 0x3D
FORCE_P3D_DOMAIN_NAMES = (
    "force_beams", "force_darts", "force_grids", "force_rays",
)
FORCE_COEXISTING_DOMAIN_NAMES = (
    "force_body", "force_projectiles", *FORCE_P3D_DOMAIN_NAMES,
)
FORCE_P3D_EXPECTED_PAIR_COUNTS = (
    ("force_beams", 192),
    ("force_darts", 15),
    ("force_grids", 11),
    ("force_rays", 16),
)


class SpriteWorkingSetError(ValueError):
    """The inputs cannot support a complete, literal working-set proof."""


@dataclass(frozen=True, order=True)
class SpriteCellRef:
    """Target-neutral identity of one cell observed by active Python."""

    bank: PythonBankKey
    code: int
    flip_x: bool = False
    flip_y: bool = False

    def __post_init__(self) -> None:
        if not 0 <= self.code <= 0x0FFF:
            raise SpriteWorkingSetError(
                f"sprite cell code is outside 12 bits: {self.code!r}")

    @property
    def stable_name(self) -> str:
        return (
            f"{self.bank.kind}:{self.bank.value:02X}:{self.code:03X}:"
            f"fx{int(self.flip_x)}:fy{int(self.flip_y)}"
        )


@dataclass(frozen=True)
class SpriteDomain:
    """One exact semantic pair domain and its non-Cartesian cell expansion."""

    domain_id: str
    kind: str
    stage: int | None
    class_name: str | None
    source_symbols: tuple[str, ...]
    pairs: tuple[DescriptorResourcePair, ...]
    cells: tuple[SpriteCellRef, ...]
    pair_sha256: str
    pack_id: str

    def summary(self) -> dict[str, object]:
        return {
            "domain_id": self.domain_id,
            "kind": self.kind,
            "stage": self.stage,
            "class_name": self.class_name,
            "source_symbols": list(self.source_symbols),
            "pair_count": len(self.pairs),
            "pair_sha256": self.pair_sha256,
            "cell_count": len(self.cells),
            "pack_id": self.pack_id,
        }


@dataclass(frozen=True)
class EventReachabilityPack:
    """Class-lifetime closure reachable from one active ROM event.

    This is deliberately not named a resident set.  ``correlation_exact`` is
    false when the coverage report aggregates a rendered class over multiple
    handler/command signatures and therefore cannot select that event's exact
    subset of class pairs.
    """

    stage: int
    address: int
    threshold: int
    command: int
    handler: int
    classes: tuple[str, ...]
    class_domain_ids: tuple[str, ...]
    pair_count: int
    pair_sha256: str
    cell_count: int
    pack_id: str
    correlation_exact: bool
    ambiguous_classes: tuple[str, ...]

    @property
    def event_id(self) -> str:
        return f"stage:{self.stage}:event:{self.address:04X}"

    def summary(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "stage": self.stage,
            "address": self.address,
            "threshold": self.threshold,
            "command": self.command,
            "handler": self.handler,
            "classes": list(self.classes),
            "class_domain_ids": list(self.class_domain_ids),
            "pair_count": self.pair_count,
            "pair_sha256": self.pair_sha256,
            "cell_count": self.cell_count,
            "pack_id": self.pack_id,
            "correlation_exact": self.correlation_exact,
            "ambiguous_classes": list(self.ambiguous_classes),
        }


@dataclass(frozen=True)
class FT812PackMeasurement:
    """Exact lossless byte cost of one target-neutral logical cell set."""

    pack_id: str
    cell_count: int
    unique_cells: int
    raw_argb4444_bytes: int
    ft812_bytes: int
    saved_bytes: int
    palette_count: int
    argb4_entries: int
    paletted4444_entries: int
    blob_sha256: str
    owner_ids: tuple[str, ...]

    def summary(self) -> dict[str, object]:
        return {
            "pack_id": self.pack_id,
            "cell_count": self.cell_count,
            "unique_cells": self.unique_cells,
            "raw_argb4444_bytes": self.raw_argb4444_bytes,
            "ft812_bytes": self.ft812_bytes,
            "saved_bytes": self.saved_bytes,
            "palette_count": self.palette_count,
            "format_counts": {
                "ARGB4": self.argb4_entries,
                "PALETTED4444": self.paletted4444_entries,
            },
            "blob_sha256": self.blob_sha256,
            "owner_ids": list(self.owner_ids),
        }


@dataclass(frozen=True)
class SchedulerFacts:
    """Only the concurrency facts literally established by active source."""

    source_sha256: str
    object_pool_slots: int
    initially_allocatable_slots: int
    maximum_event_dispatches_per_update: int
    retains_live_objects_across_updates: bool
    appends_event_objects_to_existing_list: bool
    event_specific_lifetime_bounds: bool

    def summary(self) -> dict[str, object]:
        return {
            "source_sha256": self.source_sha256,
            "object_pool_slots": self.object_pool_slots,
            "initially_allocatable_slots": self.initially_allocatable_slots,
            "maximum_event_dispatches_per_update": (
                self.maximum_event_dispatches_per_update),
            "retains_live_objects_across_updates": (
                self.retains_live_objects_across_updates),
            "appends_event_objects_to_existing_list": (
                self.appends_event_objects_to_existing_list),
            "event_specific_lifetime_bounds": (
                self.event_specific_lifetime_bounds),
        }


@dataclass(frozen=True)
class ForcePaletteEpochCandidate:
    """One exact alternative for the single live Force type-$3D slot.

    The candidate deliberately contains the union of rays, grids, beams and
    darts for one palette slot.  Those four families can coexist, whereas the
    sixteen palette slots cannot: they are alternatives selected by the
    resource manager's unique type-$3D allocation epoch.
    """

    palette_slot: int
    domain_id: str
    source_domain_ids: tuple[str, ...]
    pair_count: int
    pair_sha256: str
    cells: tuple[SpriteCellRef, ...]
    pack_id: str

    def summary(self, measurement: FT812PackMeasurement) -> dict[str, object]:
        if measurement.pack_id != self.pack_id:
            raise SpriteWorkingSetError(
                f"Force palette epoch {self.palette_slot:02X} measurement "
                "does not match its logical pack")
        return {
            "domain_id": self.domain_id,
            "palette_slot": self.palette_slot,
            "bank": {
                "kind": "palette-fallback",
                "value": self.palette_slot,
            },
            "source_domain_ids": list(self.source_domain_ids),
            "pair_count": self.pair_count,
            "pair_sha256": self.pair_sha256,
            "cell_count": len(self.cells),
            "pack_id": self.pack_id,
            "ft812_bytes": measurement.ft812_bytes,
            "blob_sha256": measurement.blob_sha256,
        }


@dataclass(frozen=True)
class ForcePaletteEpochProof:
    """Source-bound proof that Force fallback palettes are exclusive epochs."""

    source_hashes: tuple[tuple[str, str], ...]
    resource_type: int
    acquire_site_counts: tuple[tuple[str, int], ...]
    update_order: tuple[str, ...]
    state_domain_pair_counts: tuple[tuple[str, int], ...]
    coexisting_domain_ids: tuple[str, ...]
    epoch_source_domain_ids: tuple[str, ...]
    candidates: tuple[ForcePaletteEpochCandidate, ...]

    @property
    def evidence_sha256(self) -> str:
        evidence = {
            "format": FORCE_PALETTE_EPOCH_FORMAT,
            "source_hashes": list(self.source_hashes),
            "resource_type": self.resource_type,
            "acquire_site_counts": list(self.acquire_site_counts),
            "update_order": list(self.update_order),
            "state_domain_pair_counts": list(self.state_domain_pair_counts),
            "coexisting_domain_ids": list(self.coexisting_domain_ids),
            "epoch_source_domain_ids": list(self.epoch_source_domain_ids),
            "candidates": [
                {
                    "palette_slot": item.palette_slot,
                    "domain_id": item.domain_id,
                    "pair_count": item.pair_count,
                    "pair_sha256": item.pair_sha256,
                    "cell_count": len(item.cells),
                    "pack_id": item.pack_id,
                }
                for item in self.candidates
            ],
        }
        encoded = json.dumps(
            evidence, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def summary(
            self, measurements: Mapping[str, FT812PackMeasurement],
            ) -> dict[str, object]:
        candidate_measurements: list[FT812PackMeasurement] = []
        summaries: list[dict[str, object]] = []
        for candidate in self.candidates:
            measurement = measurements.get(candidate.pack_id)
            if measurement is None:
                raise SpriteWorkingSetError(
                    f"Force palette epoch {candidate.palette_slot:02X} "
                    "has no exact FT812 measurement")
            candidate_measurements.append(measurement)
            summaries.append(candidate.summary(measurement))
        if not candidate_measurements:
            raise SpriteWorkingSetError("Force palette epoch proof is empty")
        maximum = max(item.ft812_bytes for item in candidate_measurements)
        maximum_slots = [
            candidate.palette_slot
            for candidate, measurement in zip(
                self.candidates, candidate_measurements, strict=True)
            if measurement.ft812_bytes == maximum
        ]
        return {
            "format": FORCE_PALETTE_EPOCH_FORMAT,
            "evidence_sha256": self.evidence_sha256,
            "source_hashes": dict(self.source_hashes),
            "resource_type": self.resource_type,
            "bank_kind": "palette-fallback",
            "at_most_one_live_epoch": True,
            "candidate_count": len(self.candidates),
            "exact_max_ft812_bytes": maximum,
            "exact_max_palette_slots": maximum_slots,
            "acquire_site_counts": dict(self.acquire_site_counts),
            "update_order": list(self.update_order),
            "state_domain_pair_counts": dict(self.state_domain_pair_counts),
            "coexisting_domain_ids": list(self.coexisting_domain_ids),
            "epoch_source_domain_ids": list(self.epoch_source_domain_ids),
            "candidates": summaries,
            "resident_combination_claimed": False,
        }


@dataclass(frozen=True, order=True)
class MissingInvariant:
    """One minimal proof obligation required before a resident split exists."""

    code: str
    scope: str
    required_fact: str
    reason: str
    source_symbols: tuple[str, ...]

    def summary(self) -> dict[str, object]:
        return {
            "code": self.code,
            "scope": self.scope,
            "required_fact": self.required_fact,
            "reason": self.reason,
            "source_symbols": list(self.source_symbols),
        }


@dataclass(frozen=True)
class WorkingSetPlan:
    """Target-neutral sprite inventory and resident-proof status."""

    root_module: str
    coverage_source_hashes: tuple[tuple[str, str], ...]
    rom_sha256: str
    scheduler: SchedulerFacts
    common_domains: tuple[SpriteDomain, ...]
    class_domains: tuple[SpriteDomain, ...]
    event_packs: tuple[EventReachabilityPack, ...]
    ambient_class_domain_ids: tuple[str, ...]
    unique_pack_measurements: tuple[FT812PackMeasurement, ...]
    proven_resident_combinations: tuple[tuple[str, tuple[str, ...]], ...]
    missing_invariants: tuple[MissingInvariant, ...]
    force_palette_epoch: ForcePaletteEpochProof | None = None

    @property
    def ready(self) -> bool:
        return not self.missing_invariants

    @property
    def status(self) -> str:
        return "READY" if self.ready else "BLOCKED_MISSING_LIFETIME_PROOF"

    @property
    def source_binding_sha256(self) -> str:
        """Hash the exact active-Python/ROM identity, independent of target."""
        binding = {
            "root_module": self.root_module,
            "coverage_source_hashes": list(self.coverage_source_hashes),
            "rom_sha256": self.rom_sha256,
        }
        encoded = json.dumps(
            binding, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def as_dict(self) -> dict[str, object]:
        event_unique = len({event.pack_id for event in self.event_packs})
        exact_events = sum(event.correlation_exact for event in self.event_packs)
        measurements = {
            item.pack_id: item for item in self.unique_pack_measurements
        }
        epoch_sources = (set(self.force_palette_epoch.epoch_source_domain_ids)
                         if self.force_palette_epoch is not None else set())
        common_summaries: list[dict[str, object]] = []
        for item in self.common_domains:
            summary = item.summary()
            if item.domain_id in epoch_sources:
                summary["measurement_role"] = (
                    "reachability-alternatives-replaced-by-p3d-epochs")
                summary["measured_as_independent_pack"] = False
            else:
                summary["measured_as_independent_pack"] = True
            common_summaries.append(summary)
        return {
            "format": SPRITE_WORKING_SET_PLAN_FORMAT,
            "status": self.status,
            "ready": self.ready,
            "root_module": self.root_module,
            "coverage_source_hashes": dict(self.coverage_source_hashes),
            "rom_sha256": self.rom_sha256,
            "source_binding_sha256": self.source_binding_sha256,
            "scheduler": self.scheduler.summary(),
            "common_domains": common_summaries,
            "force_palette_epoch": (
                None if self.force_palette_epoch is None else
                self.force_palette_epoch.summary(measurements)),
            "class_domains": [item.summary() for item in self.class_domains],
            "ambient_class_domain_ids": list(self.ambient_class_domain_ids),
            "event_pack_count": len(self.event_packs),
            "unique_event_pack_count": event_unique,
            "event_correlation_exact_count": exact_events,
            "event_correlation_ambiguous_count": (
                len(self.event_packs) - exact_events),
            "event_packs": [item.summary() for item in self.event_packs],
            "unique_pack_measurements": [
                item.summary() for item in self.unique_pack_measurements
            ],
            "proven_resident_combinations": [
                {"name": name, "domain_ids": list(domains)}
                for name, domains in self.proven_resident_combinations
            ],
            "missing_invariants": [
                item.summary() for item in self.missing_invariants
            ],
            "interpretation": {
                "event_packs": (
                    "reachability envelopes, not resident-set certificates"),
                "byte_measurements": (
                    "exact lossless FT812 backend output for each unique "
                    "logical cell set; no RAM_G placement is claimed"),
                "stage_union_resident_by_default": False,
                "descriptor_resource_cartesian_product": False,
                "force_p3d_palette_epochs_are_mutually_exclusive": (
                    self.force_palette_epoch is not None),
            },
        }

    def to_json(self) -> str:
        """Stable JSON used for deterministic translator binding."""
        return json.dumps(
            self.as_dict(), ensure_ascii=False, sort_keys=True,
            separators=(",", ":"),
        )

    @property
    def analysis_sha256(self) -> str:
        """Hash every semantic domain, byte measurement and blocker."""
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()


def _pairs_sha256(pairs: Iterable[DescriptorResourcePair]) -> str:
    rows: list[str] = []
    for pair in sorted(set(pairs)):
        descriptor = pair.descriptor
        banks = ",".join(
            f"{bank.kind}:{bank.value:02X}" for bank in pair.bank_keys)
        rows.append(
            f"{pair.resource_type:02X}:{descriptor.address:04X}:"
            f"{descriptor.dx}:{descriptor.dy}:{descriptor.code:04X}:"
            f"{descriptor.attribute:04X}:{descriptor.width}x{descriptor.height}:"
            f"{int(descriptor.flip_x)}{int(descriptor.flip_y)}:{banks}")
    return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()


def cells_for_pairs(
        pairs: Iterable[DescriptorResourcePair],
        ) -> tuple[SpriteCellRef, ...]:
    """Expand only existing related pairs, exactly as ``M72SpriteAtlas.draw``.

    The resource relation is already carried by ``pair.bank_keys``.  Keeping
    the loop inside each pair is the important non-Cartesian invariant.
    """
    cells: set[SpriteCellRef] = set()
    for pair in pairs:
        descriptor = pair.descriptor
        if descriptor.width not in (1, 2, 4, 8) or descriptor.height not in (
                1, 2, 4, 8):
            raise SpriteWorkingSetError(
                f"descriptor ${descriptor.address:04X} has invalid geometry")
        if not pair.bank_keys:
            raise SpriteWorkingSetError(
                f"descriptor ${descriptor.address:04X} has no Python bank")
        for bank in pair.bank_keys:
            for cell_x in range(descriptor.width):
                for cell_y in range(descriptor.height):
                    source_x = (descriptor.width - 1 - cell_x
                                if descriptor.flip_x else cell_x)
                    source_y = (descriptor.height - 1 - cell_y
                                if descriptor.flip_y else cell_y)
                    cells.add(SpriteCellRef(
                        bank=bank,
                        code=(descriptor.code + 8 * source_x + source_y) & 0x0FFF,
                        flip_x=descriptor.flip_x,
                        flip_y=descriptor.flip_y,
                    ))
    return tuple(sorted(cells))


def _pack_id(cells: Iterable[SpriteCellRef]) -> str:
    names = "\n".join(cell.stable_name for cell in sorted(set(cells)))
    return "sprite-" + hashlib.sha256(names.encode("utf-8")).hexdigest()[:24]


def _domain(
        domain_id: str, kind: str, pairs: Iterable[DescriptorResourcePair], *,
        stage: int | None = None, class_name: str | None = None,
        source_symbols: Iterable[str] = (),
        ) -> SpriteDomain:
    pair_tuple = tuple(sorted(set(pairs)))
    cells = cells_for_pairs(pair_tuple)
    return SpriteDomain(
        domain_id=domain_id,
        kind=kind,
        stage=stage,
        class_name=class_name,
        source_symbols=tuple(sorted(set(source_symbols))),
        pairs=pair_tuple,
        cells=cells,
        pair_sha256=_pairs_sha256(pair_tuple),
        pack_id=_pack_id(cells),
    )


def _validate_coverage(report: CoverageReport) -> None:
    if report.root_module != ACTIVE_ROOT_MODULE:
        raise SpriteWorkingSetError(
            f"coverage root is {report.root_module!r}, expected "
            f"{ACTIVE_ROOT_MODULE!r}")
    if report.unresolved_domains:
        raise SpriteWorkingSetError(
            "sprite coverage is unresolved: " +
            ", ".join(report.unresolved_domains))

    common_domains = dict(report.common_domain_pairs)
    if len(common_domains) != len(report.common_domain_pairs):
        raise SpriteWorkingSetError("duplicate common sprite domain")
    common_union = {
        pair for pairs in common_domains.values() for pair in pairs
    }
    if common_union != set(report.common_pairs):
        raise SpriteWorkingSetError(
            "common domain ownership does not equal common pair union")
    provenance = {item.domain: item for item in report.common_provenance}
    if set(provenance) != set(common_domains):
        raise SpriteWorkingSetError("common provenance ownership is incomplete")
    for name, pairs in common_domains.items():
        owner = provenance[name]
        if owner.pair_count != len(pairs):
            raise SpriteWorkingSetError(
                f"common domain {name!r} pair count changed")
        if owner.cell_count != len(cells_for_pairs(pairs)):
            raise SpriteWorkingSetError(
                f"common domain {name!r} cell count changed")

    stage_pairs = dict(report.per_stage_pairs)
    stages = {item.stage: item for item in report.stage_provenance}
    if set(stage_pairs) != set(range(1, 9)) or set(stages) != set(range(1, 9)):
        raise SpriteWorkingSetError("coverage does not own exactly stages 1..8")
    for stage in range(1, 9):
        source_pairs = tuple(stage_pairs[stage])
        proof = stages[stage]
        if proof.pair_count != len(source_pairs):
            raise SpriteWorkingSetError(
                f"stage {stage} pair count disagrees with provenance")
        if proof.cell_count != len(cells_for_pairs(source_pairs)):
            raise SpriteWorkingSetError(
                f"stage {stage} cell count disagrees with provenance")
        classes = {item.class_name: item for item in proof.class_coverage}
        if len(classes) != len(proof.class_coverage):
            raise SpriteWorkingSetError(f"stage {stage} repeats a class proof")
        class_union = {
            pair for item in classes.values() for pair in item.pairs
        }
        if class_union != set(source_pairs):
            raise SpriteWorkingSetError(
                f"stage {stage} class ownership does not equal stage pair union")
        if len(proof.events) != proof.event_count:
            raise SpriteWorkingSetError(
                f"stage {stage} event count disagrees with provenance")
        for event in proof.events:
            unknown = set(event.classes) - set(classes)
            if unknown:
                raise SpriteWorkingSetError(
                    f"stage {stage} event ${event.address:04X} owns unknown "
                    f"classes: {sorted(unknown)!r}")


def derive_sprite_domains(
        report: CoverageReport,
        ) -> tuple[
            tuple[SpriteDomain, ...], tuple[SpriteDomain, ...],
            tuple[EventReachabilityPack, ...], tuple[str, ...],
        ]:
    """Derive immutable common, class and deduplicable event cell domains."""
    _validate_coverage(report)
    common_provenance = {
        item.domain: item for item in report.common_provenance
    }
    common_domains = tuple(
        _domain(
            f"common:{name}", "common", pairs,
            source_symbols=common_provenance[name].source_symbols,
        )
        for name, pairs in report.common_domain_pairs
    )

    class_domains: list[SpriteDomain] = []
    events: list[EventReachabilityPack] = []
    ambient: list[str] = []
    for stage_proof in report.stage_provenance:
        by_class: dict[str, SpriteDomain] = {}
        for item in stage_proof.class_coverage:
            domain = _domain(
                f"stage:{stage_proof.stage}:class:{item.class_name}",
                "stage-class",
                item.pairs,
                stage=stage_proof.stage,
                class_name=item.class_name,
                source_symbols=(
                    *item.selector_sources,
                    *item.owned_descriptor_sinks,
                    *item.owned_resource_sinks,
                ),
            )
            class_domains.append(domain)
            by_class[item.class_name] = domain

        owners: dict[str, set[tuple[int, int]]] = {
            name: set() for name in by_class
        }
        for event in stage_proof.events:
            for class_name in event.classes:
                owners[class_name].add((event.handler, event.command))
        ambient.extend(
            by_class[name].domain_id
            for name, signatures in owners.items()
            if not signatures and by_class[name].cells
        )

        for event in stage_proof.events:
            domains = tuple(by_class[name] for name in event.classes)
            pair_tuple = tuple(sorted({
                pair for domain in domains for pair in domain.pairs
            }))
            cells = cells_for_pairs(pair_tuple)
            ambiguous = tuple(sorted(
                domain.class_name or ""
                for domain in domains
                if domain.cells and len(owners[domain.class_name or ""]) != 1
            ))
            events.append(EventReachabilityPack(
                stage=stage_proof.stage,
                address=event.address,
                threshold=event.threshold,
                command=event.command,
                handler=event.handler,
                classes=event.classes,
                class_domain_ids=tuple(domain.domain_id for domain in domains),
                pair_count=len(pair_tuple),
                pair_sha256=_pairs_sha256(pair_tuple),
                cell_count=len(cells),
                pack_id=_pack_id(cells),
                correlation_exact=not ambiguous,
                ambiguous_classes=ambiguous,
            ))

    return (
        tuple(common_domains),
        tuple(class_domains),
        tuple(events),
        tuple(sorted(ambient)),
    )


def _class_node(tree: ast.Module, name: str) -> ast.ClassDef:
    matches = [
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == name
    ]
    if len(matches) != 1:
        raise SpriteWorkingSetError(f"active source lost class {name}")
    return matches[0]


def _method_node(owner: ast.ClassDef, name: str) -> ast.FunctionDef:
    matches = [
        node for node in owner.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    if len(matches) != 1:
        raise SpriteWorkingSetError(
            f"active source lost {owner.name}.{name}")
    return matches[0]


def _literal_int(tree: ast.Module, name: str) -> int:
    matches: list[int] = []
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(isinstance(target, ast.Name) and target.id == name
                   for target in targets):
            continue
        try:
            value = ast.literal_eval(node.value)
        except (TypeError, ValueError):
            continue
        if isinstance(value, int):
            matches.append(value)
    if len(matches) != 1 or matches[0] <= 0:
        raise SpriteWorkingSetError(
            f"active source constant {name} is not one positive integer")
    return matches[0]


def _pool_slots(pool: ast.ClassDef) -> tuple[int, int]:
    assignments = [
        node for node in pool.body
        if isinstance(node, ast.Assign) and
        any(isinstance(target, ast.Name) and target.id == "SLOTS"
            for target in node.targets)
    ]
    if len(assignments) != 1:
        raise SpriteWorkingSetError("M72ObjectPool.SLOTS is not unique")
    value = assignments[0].value
    if not (
            isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and
            value.func.id == "tuple" and len(value.args) == 1 and
            isinstance(value.args[0], ast.Call) and
            isinstance(value.args[0].func, ast.Name) and
            value.args[0].func.id == "range"):
        raise SpriteWorkingSetError(
            "M72ObjectPool.SLOTS is no longer tuple(range(...))")
    try:
        arguments = [ast.literal_eval(arg) for arg in value.args[0].args]
        slots = tuple(range(*arguments))
    except (TypeError, ValueError) as exc:
        raise SpriteWorkingSetError(
            "M72ObjectPool.SLOTS range is not static") from exc
    if not slots:
        raise SpriteWorkingSetError("M72ObjectPool.SLOTS is empty")

    constructor = _method_node(pool, "__init__")
    sentinel_slices = [
        node.value.slice.lower.value
        for node in ast.walk(constructor)
        if (isinstance(node, ast.Assign) and
            any(isinstance(target, ast.Name) and target.id == "free"
                for target in node.targets) and
            isinstance(node.value, ast.Subscript) and
            ast.unparse(node.value.value) == "self.SLOTS" and
            isinstance(node.value.slice, ast.Slice) and
            isinstance(node.value.slice.lower, ast.Constant) and
            isinstance(node.value.slice.lower.value, int) and
            node.value.slice.upper is None and node.value.slice.step is None)
    ]
    if len(sentinel_slices) != 1:
        raise SpriteWorkingSetError(
            "fresh object-pool sentinel slice is not statically unique")
    sentinel_count = int(sentinel_slices[0])
    if not 0 <= sentinel_count < len(slots):
        raise SpriteWorkingSetError("invalid object-pool sentinel count")
    return len(slots), len(slots) - sentinel_count


def audit_active_scheduler(source_text: str) -> SchedulerFacts:
    """Verify the precise scheduler facts used by the blocker decision."""
    try:
        tree = ast.parse(source_text)
    except SyntaxError as exc:
        raise SpriteWorkingSetError(
            f"active enemies source is not parseable: {exc}") from exc
    pool_slots, allocatable = _pool_slots(_class_node(tree, "M72ObjectPool"))
    world = _class_node(tree, "M72EnemyWorld")
    update = _method_node(world, "update")
    dispatch_calls = [
        node for node in ast.walk(update)
        if (isinstance(node, ast.Call) and
            isinstance(node.func, ast.Attribute) and
            ast.unparse(node.func.value) == "self" and
            node.func.attr == "_dispatch")
    ]
    if len(dispatch_calls) != 1 or len(dispatch_calls[0].args) != 1 or (
            ast.unparse(dispatch_calls[0].args[0]) != "event"):
        raise SpriteWorkingSetError(
            "M72EnemyWorld.update no longer has one _dispatch(event) sink")

    dispatch_if = next((
        node for node in ast.walk(update)
        if isinstance(node, ast.If) and any(
            child is dispatch_calls[0] for child in ast.walk(node))
    ), None)
    if dispatch_if is None or not all((
            "event is not None" in ast.unparse(dispatch_if.test),
            "progression >= event.threshold" in ast.unparse(dispatch_if.test),
            any(isinstance(node, ast.AugAssign) and
                ast.unparse(node.target) == "self.event_pointer" and
                isinstance(node.op, ast.Add) and
                isinstance(node.value, ast.Constant) and node.value.value == 4
                for node in ast.walk(ast.Module(
                    body=dispatch_if.body, type_ignores=[]))),
    )):
        raise SpriteWorkingSetError(
            "event dispatcher guard/pointer advance changed")
    if any(
            isinstance(node, (ast.While, ast.For)) and
            any(child is dispatch_calls[0] for child in ast.walk(node))
            for node in ast.walk(update)):
        raise SpriteWorkingSetError(
            "event dispatch moved into an unmodelled loop")

    pending_extend = [
        node for node in ast.walk(update)
        if (isinstance(node, ast.Call) and
            ast.unparse(node.func) == "self.enemies.extend" and
            len(node.args) == 1 and ast.unparse(node.args[0]) == "self.pending")
    ]
    survivor_append = [
        node for node in ast.walk(update)
        if (isinstance(node, ast.Call) and
            ast.unparse(node.func) == "survivors.append" and
            len(node.args) == 1 and ast.unparse(node.args[0]) in (
                "enemy", "explosion"))
    ]
    survivor_commit = [
        node for node in ast.walk(update)
        if (isinstance(node, ast.Assign) and
            any(ast.unparse(target) == "self.enemies" for target in node.targets) and
            ast.unparse(node.value) == "survivors")
    ]
    if len(pending_extend) != 1 or not survivor_append or (
            len(survivor_commit) != 1):
        raise SpriteWorkingSetError(
            "live-object retention/pending insertion shape changed")

    return SchedulerFacts(
        source_sha256=hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
        object_pool_slots=pool_slots,
        initially_allocatable_slots=allocatable,
        maximum_event_dispatches_per_update=1,
        retains_live_objects_across_updates=True,
        appends_event_objects_to_existing_list=True,
        # CoverageReport has pair reachability but no creation/last-draw spans.
        event_specific_lifetime_bounds=False,
    )


def _parse_active_source(source_text: str, module: str) -> ast.Module:
    try:
        return ast.parse(source_text)
    except SyntaxError as exc:
        raise SpriteWorkingSetError(
            f"active {module} source is not parseable: {exc}") from exc


def _literal_node_int(node: ast.AST) -> int | None:
    try:
        value = ast.literal_eval(node)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, int) else None


def _audit_unique_resource_type_slot(enemies_tree: ast.Module) -> None:
    """Prove that one resource type cannot occupy two live palette slots."""
    manager = _class_node(enemies_tree, "M72ResourceManager")
    acquire = _method_node(manager, "acquire")
    release = _method_node(manager, "release")

    loops = [node for node in acquire.body if isinstance(node, ast.For)]
    if len(loops) != 1 or ast.unparse(loops[0].target) != "slot" or not (
            isinstance(loops[0].iter, ast.Call) and
            ast.unparse(loops[0].iter.func) == "range" and
            [_literal_node_int(arg) for arg in loops[0].iter.args] ==
            [15, -1, -1]):
        raise SpriteWorkingSetError(
            "M72ResourceManager acquire scan no longer proves one type slot")
    loop = loops[0]
    if len(loop.body) != 2 or not all(
            isinstance(node, ast.If) for node in loop.body):
        raise SpriteWorkingSetError(
            "M72ResourceManager acquire scan shape changed")
    match, remember_free = loop.body
    if ast.unparse(match.test) != "self.types[slot] == resource_type" or (
            [ast.unparse(node) for node in match.body] != [
                "self.refs[slot] = self.refs[slot] + 1 & 255",
                "return slot",
            ]):
        raise SpriteWorkingSetError(
            "M72ResourceManager no longer reuses an existing type slot")
    if ast.unparse(remember_free.test) != "self.types[slot] == 255" or (
            [ast.unparse(node) for node in remember_free.body] != [
                "free = slot",
            ]):
        raise SpriteWorkingSetError(
            "M72ResourceManager free-slot selection changed")
    tail = [ast.unparse(node) for node in acquire.body[2:]]
    if tail != [
            "if free < 0:\n    return 255",
            "self.types[free] = resource_type & 255",
            "self.refs[free] = 1",
            "return free",
            ]:
        raise SpriteWorkingSetError(
            "M72ResourceManager type-slot creation changed")
    if [ast.unparse(node) for node in release.body] != [
            ("if slot == 255 or not 0 <= slot < 16 or "
             "self.refs[slot] == 0:\n    return"),
            "self.refs[slot] -= 1",
            ("if self.refs[slot] == 0:\n"
             "    self.types[slot] = 255"),
            ]:
        raise SpriteWorkingSetError(
            "M72ResourceManager release/refcount invariant changed")

    # A write outside the manager would invalidate the uniqueness proof even
    # if acquire/release themselves remained unchanged.
    for node in ast.walk(enemies_tree):
        targets: list[ast.AST] = []
        if isinstance(node, ast.Assign):
            targets.extend(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets.append(node.target)
        elif isinstance(node, ast.AugAssign):
            targets.append(node.target)
        if not any(
                "resources.types[" in ast.unparse(target) or
                "resources.refs[" in ast.unparse(target) or
                ast.unparse(target).startswith("self.types[") or
                ast.unparse(target).startswith("self.refs[")
                for target in targets):
            continue
        if not (manager.lineno <= node.lineno <= (manager.end_lineno or 0)):
            raise SpriteWorkingSetError(
                "resource slot table is written outside M72ResourceManager")


def _audit_force_type3d_source(
        force_tree: ast.Module, game_tree: ast.Module,
        ) -> tuple[tuple[tuple[str, int], ...], tuple[str, ...]]:
    """Verify the state/ownership facts behind the Force palette epoch."""
    if _literal_int(force_tree, "FORCE_RESOURCE_TYPE") != 0x56:
        raise SpriteWorkingSetError("Force body resource type changed")
    force = _class_node(force_tree, "Force")
    expected_acquires = {
        "_fire_attached_type6": 1,
        "update_grid_segments": 1,
        "update_ray_segments": 1,
        "update_type6": 2,
    }
    acquire_counts: dict[str, int] = {}
    all_type3d_calls = 0
    for method_name, expected_count in expected_acquires.items():
        method = _method_node(force, method_name)
        calls = [
            node for node in ast.walk(method)
            if isinstance(node, ast.Call) and
            ast.unparse(node.func) == "acquire"
        ]
        arguments = [
            _literal_node_int(node.args[0])
            if len(node.args) == 1 else None
            for node in calls
        ]
        if len(calls) != expected_count or arguments != (
                [FORCE_P3D_RESOURCE_TYPE] * expected_count):
            raise SpriteWorkingSetError(
                f"Force.{method_name} acquire(0x3D) invariant changed")
        acquire_counts[f"Force.{method_name}"] = expected_count
        all_type3d_calls += expected_count
    discovered_type3d_calls = [
        node for node in ast.walk(force)
        if isinstance(node, ast.Call) and ast.unparse(node.func) == "acquire" and
        len(node.args) == 1 and
        _literal_node_int(node.args[0]) == FORCE_P3D_RESOURCE_TYPE
    ]
    if len(discovered_type3d_calls) != all_type3d_calls:
        raise SpriteWorkingSetError(
            "Force gained an unowned acquire(0x3D) site")

    draw = _method_node(force, "draw")
    draw_relations = sorted(
        (ast.unparse(node.args[2]), ast.unparse(node.args[3]))
        for node in ast.walk(draw)
        if isinstance(node, ast.Call) and ast.unparse(node.func) == "atlas.draw" and
        len(node.args) >= 4
    )
    expected_draw_relations = sorted((
        ("self.resource_slot", "FORCE_RESOURCE_TYPE"),
        ("projectile.resource_slot", "2"),
        ("segment.resource_slot", "61"),
        ("segment.resource_slot", "61"),
        ("beam.resource_slot", "61"),
        ("dart.resource_slot", "61"),
    ))
    if draw_relations != expected_draw_relations:
        raise SpriteWorkingSetError(
            "Force.draw palette/resource relation changed")

    sync_level = _method_node(force, "sync_level")
    level_zero = next((
        node for node in ast.walk(sync_level)
        if isinstance(node, ast.If) and
        ast.unparse(node.test) == "handler == 9858"
    ), None)
    child_fields = {
        "projectiles", "ray_segments", "grid_segments", "beams", "darts",
    }
    if level_zero is None:
        raise SpriteWorkingSetError("Force level-zero cleanup branch changed")
    cleared = {
        ast.unparse(node.func.value).removeprefix("self.")
        for node in ast.walk(ast.Module(body=level_zero.body, type_ignores=[]))
        if isinstance(node, ast.Call) and
        isinstance(node.func, ast.Attribute) and node.func.attr == "clear"
    }
    released = {
        ast.unparse(node.iter.func.value).removeprefix("self.")
        for node in ast.walk(ast.Module(body=level_zero.body, type_ignores=[]))
        if isinstance(node, ast.For) and isinstance(node.iter, ast.Call) and
        isinstance(node.iter.func, ast.Attribute) and
        node.iter.func.attr == "values" and any(
            isinstance(child, ast.Call) and
            ast.unparse(child.func) == "release" and
            len(child.args) == 1 and
            ast.unparse(child.args[0]).endswith(".resource_slot")
            for child in ast.walk(node))
    }
    all_clears = {
        ast.unparse(node.func.value).removeprefix("self.")
        for node in ast.walk(force)
        if isinstance(node, ast.Call) and
        isinstance(node.func, ast.Attribute) and node.func.attr == "clear" and
        ast.unparse(node.func.value).startswith("self.")
    }
    if cleared != child_fields or released != child_fields or (
            all_clears != child_fields):
        raise SpriteWorkingSetError(
            "Force child lifetime cleanup is no longer level-zero-only")

    for method_name, field, local in (
            ("_release_ray", "ray_segments", "segment"),
            ("_release_grid", "grid_segments", "segment"),
            ("_release_beam", "beams", "beam"),
            ("_release_dart", "darts", "dart"),
            ):
        method_text = ast.unparse(_method_node(force, method_name))
        if (f"{local} = self.{field}.pop(slot, None)" not in method_text or
                f"release({local}.resource_slot)" not in method_text):
            raise SpriteWorkingSetError(
                f"Force.{method_name} resource ownership changed")

    game = _class_node(game_tree, "Game")
    update = _method_node(game, "update")
    update_names = (
        "fire_matrix", "update_projectiles", "update_ray_segments",
        "update_grid_segments", "update_type6",
    )
    ordered_calls: list[tuple[int, str]] = []
    for name in update_names:
        calls = [
            node for node in ast.walk(update)
            if isinstance(node, ast.Call) and
            ast.unparse(node.func) == f"self.force.{name}"
        ]
        if len(calls) != 1:
            raise SpriteWorkingSetError(
                f"Game.update lost unique Force.{name} call")
        ordered_calls.append((calls[0].lineno, name))
    if tuple(name for _line, name in sorted(ordered_calls)) != update_names:
        raise SpriteWorkingSetError("Game Force update order changed")
    render = _method_node(game, "render")
    if sum(
            isinstance(node, ast.Call) and
            ast.unparse(node.func) == "self.force.draw"
            for node in ast.walk(render)) != 1:
        raise SpriteWorkingSetError("Game.render lost Force.draw")
    death = _method_node(game, "_begin_player_death")
    death_sync = [
        node for node in ast.walk(death)
        if isinstance(node, ast.Call) and
        ast.unparse(node.func) == "self.force.sync_level"
    ]
    if len(death_sync) != 1 or not death_sync[0].args or (
            _literal_node_int(death_sync[0].args[0]) != 0):
        raise SpriteWorkingSetError(
            "player death no longer clears Force before render")

    return tuple(sorted(acquire_counts.items())), update_names


def audit_force_palette_epochs(
        force_source_text: str, game_source_text: str,
        enemies_source_text: str,
        common_domain_pairs: Mapping[
            str, tuple[DescriptorResourcePair, ...]],
        ) -> ForcePaletteEpochProof:
    """Build sixteen exclusive P3D candidates from active source evidence."""
    force_tree = _parse_active_source(force_source_text, "rtype_port.force")
    game_tree = _parse_active_source(game_source_text, "rtype_port.game")
    enemies_tree = _parse_active_source(
        enemies_source_text, "rtype_port.enemies")
    _audit_unique_resource_type_slot(enemies_tree)
    acquire_sites, update_order = _audit_force_type3d_source(
        force_tree, game_tree)

    expected_counts = {
        "force_body": 31,
        "force_projectiles": 5,
        **dict(FORCE_P3D_EXPECTED_PAIR_COUNTS),
    }
    missing = set(expected_counts) - set(common_domain_pairs)
    if missing:
        raise SpriteWorkingSetError(
            "Force palette proof is missing common domains: " +
            ", ".join(sorted(missing)))
    actual_counts = {
        name: len(common_domain_pairs[name]) for name in expected_counts
    }
    if actual_counts != expected_counts:
        raise SpriteWorkingSetError(
            f"Force state-domain pair counts changed: {actual_counts!r}")

    typed_expectations = {
        "force_body": (0x56, PythonBankKey("typed-resource", 0x56)),
        "force_projectiles": (0x02, PythonBankKey("typed-resource", 0x02)),
    }
    for name, (resource_type, bank) in typed_expectations.items():
        if any(
                pair.resource_type != resource_type or pair.bank_keys != (bank,)
                for pair in common_domain_pairs[name]):
            raise SpriteWorkingSetError(
                f"{name} descriptor/palette/resource relation changed")

    fallback_banks = tuple(
        PythonBankKey("palette-fallback", slot) for slot in range(16))
    type3d_pairs: list[DescriptorResourcePair] = []
    for name in FORCE_P3D_DOMAIN_NAMES:
        pairs = common_domain_pairs[name]
        if any(
                pair.resource_type != FORCE_P3D_RESOURCE_TYPE or
                pair.bank_keys != fallback_banks
                for pair in pairs):
            raise SpriteWorkingSetError(
                f"{name} is no longer the exact 16-way P3D fallback relation")
        type3d_pairs.extend(pairs)
    owned_pairs = set(type3d_pairs)
    if len(owned_pairs) != sum(dict(FORCE_P3D_EXPECTED_PAIR_COUNTS).values()):
        raise SpriteWorkingSetError(
            "Force type-3D domains overlap or lost descriptor ownership")
    leaked = [
        name for name, pairs in common_domain_pairs.items()
        if name not in FORCE_P3D_DOMAIN_NAMES and any(
            pair.resource_type == FORCE_P3D_RESOURCE_TYPE for pair in pairs)
    ]
    if leaked:
        raise SpriteWorkingSetError(
            "resource type 0x3D escaped the Force epoch domains: " +
            ", ".join(sorted(leaked)))

    source_domain_ids = tuple(
        f"common:{name}" for name in FORCE_P3D_DOMAIN_NAMES)
    candidates: list[ForcePaletteEpochCandidate] = []
    for slot in range(16):
        bank = PythonBankKey("palette-fallback", slot)
        narrowed = tuple(sorted(
            DescriptorResourcePair(
                resource_type=pair.resource_type,
                descriptor=pair.descriptor,
                bank_keys=(bank,),
            )
            for pair in owned_pairs
        ))
        cells = cells_for_pairs(narrowed)
        candidates.append(ForcePaletteEpochCandidate(
            palette_slot=slot,
            domain_id=f"force:p3d-epoch:{slot:02X}",
            source_domain_ids=source_domain_ids,
            pair_count=len(narrowed),
            pair_sha256=_pairs_sha256(narrowed),
            cells=cells,
            pack_id=_pack_id(cells),
        ))

    source_hashes = tuple(sorted((
        ("rtype_port.enemies", hashlib.sha256(
            enemies_source_text.encode("utf-8")).hexdigest()),
        ("rtype_port.force", hashlib.sha256(
            force_source_text.encode("utf-8")).hexdigest()),
        ("rtype_port.game", hashlib.sha256(
            game_source_text.encode("utf-8")).hexdigest()),
    )))
    return ForcePaletteEpochProof(
        source_hashes=source_hashes,
        resource_type=FORCE_P3D_RESOURCE_TYPE,
        acquire_site_counts=acquire_sites,
        update_order=update_order,
        state_domain_pair_counts=tuple(sorted(actual_counts.items())),
        coexisting_domain_ids=tuple(
            f"common:{name}" for name in FORCE_COEXISTING_DOMAIN_NAMES),
        epoch_source_domain_ids=source_domain_ids,
        candidates=tuple(candidates),
    )


def _bank_source(bank: PythonBankKey) -> CellSourceKey:
    if bank.kind == "typed-resource" and 0 <= bank.value <= 0xFF:
        return CellSourceKey("sprite", f"type{bank.value:02X}")
    if bank.kind == "palette-fallback" and 0 <= bank.value <= 0x0F:
        return CellSourceKey("sprite", "palette-fallback", bank.value)
    raise SpriteWorkingSetError(f"unknown active Python bank {bank!r}")


def _bank_path(root: Path, bank: PythonBankKey) -> Path:
    arcade = root / "Assets" / "Converted" / "Arcade"
    if bank.kind == "typed-resource":
        return arcade / "ResourceHQ" / (
            f"RTYPE_SPRITES_TYPE{bank.value:02X}_HQ_ARGB4444.bin")
    if bank.kind == "palette-fallback":
        return arcade / "FullHQ" / (
            f"RTYPE_SPRITES_PAL{bank.value:02X}_HQ_ARGB4444.bin")
    raise SpriteWorkingSetError(f"unknown active Python bank {bank!r}")


def _measure_packs(
        root: Path, source_text: str,
        pack_cells: Mapping[str, tuple[SpriteCellRef, ...]],
        pack_owners: Mapping[str, set[str]],
        ) -> tuple[FT812PackMeasurement, ...]:
    tree = ast.parse(source_text)
    width = _literal_int(tree, "SPRITE_CELL_W")
    height = _literal_int(tree, "SPRITE_CELL_H")
    cell_bytes = width * height * 2
    all_banks = sorted({
        cell.bank for cells in pack_cells.values() for cell in cells
    })
    bank_specs: dict[PythonBankKey, CellBankSpec] = {}
    for bank in all_banks:
        path = _bank_path(root, bank)
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise SpriteWorkingSetError(
                f"active Python sprite bank is unavailable: {path}: {exc}") from exc
        if size <= 0 or size % cell_bytes:
            raise SpriteWorkingSetError(
                f"active Python sprite bank has invalid size {size}: {path}")
        bank_specs[bank] = CellBankSpec(
            _bank_source(bank), path, width, height, size // cell_bytes)

    measurements: list[FT812PackMeasurement] = []
    empty_sha = hashlib.sha256(b"").hexdigest()
    for pack_id in sorted(pack_cells):
        cells = pack_cells[pack_id]
        owners = tuple(sorted(pack_owners[pack_id]))
        if not cells:
            measurements.append(FT812PackMeasurement(
                pack_id=pack_id,
                cell_count=0,
                unique_cells=0,
                raw_argb4444_bytes=0,
                ft812_bytes=0,
                saved_bytes=0,
                palette_count=0,
                argb4_entries=0,
                paletted4444_entries=0,
                blob_sha256=empty_sha,
                owner_ids=owners,
            ))
            continue
        keys = tuple(CellKey(
            _bank_source(cell.bank), cell.code, cell.flip_x, cell.flip_y)
            for cell in cells)
        banks = tuple(bank_specs[bank]
                      for bank in sorted({cell.bank for cell in cells}))
        raw_ceiling = len(cells) * cell_bytes
        pack = compile_ft812_cell_assets(
            keys,
            banks,
            FT812AssetPackBudget(
                max_logical_entries=len(cells),
                max_unique_cells=len(cells),
                max_palettes=len(cells),
                # A palette per cell plus alignment is a strict construction
                # ceiling; this is sizing, not a resident RAM_G allowance.
                max_bytes=raw_ceiling + len(cells) * 516,
                alignment=4,
            ),
            project_root=root,
        )
        actual = {entry.key for entry in pack.entries}
        if actual != set(keys):
            raise SpriteWorkingSetError(
                f"FT812 backend lost logical cells from {pack_id}")
        format_counts = {"ARGB4": 0, "PALETTED4444": 0}
        for entry in pack.entries:
            format_counts[entry.pixel_format] += 1
        measurements.append(FT812PackMeasurement(
            pack_id=pack_id,
            cell_count=len(cells),
            unique_cells=pack.unique_cells,
            raw_argb4444_bytes=pack.raw_argb4444_bytes,
            ft812_bytes=len(pack.data),
            saved_bytes=pack.raw_argb4444_bytes - len(pack.data),
            palette_count=len(pack.palettes),
            argb4_entries=format_counts["ARGB4"],
            paletted4444_entries=format_counts["PALETTED4444"],
            blob_sha256=pack.sha256,
            owner_ids=owners,
        ))
    return tuple(measurements)


def _source_text_for_module(
        root: Path, report: CoverageReport, module: str,
        ) -> str:
    if not module.startswith("rtype_port."):
        raise SpriteWorkingSetError(
            f"active source module is outside rtype_port: {module!r}")
    path = (root / "Source" / "Python" /
            Path(*module.split(".")).with_suffix(".py"))
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SpriteWorkingSetError(
            f"active {module} source is unavailable: {exc}") from exc
    expected = dict(report.source_hashes).get(module)
    actual = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if expected is None or actual != expected:
        raise SpriteWorkingSetError(
            f"CoverageReport is stale for active {module}")
    return text


def _source_text_for_report(root: Path, report: CoverageReport) -> str:
    """Compatibility wrapper for the scheduler/asset source."""
    return _source_text_for_module(root, report, "rtype_port.enemies")


def plan_sprite_working_sets(
        report: CoverageReport, project_root: Path | str | None = None,
        ) -> WorkingSetPlan:
    """Build and measure the strongest plan justified by ``CoverageReport``.

    The current report intentionally has no lifetime intervals.  Consequently
    this function returns a structured blocked plan, not a stage-union or
    per-event resident fiction.
    """
    root = (Path(__file__).resolve().parents[3] if project_root is None
            else Path(project_root)).resolve()
    common, classes, events, ambient = derive_sprite_domains(report)
    source_text = _source_text_for_report(root, report)
    scheduler = audit_active_scheduler(source_text)

    common_pair_map = dict(report.common_domain_pairs)
    present_force_domains = (
        set(common_pair_map) & set(FORCE_COEXISTING_DOMAIN_NAMES))
    force_palette_epoch: ForcePaletteEpochProof | None = None
    if present_force_domains:
        if present_force_domains != set(FORCE_COEXISTING_DOMAIN_NAMES):
            raise SpriteWorkingSetError(
                "CoverageReport has an incomplete Force state-domain family")
        if any(
                pair.resource_type == FORCE_P3D_RESOURCE_TYPE
                for _stage, pairs in report.per_stage_pairs for pair in pairs):
            raise SpriteWorkingSetError(
                "stage sprite coverage uses resource type 0x3D outside the "
                "proved Force palette epoch")
        force_palette_epoch = audit_force_palette_epochs(
            _source_text_for_module(root, report, "rtype_port.force"),
            _source_text_for_module(root, report, "rtype_port.game"),
            source_text,
            common_pair_map,
        )

    pack_cells: dict[str, tuple[SpriteCellRef, ...]] = {}
    pack_owners: dict[str, set[str]] = {}

    def own(pack_id: str, cells: tuple[SpriteCellRef, ...], owner: str) -> None:
        previous = pack_cells.setdefault(pack_id, cells)
        if previous != cells:
            raise SpriteWorkingSetError(
                f"logical pack digest collision for {pack_id}")
        pack_owners.setdefault(pack_id, set()).add(owner)

    replaced_common_ids = (
        set(force_palette_epoch.epoch_source_domain_ids)
        if force_palette_epoch is not None else set())
    for domain in (*common, *classes):
        if domain.domain_id in replaced_common_ids:
            # The coverage domain is a 16-way alternative relation, not a
            # simultaneously resident pack.  Its exact replacements are the
            # sixteen source-proved epoch candidates below.
            continue
        own(domain.pack_id, domain.cells, domain.domain_id)
    if force_palette_epoch is not None:
        for candidate in force_palette_epoch.candidates:
            own(candidate.pack_id, candidate.cells, candidate.domain_id)
    # Reconstruct event cells only from its already-related class domains.
    class_lookup = {domain.domain_id: domain for domain in classes}
    for event in events:
        cells = tuple(sorted({
            cell
            for domain_id in event.class_domain_ids
            for cell in class_lookup[domain_id].cells
        }))
        if _pack_id(cells) != event.pack_id or len(cells) != event.cell_count:
            raise SpriteWorkingSetError(
                f"event pack reconstruction changed at {event.event_id}")
        own(event.pack_id, cells, event.event_id)

    measurements = _measure_packs(
        root, source_text, pack_cells, pack_owners)

    ambiguous_events = tuple(
        event.event_id for event in events if not event.correlation_exact
    )
    invariants: list[MissingInvariant] = []
    if ambiguous_events:
        invariants.append(MissingInvariant(
            code="PZSW101",
            scope="event-pair-correlation",
            required_fact=(
                "per event address, preserve constructor/path selectors as "
                "an exact event -> class -> descriptor/resource relation"),
            reason=(
                f"{len(ambiguous_events)} events reuse rendered classes across "
                "multiple handler/command signatures; stage-class pairs are "
                "exact but cannot be narrowed to those events from this report"),
            source_symbols=(
                "CoverageReport.stage_provenance.events",
                "CoverageReport.stage_provenance.class_coverage",
            ),
        ))
    invariants.append(MissingInvariant(
        code="PZSW102",
        scope="stage-object-lifetimes",
        required_fact=(
            "for every event root and spawned descendant, prove creation and "
            "last-draw bounds in one shared frame/progression coordinate, "
            "including cleanup, destruction and object-pool allocation failure"),
        reason=(
            "the scheduler retains live objects while dispatching later events; "
            "CoverageReport contains reachability but no lifetime intervals, so "
            "no cross-event class combination is proven exhaustive"),
        source_symbols=(
            "rtype_port.enemies.M72EnemyWorld.update",
            "rtype_port.enemies.M72PendingList.append",
            "rtype_port.enemies.M72ObjectPool",
        ),
    ))
    invariants.append(MissingInvariant(
        code="PZSW103",
        scope="ambient-and-common-concurrency",
        required_fact=(
            "prove maximum live overlap for player death, shots, the already-"
            "coexisting Force state domains, Bits, ExplosionEffect and "
            "EnemyProjectile against stage event objects"),
        reason=(
            "the Force type-3D palette epoch is now exact, but Force families "
            "can coexist and generic explosion/projectile classes have no owning "
            "ROM event; their cross-domain lifetime overlap remains unproved"),
        source_symbols=(
            "CoverageReport.common_domain_pairs",
            "CoverageReport.stage_provenance.class_coverage",
            "rtype_port.force.Force",
            "rtype_port.game.Game",
        ),
    ))
    invariants.append(MissingInvariant(
        code="PZSW104",
        scope="load-transition-safety",
        required_fact=(
            "for every proven live-state transition, establish the upload-before-"
            "first-draw and eviction-after-last-draw ordering and the available "
            "RAM_G budget"),
        reason=(
            "exact independent/epoch pack byte costs do not by themselves "
            "establish a safe streaming schedule, including same-frame Force "
            "beam/dart first draws"),
        source_symbols=(
            "pyz80_compiler.ft812_assets.compile_ft812_cell_assets",
        ),
    ))

    return WorkingSetPlan(
        root_module=report.root_module,
        coverage_source_hashes=report.source_hashes,
        rom_sha256=report.rom_sha256,
        scheduler=scheduler,
        common_domains=common,
        class_domains=classes,
        event_packs=events,
        ambient_class_domain_ids=ambient,
        unique_pack_measurements=measurements,
        # No non-trivial simultaneous combination is encoded by CoverageReport.
        proven_resident_combinations=(),
        missing_invariants=tuple(sorted(invariants)),
        force_palette_epoch=force_palette_epoch,
    )


def analyze_sprite_working_sets(
        project_root: Path | str | None = None,
        ) -> WorkingSetPlan:
    """Run active sprite coverage once, then build its working-set plan."""
    root = (Path(__file__).resolve().parents[3] if project_root is None
            else Path(project_root)).resolve()
    return plan_sprite_working_sets(analyze_sprite_coverage(root), root)


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Analyze active Python sprite working sets")
    parser.add_argument("--project-root", type=Path, default=None)
    parser.add_argument(
        "--require-ready", action="store_true",
        help="return failure while lifetime/residency proof is incomplete")
    arguments = parser.parse_args(argv)
    try:
        plan = analyze_sprite_working_sets(arguments.project_root)
    except (SpriteCoverageError, SpriteWorkingSetError,
            AssetCompileError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(plan.as_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return int(arguments.require_ready and not plan.ready)


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "EventReachabilityPack",
    "FT812PackMeasurement",
    "FORCE_PALETTE_EPOCH_FORMAT",
    "ForcePaletteEpochCandidate",
    "ForcePaletteEpochProof",
    "MissingInvariant",
    "SPRITE_WORKING_SET_PLAN_FORMAT",
    "SchedulerFacts",
    "SpriteCellRef",
    "SpriteDomain",
    "SpriteWorkingSetError",
    "WorkingSetPlan",
    "analyze_sprite_working_sets",
    "audit_active_scheduler",
    "audit_force_palette_epochs",
    "cells_for_pairs",
    "derive_sprite_domains",
    "plan_sprite_working_sets",
]
