"""Source-derived FT812 sprite-fragment sizing envelope.

This stage deliberately stops before publication/integration.  It joins the
proved active-Python frame-record bound to ``SpriteDrawPlanIR``, the exact
source/ROM sprite coverage relation, and the generated HQT3/CMD_APPEND pack.
Only a complete join may produce weighted RAM_DL and raster upper bounds.

The object bound is weighted without multiplying the whole-frame record
ceiling by one global template maximum.  Every pool slot receives the worst
unbounded-class cost; finite class instance bounds add only their positive
premium over that baseline.  One-shot transient composition is accounted for
separately.  Dynamic coordinates are intentionally not guessed: the raster
result extends each template's proved peak to every one of the 768 physical
lines, which is conservative for an unrestricted anchor domain.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import struct
from typing import Any, Iterable, Mapping, Sequence

from .draw_plan import SpriteDrawPlanIR, compile_active_enemy_draw_plan
from .ft812_budget import FT812Timing, analyze_display_list
from .sprite_coverage import CoverageReport, analyze_sprite_coverage


FRAME_SPRITE_FRAGMENT_ENVELOPE_FORMAT = (
    "pyz80.frame-sprite-fragment-envelope.v4")
FRAME_RECORD_BOUND_FORMAT = "pyz80.frame-draw-record-bound.v2"
DEFAULT_CHUNK_CAPACITY = 128
MAX_CHUNK_CAPACITY = 128
DEFAULT_RASTER_HEIGHT = 768
BATCH_RECORD_EXPANDED_OVERHEAD_WORDS = 2
BATCH_PREFIX_WORDS = 10
BATCH_SUFFIX_WORDS = 3

_HQT3_HEADER = struct.Struct("<4sBBHIII")
_HQT3_RECORD = struct.Struct("<HBBHhhHBBHH")
_HQT3_STATE = struct.Struct("<II")
_HQT3_CELL = struct.Struct("<IhhB")
_DL_BITMAP_SOURCE = 0x01000000
_DL_PALETTE_SOURCE = 0x2A000000
_DL_VERTEX2F = 0x40000000
_PALETTED4444 = 15


__all__ = [
    "DEFAULT_CHUNK_CAPACITY",
    "DEFAULT_RASTER_HEIGHT",
    "FRAME_SPRITE_FRAGMENT_ENVELOPE_FORMAT",
    "FrameSpriteFragmentEnvelopeError",
    "FrameSpriteFragmentEnvelopeReport",
    "TemplateMetric",
    "analyze_frame_sprite_fragment_envelope",
    "build_frame_sprite_fragment_envelope",
]


class FrameSpriteFragmentEnvelopeError(ValueError):
    """Stable fail-closed diagnostic for malformed or optimistic inputs."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


@dataclass(frozen=True)
class TemplateMetric:
    bank_key: int
    descriptor_address: int
    append_words: int
    raster_peak_cycles: int
    cell_count: int
    phase_word_counts: tuple[int, ...] = ()

    @property
    def key(self) -> tuple[int, int]:
        return self.bank_key, self.descriptor_address

    def as_dict(self) -> dict[str, object]:
        return {
            "bank_key": self.bank_key,
            "descriptor_address": self.descriptor_address,
            "append_words": self.append_words,
            "raster_peak_cycles": self.raster_peak_cycles,
            "cell_count": self.cell_count,
            "phase_word_counts": list(self.phase_word_counts),
        }


@dataclass(frozen=True)
class FrameSpriteFragmentEnvelopeReport:
    payload: Mapping[str, object]

    @property
    def status(self) -> str:
        return str(self.payload["status"])

    @property
    def proof_complete(self) -> bool:
        return bool(self.payload["proof_complete"])

    def as_dict(self) -> dict[str, object]:
        return json.loads(json.dumps(self.payload, sort_keys=True))

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(
            self.payload, ensure_ascii=False, sort_keys=True, indent=indent,
        ) + "\n"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def _domain_hash(keys: Iterable[tuple[int, int]]) -> str:
    return _sha256(_json_bytes([[a, b] for a, b in sorted(set(keys))]))


def _require_int(value: object, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise FrameSpriteFragmentEnvelopeError(
            "PZFSFE001", f"{label} is not an integer >= {minimum}")
    return value


def _action_ordinals(draw_plan: SpriteDrawPlanIR | Mapping[str, object]
                     ) -> tuple[int, ...]:
    if isinstance(draw_plan, SpriteDrawPlanIR):
        values = tuple(item.ordinal for item in draw_plan.actions)
    else:
        raw = draw_plan.get("actions")
        if not isinstance(raw, Sequence):
            raise FrameSpriteFragmentEnvelopeError(
                "PZFSFE003", "draw plan has no action sequence")
        values = tuple(_require_int(item["ordinal"], "action ordinal")
                       for item in raw if isinstance(item, Mapping))
        if len(values) != len(raw):
            raise FrameSpriteFragmentEnvelopeError(
                "PZFSFE003", "draw plan action is not a mapping")
    if len(values) != len(set(values)) or values != tuple(range(len(values))):
        raise FrameSpriteFragmentEnvelopeError(
            "PZFSFE003", f"draw action ordinals are not dense: {values!r}")
    return values


def _finite_instance_bounds(record_bound: Mapping[str, object]
                            ) -> dict[str, int]:
    try:
        raw = record_bound["abstract_reachability"]
        raw = raw["spawn_reachability"]  # type: ignore[index]
        raw = raw["finite_class_instance_upper_bounds"]  # type: ignore[index]
    except (KeyError, TypeError) as exc:
        raise FrameSpriteFragmentEnvelopeError(
            "PZFSFE001", "record bound lost finite class bounds") from exc
    if not isinstance(raw, Mapping):
        raise FrameSpriteFragmentEnvelopeError(
            "PZFSFE001", "finite class bounds are not a mapping")
    return {
        str(name): _require_int(value, f"finite bound for {name}")
        for name, value in raw.items()
    }


def _record_composition(record_bound: Mapping[str, object]
                        ) -> tuple[int, int, int, int, dict[str, int]]:
    if record_bound.get("format") != FRAME_RECORD_BOUND_FORMAT:
        raise FrameSpriteFragmentEnvelopeError(
            "PZFSFE001", "unsupported frame-record-bound format")
    if (record_bound.get("proof_complete") is not True or
            record_bound.get("can_certify_frame_budget") is not True or
            record_bound.get("bound_kind") != "conservative_upper_bound"):
        raise FrameSpriteFragmentEnvelopeError(
            "PZFSFE001", "record bound is not a certified conservative bound")
    total = _require_int(
        record_bound.get("certified_frame_max_records"),
        "certified frame max records")
    try:
        abstract = record_bound["abstract_reachability"]
        objects = abstract["object_records"]  # type: ignore[index]
        transients = abstract["transient_sprites"]  # type: ignore[index]
        pool = record_bound["object_pool"]
        object_total = _require_int(
            objects["finite_upper_bound"], "object record bound")  # type: ignore[index]
        transient_total = _require_int(
            transients["finite_per_frame_upper_bound"],  # type: ignore[index]
            "transient record bound")
        pool_count = _require_int(
            pool["allocatable_record_count"], "pool record count")  # type: ignore[index]
    except (KeyError, TypeError) as exc:
        raise FrameSpriteFragmentEnvelopeError(
            "PZFSFE001", "record bound lost composition witnesses") from exc
    if object_total + transient_total != total:
        raise FrameSpriteFragmentEnvelopeError(
            "PZFSFE006", "object + transient records do not equal frame bound")
    return total, object_total, transient_total, pool_count, \
        _finite_instance_bounds(record_bound)


def _class_rows(record_bound: Mapping[str, object]
                ) -> tuple[dict[str, object], ...]:
    try:
        rows = record_bound["object_multiplicity"]["classes"]  # type: ignore[index]
    except (KeyError, TypeError) as exc:
        raise FrameSpriteFragmentEnvelopeError(
            "PZFSFE001", "record bound lost class multiplicities") from exc
    if not isinstance(rows, Sequence):
        raise FrameSpriteFragmentEnvelopeError(
            "PZFSFE001", "class multiplicities are not a sequence")
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise FrameSpriteFragmentEnvelopeError(
                "PZFSFE001", "class multiplicity row is malformed")
        name = str(raw.get("class_name"))
        if not name or name in seen:
            raise FrameSpriteFragmentEnvelopeError(
                "PZFSFE001", f"duplicate/empty class row {name!r}")
        seen.add(name)
        actions_raw = raw.get("action_ordinals")
        if not isinstance(actions_raw, Sequence):
            raise FrameSpriteFragmentEnvelopeError(
                "PZFSFE003", f"{name} has no action ordinal sequence")
        actions = tuple(_require_int(value, f"{name} action ordinal")
                        for value in actions_raw)
        count = _require_int(
            raw.get("max_records_per_object"), f"{name} record count")
        if len(actions) != count or len(set(actions)) != len(actions):
            raise FrameSpriteFragmentEnvelopeError(
                "PZFSFE006",
                f"{name} action witness does not equal its record count")
        result.append({
            "class_name": name,
            "action_ordinals": actions,
            "max_records_per_object": count,
            "witness_fields": raw.get("witness_fields", {}),
        })
    return tuple(result)


def _transient_composition(record_bound: Mapping[str, object]
                           ) -> dict[str, int]:
    try:
        raw = record_bound["abstract_reachability"]["transient_sprites"] \
            ["lifetime_emission_contributions"]  # type: ignore[index]
    except (KeyError, TypeError) as exc:
        raise FrameSpriteFragmentEnvelopeError(
            "PZFSFE001", "record bound lost transient composition") from exc
    if not isinstance(raw, Mapping):
        raise FrameSpriteFragmentEnvelopeError(
            "PZFSFE001", "transient composition is not a mapping")
    return {str(name): _require_int(value, f"transient {name} count")
            for name, value in raw.items()}


def _metric_choice(
        keys: Sequence[tuple[int, int]],
        metrics: Mapping[tuple[int, int], TemplateMetric],
        field: str,
        ) -> tuple[int, tuple[int, int]]:
    candidates = [(int(getattr(metrics[key], field)), key) for key in keys]
    return max(candidates, key=lambda item: (item[0], item[1]))


def _validate_claims(
        claims: Mapping[str, object] | None, *, append_words: int,
        max_chunks: int, raster: Sequence[int], expanded_words: int,
        ) -> None:
    if claims is None:
        return
    scalar = {
        "max_cmd_append_expanded_words": append_words,
        "max_chunks": max_chunks,
        "max_fragment_expanded_dl_words": expanded_words,
    }
    for name, proved in scalar.items():
        if name not in claims:
            continue
        claimed = _require_int(claims[name], f"claimed {name}")
        if claimed < proved:
            raise FrameSpriteFragmentEnvelopeError(
                "PZFSFE007", f"optimistic {name}: {claimed} < {proved}")
    if "raster_cycles_by_line" in claims:
        claimed_raster = claims["raster_cycles_by_line"]
        if (not isinstance(claimed_raster, Sequence) or
                len(claimed_raster) != len(raster)):
            raise FrameSpriteFragmentEnvelopeError(
                "PZFSFE007", "claimed raster envelope has wrong height")
        for line, (claimed_raw, proved) in enumerate(zip(claimed_raster, raster)):
            claimed = _require_int(claimed_raw, f"claimed raster line {line}")
            if claimed < proved:
                raise FrameSpriteFragmentEnvelopeError(
                    "PZFSFE007",
                    f"optimistic raster line {line}: {claimed} < {proved}")


def build_frame_sprite_fragment_envelope(
        record_bound: Mapping[str, object],
        draw_plan: SpriteDrawPlanIR | Mapping[str, object],
        class_template_keys: Mapping[str, Sequence[tuple[int, int]]],
        template_metrics: Mapping[tuple[int, int], TemplateMetric], *,
        transient_template_keys: Mapping[str, Sequence[tuple[int, int]]] | None = None,
        nonrendering_classes: Iterable[str] = (),
        chunk_capacity: int = DEFAULT_CHUNK_CAPACITY,
        raster_height: int = DEFAULT_RASTER_HEIGHT,
        claims: Mapping[str, object] | None = None,
        input_bindings: Mapping[str, object] | None = None,
        ) -> FrameSpriteFragmentEnvelopeReport:
    """Build a weighted proof from already source-derived finite relations.

    Missing reachable template identities are returned as explicit blockers,
    never replaced by a geometry estimate.  Malformed action/count relations
    and optimistic caller claims are hard errors.
    """

    if (isinstance(chunk_capacity, bool) or
            not isinstance(chunk_capacity, int) or
            not 1 <= chunk_capacity <= MAX_CHUNK_CAPACITY):
        raise FrameSpriteFragmentEnvelopeError(
            "PZFSFE002",
            f"chunk capacity {chunk_capacity!r} is outside 1..{MAX_CHUNK_CAPACITY}")
    capacity = chunk_capacity
    height = _require_int(raster_height, "raster height", minimum=1)
    actions = _action_ordinals(draw_plan)
    (frame_records, expected_object_records, expected_transient_records,
     pool_count, finite_bounds) = _record_composition(record_bound)
    rows = _class_rows(record_bound)
    transient_counts = _transient_composition(record_bound)
    transient_domains = transient_template_keys or class_template_keys
    nonrendering = frozenset(str(name) for name in nonrendering_classes)

    class_witnesses: list[dict[str, object]] = []
    class_costs: dict[str, tuple[int, int, int]] = {}
    missing_keys: set[tuple[int, int]] = set()
    missing_action_domains: list[dict[str, object]] = []
    object_action_domain = set(actions[:-1])
    transient_action = actions[-1] if actions else -1

    for row in rows:
        name = str(row["class_name"])
        ordinals = tuple(row["action_ordinals"])  # type: ignore[arg-type]
        invalid = sorted(set(ordinals) - object_action_domain)
        if invalid:
            raise FrameSpriteFragmentEnvelopeError(
                "PZFSFE003",
                f"{name} references unmapped object action(s) {invalid}")
        count = int(row["max_records_per_object"])
        raw_domain = class_template_keys.get(name, ())
        domain = tuple(sorted(set((int(a), int(b)) for a, b in raw_domain)))
        absent = tuple(key for key in domain if key not in template_metrics)
        if count and not domain and name not in nonrendering:
            missing_action_domains.append({
                "class_name": name,
                "action_ordinals": list(ordinals),
                "reason": "empty source/ROM template domain",
            })
        missing_keys.update(absent)
        witness: dict[str, object] = {
            "class_name": name,
            "action_ordinals": list(ordinals),
            "max_records_per_object": count,
            "witness_fields": row["witness_fields"],
            "candidate_template_count": len(domain),
            "candidate_template_domain_sha256": _domain_hash(domain),
            "mapped_template_count": len(domain) - len(absent),
            "missing_template_count": len(absent),
            "missing_template_sample": [list(key) for key in absent[:8]],
            "source_coverage_nonrendering": name in nonrendering,
        }
        if name in nonrendering:
            if domain:
                raise FrameSpriteFragmentEnvelopeError(
                    "PZFSFE004",
                    f"{name} is both non-rendering and owns template identities")
            class_costs[name] = (0, 0, 0)
            witness.update({
                "effective_visible_records_per_object": 0,
                "max_cmd_append_expanded_words_per_object": 0,
                "max_raster_peak_cycles_per_object": 0,
            })
        elif count and domain and not absent:
            append_one, append_key = _metric_choice(
                domain, template_metrics, "append_words")
            raster_one, raster_key = _metric_choice(
                domain, template_metrics, "raster_peak_cycles")
            append_cost = count * append_one
            raster_cost = count * raster_one
            class_costs[name] = (count, append_cost, raster_cost)
            witness.update({
                "max_append_words_per_record": append_one,
                "append_maximizer_template": list(append_key),
                "max_cmd_append_expanded_words_per_object": append_cost,
                "max_raster_peak_cycles_per_record": raster_one,
                "raster_maximizer_template": list(raster_key),
                "max_raster_peak_cycles_per_object": raster_cost,
            })
        elif count == 0:
            class_costs[name] = (0, 0, 0)
            witness.update({
                "max_cmd_append_expanded_words_per_object": 0,
                "max_raster_peak_cycles_per_object": 0,
            })
        class_witnesses.append(witness)

    transient_witnesses: list[dict[str, object]] = []
    transient_costs: dict[str, tuple[int, int, int]] = {}
    for owner, count in sorted(transient_counts.items()):
        domain = tuple(sorted(set(
            (int(a), int(b)) for a, b in transient_domains.get(owner, ()))))
        absent = tuple(key for key in domain if key not in template_metrics)
        if count and not domain:
            missing_action_domains.append({
                "class_name": owner,
                "action_ordinals": [transient_action],
                "reason": "empty transient source/ROM template domain",
            })
        missing_keys.update(absent)
        witness: dict[str, object] = {
            "owner_class": owner,
            "action_ordinal": transient_action,
            "emission_upper_bound": count,
            "candidate_template_count": len(domain),
            "candidate_template_domain_sha256": _domain_hash(domain),
            "mapped_template_count": len(domain) - len(absent),
            "missing_template_count": len(absent),
            "missing_template_sample": [list(key) for key in absent[:8]],
        }
        if count and domain and not absent:
            append_one, append_key = _metric_choice(
                domain, template_metrics, "append_words")
            raster_one, raster_key = _metric_choice(
                domain, template_metrics, "raster_peak_cycles")
            append_cost = count * append_one
            raster_cost = count * raster_one
            transient_costs[owner] = (count, append_cost, raster_cost)
            witness.update({
                "max_append_words_per_emission": append_one,
                "append_maximizer_template": list(append_key),
                "max_cmd_append_expanded_words_contribution": append_cost,
                "max_raster_peak_cycles_per_emission": raster_one,
                "raster_maximizer_template": list(raster_key),
                "max_raster_peak_cycles_contribution": raster_cost,
            })
        transient_witnesses.append(witness)

    blockers: list[dict[str, object]] = []
    if missing_action_domains:
        blockers.append({
            "code": "PZFSFE101",
            "missing_invariant": "every reachable draw action has a finite source/ROM template domain",
            "witnesses": missing_action_domains,
        })
    if missing_keys:
        blockers.append({
            "code": "PZFSFE102",
            "missing_invariant": "HQT3 contains every reachable (bank_key, descriptor) identity",
            "missing_template_count": len(missing_keys),
            "missing_template_domain_sha256": _domain_hash(missing_keys),
            "missing_template_sample": [list(key) for key in sorted(missing_keys)[:32]],
        })

    max_chunks = (frame_records + capacity - 1) // capacity
    proof_complete = not blockers
    weighted: dict[str, object]
    raster_payload: dict[str, object]
    if proof_complete:
        active_names = {
            str(row["class_name"]) for row in rows
            if int(row["max_records_per_object"]) > 0
        }
        if active_names - set(class_costs):
            raise AssertionError("complete join lost an active class cost")
        unbounded = sorted(active_names - set(finite_bounds))
        if not unbounded:
            raise FrameSpriteFragmentEnvelopeError(
                "PZFSFE006", "no unbounded class exists for pool baseline")

        record_baseline = max(class_costs[name][0] for name in unbounded)
        append_baseline = max(class_costs[name][1] for name in unbounded)
        raster_baseline = max(class_costs[name][2] for name in unbounded)
        record_premiums: list[dict[str, object]] = []
        append_premiums: list[dict[str, object]] = []
        raster_premiums: list[dict[str, object]] = []
        for name in sorted(active_names & set(finite_bounds)):
            instances = min(pool_count, finite_bounds[name])
            record_cost, append_cost, raster_cost = class_costs[name]
            record_delta = max(0, record_cost - record_baseline)
            append_delta = max(0, append_cost - append_baseline)
            raster_delta = max(0, raster_cost - raster_baseline)
            if record_delta:
                record_premiums.append({
                    "class_name": name, "instance_upper_bound": instances,
                    "premium_per_instance": record_delta,
                    "contribution": instances * record_delta,
                })
            if append_delta:
                append_premiums.append({
                    "class_name": name, "instance_upper_bound": instances,
                    "premium_per_instance": append_delta,
                    "contribution": instances * append_delta,
                })
            if raster_delta:
                raster_premiums.append({
                    "class_name": name, "instance_upper_bound": instances,
                    "premium_per_instance": raster_delta,
                    "contribution": instances * raster_delta,
                })

        derived_object_records = (
            pool_count * record_baseline +
            sum(int(item["contribution"]) for item in record_premiums))
        if derived_object_records != expected_object_records:
            raise FrameSpriteFragmentEnvelopeError(
                "PZFSFE006",
                "weighted class join does not reproduce object record proof: "
                f"{derived_object_records} != {expected_object_records}")
        if sum(transient_counts.values()) != expected_transient_records:
            raise FrameSpriteFragmentEnvelopeError(
                "PZFSFE006", "transient witnesses do not reproduce record proof")

        object_append = pool_count * append_baseline + sum(
            int(item["contribution"]) for item in append_premiums)
        object_raster = pool_count * raster_baseline + sum(
            int(item["contribution"]) for item in raster_premiums)
        transient_append = sum(value[1] for value in transient_costs.values())
        transient_raster = sum(value[2] for value in transient_costs.values())
        append_total = object_append + transient_append
        raster_peak = object_raster + transient_raster
        expanded_words = (
            append_total + frame_records * BATCH_RECORD_EXPANDED_OVERHEAD_WORDS +
            max_chunks * (BATCH_PREFIX_WORDS + BATCH_SUFFIX_WORDS))
        raster = tuple(raster_peak for _ in range(height))
        _validate_claims(
            claims, append_words=append_total, max_chunks=max_chunks,
            raster=raster, expanded_words=expanded_words)

        weighted = {
            "bound_kind": "source_derived_conservative_upper_bound",
            "max_cmd_append_expanded_words": append_total,
            "object_cmd_append_expanded_words": object_append,
            "transient_cmd_append_expanded_words": transient_append,
            "max_fragment_expanded_dl_words": expanded_words,
            "formula": (
                "max_chunks*13 + certified_frame_max_records*2 + "
                "max_cmd_append_expanded_words"),
            "object_weighting": {
                "pool_slots": pool_count,
                "unbounded_classes": unbounded,
                "unbounded_append_baseline_per_slot": append_baseline,
                "finite_append_premiums": append_premiums,
                "finite_record_premiums": record_premiums,
            },
        }
        raster_payload = {
            "height": height,
            "max_raster_cycles_by_line": list(raster),
            "max_raster_cycles_by_line_sha256": _sha256(_json_bytes(list(raster))),
            "worst_line_raster_cycles": raster_peak,
            "object_raster_cycles": object_raster,
            "transient_raster_cycles": transient_raster,
            "method": (
                "per-template HQT3 phase peak; class/premium weighting; "
                "unrestricted anchors conservatively extend the peak to every line"),
            "object_weighting": {
                "unbounded_raster_baseline_per_slot": raster_baseline,
                "finite_raster_premiums": raster_premiums,
            },
        }
    else:
        if claims is not None:
            raise FrameSpriteFragmentEnvelopeError(
                "PZFSFE007", "cannot validate a claim against an incomplete join")
        weighted = {
            "bound_kind": None,
            "max_cmd_append_expanded_words": None,
            "object_cmd_append_expanded_words": None,
            "transient_cmd_append_expanded_words": None,
            "max_fragment_expanded_dl_words": None,
            "reason": "reachable HQT3 join is incomplete",
        }
        raster_payload = {
            "height": height,
            "max_raster_cycles_by_line": None,
            "max_raster_cycles_by_line_sha256": None,
            "worst_line_raster_cycles": None,
            "reason": "reachable HQT3 join is incomplete",
        }

    payload: dict[str, object] = {
        "format": FRAME_SPRITE_FRAGMENT_ENVELOPE_FORMAT,
        "status": (
            "READY_CONSERVATIVE_ENVELOPE_PREPUBLICATION_BLOCKED"
            if proof_complete else "BLOCKED_UNMAPPED_REACHABLE_TEMPLATE"),
        "proof_complete": proof_complete,
        "can_size_sprite_fragment": proof_complete,
        "frame_budget_contract_pass": False,
        "prepublication_certified": False,
        "atomic_commit_certified": False,
        "live_eligible": False,
        "blockers": blockers,
        "integration_gates": [{
            "code": "PZFSFE201",
            "required": (
                "whole-frame prepublication and atomic fragment commit proof"),
            "satisfied": False,
        }],
        "record_envelope": {
            "certified_frame_max_records": frame_records,
            "object_records": expected_object_records,
            "transient_records": expected_transient_records,
            "chunk_capacity": capacity,
            "max_chunks": max_chunks,
            "chunk_formula": "ceil(certified_frame_max_records/chunk_capacity)",
            "chunk_capacity_target_max": MAX_CHUNK_CAPACITY,
        },
        "weighted_display_list": weighted,
        "raster_envelope": raster_payload,
        "class_action_witnesses": class_witnesses,
        "transient_composition_witnesses": transient_witnesses,
        "template_metrics": {
            "template_count": len(template_metrics),
            "domain_sha256": _domain_hash(template_metrics),
            "max_append_words_in_generated_set": (
                max((item.append_words for item in template_metrics.values()),
                    default=0)),
            "max_raster_peak_in_generated_set": (
                max((item.raster_peak_cycles
                     for item in template_metrics.values()), default=0)),
        },
        "input_bindings": dict(input_bindings or {}),
        "proof_scope": {
            "weighted_join": "class_name + action_ordinals + source/ROM template domain",
            "transients_accounted_separately": True,
            "uses_global_template_max_times_frame_records": False,
            "whole_frame_record_array_required": False,
        },
    }
    payload["semantic_sha256"] = _sha256(_json_bytes(payload))
    return FrameSpriteFragmentEnvelopeReport(payload)


def _checked_file(root: Path, row: Mapping[str, object], label: str) -> tuple[Path, bytes]:
    path_value = row.get("path")
    if not isinstance(path_value, str):
        raise FrameSpriteFragmentEnvelopeError(
            "PZFSFE008", f"{label} path is missing")
    path = (root / path_value).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise FrameSpriteFragmentEnvelopeError(
            "PZFSFE008", f"{label} escapes project root") from exc
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise FrameSpriteFragmentEnvelopeError(
            "PZFSFE008", f"cannot read {label}: {exc}") from exc
    if row.get("size") != len(data) or row.get("sha256") != _sha256(data):
        raise FrameSpriteFragmentEnvelopeError(
            "PZFSFE008", f"{label} size/hash does not match manifest")
    return path, data


def _define_values(c_text: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for name, raw in re.findall(
            r"(?m)^#define\s+(PYZ80_FT_[A-Z0-9_]+)\s+"
            r"(0x[0-9A-Fa-f]+|[0-9]+)u?l?\s*$", c_text):
        result[name] = int(raw, 0)
    return result


def _batch_prefix(c_text: str) -> tuple[tuple[int, ...], dict[str, int]]:
    values = _define_values(c_text)
    match = re.search(
        r"static const uint32_t PyZ80FT_SpriteBatchPrefix\s*\[[^]]+\]\s*=\s*\{"
        r"(?P<body>.*?)\};", c_text, re.S)
    if match is None:
        raise FrameSpriteFragmentEnvelopeError(
            "PZFSFE008", "FT812 C source lost sprite batch prefix")
    names = tuple(re.findall(r"PYZ80_FT_[A-Z0-9_]+", match.group("body")))
    try:
        prefix = tuple(values[name] for name in names)
    except KeyError as exc:
        raise FrameSpriteFragmentEnvelopeError(
            "PZFSFE008", f"unresolved sprite prefix macro {exc.args[0]}") from exc
    if (len(prefix) != BATCH_PREFIX_WORDS or
            values.get("PYZ80_FT_BATCH_PREFIX_WORDS") != BATCH_PREFIX_WORDS or
            values.get("PYZ80_FT_BATCH_SUFFIX_WORDS") != BATCH_SUFFIX_WORDS):
        raise FrameSpriteFragmentEnvelopeError(
            "PZFSFE008", "FT812 batch prefix/suffix ABI changed")
    return prefix, values


def _logical_vertex(value: int) -> int:
    magnitude = (abs(value) * 64 + 2) // 5
    return -magnitude if value < 0 else magnitude


def _phase_words(cells: Sequence[Mapping[str, object]],
                 phase_x: int, phase_y: int) -> tuple[int, ...]:
    words: list[int] = []
    current_layout: int | None = None
    current_palette: int | None = None
    for cell in cells:
        layout = int(cell["layout"])
        format_code = int(cell["format"])
        palette = int(cell["palette_ram_g"])
        if layout != current_layout:
            words.append(layout)
            current_layout = layout
        if format_code == _PALETTED4444 and palette != current_palette:
            words.append(_DL_PALETTE_SOURCE | palette)
            current_palette = palette
        local_x = int(cell["local_x"])
        local_y = int(cell["local_y"])
        relative_x = (_logical_vertex(phase_x + local_x) -
                      _logical_vertex(phase_x))
        relative_y = (_logical_vertex(phase_y + local_y) -
                      _logical_vertex(phase_y))
        words.extend((
            _DL_BITMAP_SOURCE | (int(cell["ram_g"]) & 0x003FFFFF),
            _DL_VERTEX2F | ((relative_x & 0x7FFF) << 15) |
            (relative_y & 0x7FFF),
        ))
    return tuple(words)


def _template_raster_peak(prefix: Sequence[int], defines: Mapping[str, int],
                          words: Sequence[int]) -> int:
    try:
        translate_x = defines["PYZ80_FT_DL_VERTEX_TRANSLATE_X"]
        translate_y = defines["PYZ80_FT_DL_VERTEX_TRANSLATE_Y"]
        end = defines["PYZ80_FT_DL_END"]
    except KeyError as exc:
        raise FrameSpriteFragmentEnvelopeError(
            "PZFSFE008", f"FT812 C source lost {exc.args[0]}") from exc
    # 100px expressed in the FT812 1/16-pixel translate field keeps the
    # largest generated template away from clipping while preserving its
    # internal phase geometry.  The final translate reset and END are the
    # actual batch suffix; DISPLAY terminates this isolated analysis list.
    translate = 100 * 16
    dl = tuple(prefix) + (
        translate_x | translate, translate_y | translate,
    ) + tuple(words) + (translate_x, translate_y, end, 0)
    try:
        result = analyze_display_list(
            struct.pack(f"<{len(dl)}I", *dl),
            timing=FT812Timing(height=DEFAULT_RASTER_HEIGHT),
            fail_on_budget=False)
    except Exception as exc:
        raise FrameSpriteFragmentEnvelopeError(
            "PZFSFE008", f"HQT3 template raster analysis failed: {exc}") from exc
    return max(result.line_raster_cycles, default=0)


def _load_template_metrics(
        root: Path, assets: Mapping[str, object],
        ) -> tuple[dict[tuple[int, int], TemplateMetric], dict[str, object]]:
    artifacts = assets.get("artifacts")
    if not isinstance(artifacts, Sequence):
        raise FrameSpriteFragmentEnvelopeError(
            "PZFSFE008", "asset manifest has no artifact sequence")
    candidates = [item for item in artifacts if isinstance(item, Mapping) and
                  item.get("kind") == "sprite-bootstrap-working-set"]
    if len(candidates) != 1:
        raise FrameSpriteFragmentEnvelopeError(
            "PZFSFE008", f"expected one sprite artifact, got {len(candidates)}")
    artifact = candidates[0]
    templates = artifact.get("templates")
    if not isinstance(templates, Mapping):
        raise FrameSpriteFragmentEnvelopeError(
            "PZFSFE008", "sprite artifact has no HQT3 section")
    template_path, raw = _checked_file(root, templates, "HQT3")
    if len(raw) < _HQT3_HEADER.size:
        raise FrameSpriteFragmentEnvelopeError("PZFSFE008", "HQT3 is truncated")
    (magic, version, record_size, record_count, cell_count,
     cell_record_size, state_count) = _HQT3_HEADER.unpack_from(raw)
    if (magic != b"HQT3" or version != 3 or
            record_size != _HQT3_RECORD.size or
            cell_record_size != _HQT3_CELL.size or
            templates.get("record_count") != record_count or
            templates.get("cell_count") != cell_count or
            templates.get("state_count") != state_count):
        raise FrameSpriteFragmentEnvelopeError(
            "PZFSFE008", "HQT3 header does not match manifest")
    manifest_rows = templates.get("records")
    state_rows = templates.get("states")
    if (not isinstance(manifest_rows, Sequence) or
            len(manifest_rows) != record_count or
            not isinstance(state_rows, Sequence) or
            len(state_rows) != state_count):
        raise FrameSpriteFragmentEnvelopeError(
            "PZFSFE008", "HQT3 manifest rows are incomplete")
    records_at = _HQT3_HEADER.size
    states_at = records_at + record_count * _HQT3_RECORD.size
    cells_at = states_at + state_count * _HQT3_STATE.size
    if cells_at + cell_count * _HQT3_CELL.size != len(raw):
        raise FrameSpriteFragmentEnvelopeError(
            "PZFSFE008", "HQT3 section sizes do not cover its bytes")
    states = tuple(_HQT3_STATE.unpack_from(raw, states_at + i * 8)
                   for i in range(state_count))
    for actual, row in zip(states, state_rows):
        if (not isinstance(row, Mapping) or
                actual != (int(row["layout"]), int(row["palette_ram_g"]))):
            raise FrameSpriteFragmentEnvelopeError(
                "PZFSFE008", "HQT3 bitmap state differs from manifest")

    c_tables = templates.get("c_tables")
    if not isinstance(c_tables, Mapping):
        raise FrameSpriteFragmentEnvelopeError(
            "PZFSFE008", "HQT3 generated C bindings are missing")
    c_source_row = c_tables.get("source")
    c_header_row = c_tables.get("header")
    if not isinstance(c_source_row, Mapping) or not isinstance(c_header_row, Mapping):
        raise FrameSpriteFragmentEnvelopeError(
            "PZFSFE008", "HQT3 C/H manifest rows are malformed")
    c_source_path, c_source_raw = _checked_file(root, c_source_row, "HQT3 C")
    c_header_path, c_header_raw = _checked_file(root, c_header_row, "HQT3 H")
    ft_c_path = root / "Source" / "C" / "ft812" / "pyz80_ft812.c"
    ft_c_raw = ft_c_path.read_bytes()
    prefix, defines = _batch_prefix(ft_c_raw.decode("utf-8"))

    append = templates.get("append")
    if not isinstance(append, Mapping):
        raise FrameSpriteFragmentEnvelopeError(
            "PZFSFE008", "HQT3 CMD_APPEND section is missing")
    append_path, append_raw = _checked_file(root, append, "CMD_APPEND pack")
    unique: list[bytes] = []
    unique_index: dict[bytes, int] = {}
    mapping: list[int] = []
    metrics: dict[tuple[int, int], TemplateMetric] = {}
    next_cell = 0
    for index, row in enumerate(manifest_rows):
        if not isinstance(row, Mapping):
            raise FrameSpriteFragmentEnvelopeError(
                "PZFSFE008", "HQT3 template row is malformed")
        packed = _HQT3_RECORD.unpack_from(
            raw, records_at + index * _HQT3_RECORD.size)
        expected = (
            int(row["bank_key"]), int(row["flags"]),
            int(row["resource_type"]), int(row["descriptor_address"]),
            int(row["dx"]), int(row["dy"]), int(row["code"]),
            int(row["width"]), int(row["height"]),
            int(row["cell_first"]), int(row["cell_count"]),
        )
        if packed != expected or expected[9] != next_cell:
            raise FrameSpriteFragmentEnvelopeError(
                "PZFSFE008", "HQT3 record differs from manifest/order")
        cells = row.get("cells")
        if not isinstance(cells, Sequence) or len(cells) != expected[10]:
            raise FrameSpriteFragmentEnvelopeError(
                "PZFSFE008", "HQT3 cell list differs from record")
        for offset, cell in enumerate(cells):
            if not isinstance(cell, Mapping):
                raise FrameSpriteFragmentEnvelopeError(
                    "PZFSFE008", "HQT3 cell row is malformed")
            actual_cell = _HQT3_CELL.unpack_from(
                raw, cells_at + (next_cell + offset) * _HQT3_CELL.size)
            expected_cell = (
                int(cell["ram_g"]), int(cell["local_x"]),
                int(cell["local_y"]), int(cell["state_index"]),
            )
            if actual_cell != expected_cell or not 0 <= expected_cell[3] < state_count:
                raise FrameSpriteFragmentEnvelopeError(
                    "PZFSFE008", "HQT3 cell differs from manifest/state domain")
            if (int(cell["layout"]), int(cell["palette_ram_g"])) != \
                    states[expected_cell[3]]:
                raise FrameSpriteFragmentEnvelopeError(
                    "PZFSFE008", "HQT3 expanded cell state is inconsistent")
        phase_words: list[tuple[int, ...]] = []
        raster_peak = 0
        for phase_x in range(5):
            for phase_y in range(5):
                words = _phase_words(cells, phase_x, phase_y)
                phase_words.append(words)
                blob = struct.pack(f"<{len(words)}I", *words)
                blob_index = unique_index.get(blob)
                if blob_index is None:
                    blob_index = len(unique)
                    unique_index[blob] = blob_index
                    unique.append(blob)
                if blob_index > 0xFF:
                    raise FrameSpriteFragmentEnvelopeError(
                        "PZFSFE008", "CMD_APPEND mapping exceeds uint8")
                mapping.append(blob_index)
                raster_peak = max(
                    raster_peak, _template_raster_peak(prefix, defines, words))
        word_counts = tuple(len(words) for words in phase_words)
        key = expected[0], expected[3]
        if key in metrics:
            raise FrameSpriteFragmentEnvelopeError(
                "PZFSFE008", f"duplicate HQT3 key {key}")
        metrics[key] = TemplateMetric(
            bank_key=key[0], descriptor_address=key[1],
            append_words=max(word_counts),
            raster_peak_cycles=raster_peak,
            cell_count=len(cells), phase_word_counts=word_counts)
        next_cell += len(cells)
    if next_cell != cell_count:
        raise FrameSpriteFragmentEnvelopeError(
            "PZFSFE008", "HQT3 cells are not covered exactly once")
    mapping_bytes = bytes(mapping)
    expected_append = b"".join(unique)
    if (expected_append != append_raw or append.get("mapping_count") != len(mapping) or
            append.get("mapping_sha256") != _sha256(mapping_bytes) or
            append.get("blob_count") != len(unique)):
        raise FrameSpriteFragmentEnvelopeError(
            "PZFSFE008", "CMD_APPEND bytes/mapping are not reproducible from HQT3")
    blob_rows = append.get("blobs")
    if not isinstance(blob_rows, Sequence) or len(blob_rows) != len(unique):
        raise FrameSpriteFragmentEnvelopeError(
            "PZFSFE008", "CMD_APPEND blob witnesses are incomplete")
    offset = 0
    base = _require_int(append.get("ram_g_base"), "CMD_APPEND RAM_G base")
    for blob, row in zip(unique, blob_rows):
        if not isinstance(row, Mapping):
            raise FrameSpriteFragmentEnvelopeError(
                "PZFSFE008", "CMD_APPEND blob witness is malformed")
        expected_row = {
            "ram_g": base + offset,
            "offset": offset,
            "size": len(blob),
            "word_count": len(blob) // 4,
            "sha256": _sha256(blob),
        }
        if dict(row) != expected_row:
            raise FrameSpriteFragmentEnvelopeError(
                "PZFSFE008", "CMD_APPEND blob witness is optimistic/stale")
        offset += len(blob)
    bindings = {
        "assets_manifest_format": assets.get("format"),
        "hqt3": {
            "path": template_path.relative_to(root).as_posix(),
            "sha256": _sha256(raw), "record_count": record_count,
        },
        "cmd_append": {
            "path": append_path.relative_to(root).as_posix(),
            "sha256": _sha256(append_raw),
            "mapping_sha256": _sha256(mapping_bytes),
        },
        "generated_hqt3_c": {
            "path": c_source_path.relative_to(root).as_posix(),
            "sha256": _sha256(c_source_raw),
        },
        "generated_hqt3_h": {
            "path": c_header_path.relative_to(root).as_posix(),
            "sha256": _sha256(c_header_raw),
        },
        "ft812_batch_c": {
            "path": ft_c_path.relative_to(root).as_posix(),
            "sha256": _sha256(ft_c_raw),
            "prefix_words": len(prefix), "suffix_words": BATCH_SUFFIX_WORDS,
        },
    }
    return metrics, bindings


def _pair_keys(pairs: Iterable[object]) -> set[tuple[int, int]]:
    result: set[tuple[int, int]] = set()
    for raw_pair in pairs:
        pair = raw_pair
        for bank in pair.bank_keys:  # type: ignore[attr-defined]
            if bank.kind == "typed-resource":
                bank_key = 0x0100 | bank.value
            elif bank.kind == "palette-fallback":
                bank_key = bank.value
            else:
                raise FrameSpriteFragmentEnvelopeError(
                    "PZFSFE004", f"unknown Python bank kind {bank.kind}")
            result.add((bank_key, pair.descriptor.address))  # type: ignore[attr-defined]
    return result


def _coverage_domains(coverage: CoverageReport) -> tuple[
        dict[str, tuple[tuple[int, int], ...]], frozenset[str], dict[str, object]]:
    domains: dict[str, set[tuple[int, int]]] = {}
    stages: dict[str, set[int]] = {}
    nonrendering: set[str] = set()
    for stage in coverage.stage_provenance:
        stage_rows = {item.class_name: item for item in stage.class_coverage}
        explosion_domain = _pair_keys(
            stage_rows["ExplosionEffect"].pairs
            if "ExplosionEffect" in stage_rows else ())
        for item in stage.class_coverage:
            bucket = domains.setdefault(item.class_name, set())
            stages.setdefault(item.class_name, set()).add(stage.stage)
            bucket.update(_pair_keys(item.pairs))
            if item.relation_kind == "inherited-explosion-effect":
                if not explosion_domain:
                    raise FrameSpriteFragmentEnvelopeError(
                        "PZFSFE004",
                        f"{item.class_name} lost inherited explosion domain")
                bucket.update(explosion_domain)
            elif item.relation_kind in {
                    "no-visible-descriptor-domain", "non-visible-controller"}:
                nonrendering.add(item.class_name)
    common = dict(coverage.common_domain_pairs)
    fixed = common.get("fixed_shot_visual", ())
    if fixed:
        domains.setdefault("PlayerShotVisual4EAF", set()).update(
            _pair_keys(fixed))
        stages.setdefault("PlayerShotVisual4EAF", set()).update(range(1, 9))
        nonrendering.discard("PlayerShotVisual4EAF")
    # A class seen as non-rendering in one stage must not gain a visible domain
    # in another.  This also catches an optimistic inheritance shortcut.
    conflict = sorted(name for name in nonrendering if domains.get(name))
    if conflict:
        raise FrameSpriteFragmentEnvelopeError(
            "PZFSFE004",
            f"classes are both visible and non-rendering: {conflict}")
    result = {name: tuple(sorted(keys)) for name, keys in domains.items()}
    provenance = {
        "root_module": coverage.root_module,
        "rom_sha256": coverage.rom_sha256,
        "source_hashes": dict(coverage.source_hashes),
        "class_domains": {
            name: {
                "stages": sorted(stages.get(name, ())),
                "template_count": len(keys),
                "template_domain_sha256": _domain_hash(keys),
            }
            for name, keys in sorted(result.items())
        },
    }
    provenance["nonrendering_classes"] = sorted(nonrendering)
    return result, frozenset(nonrendering), provenance


def _check_bound_source_bindings(root: Path, bound: Mapping[str, object]) -> None:
    bindings = bound.get("source_bindings")
    if not isinstance(bindings, Mapping):
        raise FrameSpriteFragmentEnvelopeError(
            "PZFSFE001", "record bound source bindings are missing")
    for relative, expected in bindings.items():
        path = root / str(relative)
        try:
            actual = _sha256(path.read_bytes())
        except OSError as exc:
            raise FrameSpriteFragmentEnvelopeError(
                "PZFSFE001", f"cannot verify bound source {relative}: {exc}") from exc
        if actual != expected:
            raise FrameSpriteFragmentEnvelopeError(
                "PZFSFE001", f"record bound is stale for {relative}")


def analyze_frame_sprite_fragment_envelope(
        project_root: Path | str, *,
        chunk_capacity: int = DEFAULT_CHUNK_CAPACITY,
        record_bound_report: Mapping[str, object] | None = None,
        coverage_report: CoverageReport | None = None,
        assets_manifest: Mapping[str, object] | None = None,
        draw_plan: SpriteDrawPlanIR | None = None,
        ) -> FrameSpriteFragmentEnvelopeReport:
    """Bind and analyze the active non-canonical Python project."""

    root = Path(project_root).resolve()
    bound_path = root / "Build" / "rtype_python_frame_record_bound_status.json"
    assets_path = root / "Build" / "rtype_python_assets.json"
    if record_bound_report is None:
        bound_raw = bound_path.read_bytes()
        bound = json.loads(bound_raw.decode("utf-8"))
    else:
        bound = dict(record_bound_report)
        bound_raw = _json_bytes(bound)
    _check_bound_source_bindings(root, bound)
    plan = draw_plan or compile_active_enemy_draw_plan(root)
    bound_plan = bound.get("draw_plan")
    if (not isinstance(bound_plan, Mapping) or
            bound_plan.get("semantic_sha256") != plan.semantic_sha256 or
            bound_plan.get("source_sha256") != plan.source_sha256):
        raise FrameSpriteFragmentEnvelopeError(
            "PZFSFE001", "record bound and active DrawPlan are not hash-bound")
    coverage = coverage_report or analyze_sprite_coverage(root)
    domains, nonrendering, coverage_binding = _coverage_domains(coverage)
    # ``CoverageReport`` is a closed source/ROM reachability proof.  A class
    # which exists in the generic DrawPlan multiplicity table but owns neither
    # a stage relation nor a common-domain adapter is unreachable in the
    # launched program, hence contributes no visible record/template cost.
    bound_class_names = {
        str(item["class_name"]) for item in _class_rows(bound)
    }
    coverage_owned_names = set(domains) | set(nonrendering)
    unreachable_draw_classes = frozenset(
        bound_class_names - coverage_owned_names)
    nonrendering = frozenset(set(nonrendering) | set(unreachable_draw_classes))
    coverage_binding["source_rom_unreachable_draw_classes"] = sorted(
        unreachable_draw_classes)
    reachability = bound.get("abstract_reachability")
    try:
        bound_rom = reachability["event_cursor"]["rom_sha256"]  # type: ignore[index]
    except (KeyError, TypeError) as exc:
        raise FrameSpriteFragmentEnvelopeError(
            "PZFSFE001", "record bound lost ROM binding") from exc
    if bound_rom != coverage.rom_sha256:
        raise FrameSpriteFragmentEnvelopeError(
            "PZFSFE001", "record-bound ROM differs from sprite coverage ROM")
    if assets_manifest is None:
        assets_raw = assets_path.read_bytes()
        assets = json.loads(assets_raw.decode("utf-8"))
    else:
        assets = dict(assets_manifest)
        assets_raw = _json_bytes(assets)
    metrics, hqt_binding = _load_template_metrics(root, assets)
    bindings = {
        "frame_record_bound": {
            "path": bound_path.relative_to(root).as_posix(),
            "sha256": _sha256(bound_raw),
            "semantic_status": bound.get("status"),
        },
        "draw_plan": {
            "format": plan.format,
            "source_path": plan.source_path,
            "source_sha256": plan.source_sha256,
            "method_ast_sha256": plan.method_ast_sha256,
            "semantic_sha256": plan.semantic_sha256,
        },
        "sprite_coverage": coverage_binding,
        "assets_manifest": {
            "path": assets_path.relative_to(root).as_posix(),
            "sha256": _sha256(assets_raw),
            "source_ast_sha256": assets.get("source_ast_sha256"),
        },
        "generated_templates": hqt_binding,
    }
    return build_frame_sprite_fragment_envelope(
        bound, plan, domains, metrics,
        transient_template_keys=domains,
        nonrendering_classes=nonrendering,
        chunk_capacity=chunk_capacity,
        raster_height=DEFAULT_RASTER_HEIGHT,
        input_bindings=bindings)
