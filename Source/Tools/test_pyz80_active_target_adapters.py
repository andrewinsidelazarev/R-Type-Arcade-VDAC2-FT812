#!/usr/bin/env python3
"""Proof tests for source-derived active target adapter inventory."""

from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path

from check_pyz80_active_target_adapters import probe, validate_report
from pyz80_compiler.active_target_adapters import (
    ACTIVE_TARGET_ADAPTERS_FORMAT,
    ACTIVE_TARGET_ADAPTERS_STATUS,
    ActiveTargetAdaptersError,
)


ROOT = Path(__file__).resolve().parents[2]


class ActiveTargetAdaptersTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = probe(ROOT)
        cls.inventory = cls.report["inventory"]
        cls.sites = cls.inventory["sites"]
        cls.active_graph = json.loads(
            (ROOT / "Build" /
             "rtype_python_active_call_graph_status.json").read_text(
                 encoding="utf-8"))

    def test_report_is_live_blocked_and_covers_exact_active_input(self) -> None:
        self.assertEqual(self.report["format"], ACTIVE_TARGET_ADAPTERS_FORMAT)
        self.assertEqual(self.report["status"], ACTIVE_TARGET_ADAPTERS_STATUS)
        self.assertFalse(self.report["live"])
        call_graph = self.active_graph["call_graph"]
        reachable = set(call_graph["proven_reachable_callable_ids"])
        reachable_sites = [
            row for row in call_graph["call_sites"]
            if row["caller"] in reachable
        ]
        self.assertEqual(
            self.inventory["runtime"]["input_host_boundary_count"],
            sum(row["resolution"]["kind"] == "host-boundary"
                for row in reachable_sites))
        self.assertEqual(
            self.inventory["runtime"]["input_unresolved_count"],
            sum(row["resolution"]["kind"].startswith("unresolved-")
                for row in reachable_sites))
        self.assertEqual(
            self.inventory["runtime"]["input_finite_dynamic_count"],
            sum(row["resolution"]["kind"] == "finite-dynamic-dispatch"
                for row in reachable_sites))
        self.assertEqual(
            self.inventory["module_initialization"]["site_count"],
            self.active_graph["module_initialization"]
            ["host_boundary_call_site_count"] +
            self.active_graph["module_initialization"]
            ["unresolved_call_site_count"])
        self.assertEqual(len({row["call_site_id"] for row in self.sites}),
                         len(self.sites))
        resolved = sorted(row["call_site_id"] for row in self.sites
                          if row["exact_callable_semantics"])
        unresolved = sorted(row["call_site_id"] for row in self.sites
                            if not row["exact_callable_semantics"])
        self.assertEqual(self.inventory["resolved_call_site_ids"], resolved)
        self.assertEqual(
            self.inventory["unresolved_call_site_ids"], unresolved)
        self.assertFalse(set(resolved) & set(unresolved))
        for row in self.sites:
            span = {
                "module": row["module"], "line": row["line"],
                "column": row["column"], "source": row["source"],
                "ast_sha256": row["ast_sha256"],
            }
            digest = hashlib.sha256(json.dumps(
                span, ensure_ascii=False, sort_keys=True,
                separators=(",", ":")).encode("utf-8")).hexdigest()
            self.assertEqual(row["source_span_sha256"], digest)
        self.assertLess(self.inventory["semantic_group_count"],
                        self.inventory["site_count"])
        self.assertTrue(any(row["site_count"] > 1
                            for row in self.inventory["semantic_groups"]))

    def test_module_initialization_adapters_are_separate(self) -> None:
        module = [row for row in self.sites
                  if row["context"] == "module-initialization"]
        runtime = [row for row in self.sites if row["context"] == "runtime"]
        self.assertEqual(len(module),
                         self.inventory["module_initialization"]["site_count"])
        self.assertEqual(len(runtime), self.inventory["runtime"]["site_count"])
        self.assertTrue(
            self.inventory["module_initialization"]["separate_from_runtime"])
        self.assertFalse({row["call_site_id"] for row in module} &
                         {row["call_site_id"] for row in runtime})

    def test_source_resolver_is_conservative_and_never_uses_annotations(self) -> None:
        self.assertGreater(
            self.inventory["source_resolved_internal_call_count"], 0)
        self.assertGreater(
            self.inventory["unresolved_callable_semantics_count"], 0)
        self.assertTrue(all(
            row["annotations_used_as_type_evidence"] is False
            for row in self.sites))
        supers = [row for row in self.sites
                  if row["source"].startswith("super().__init__")]
        self.assertTrue(supers)
        self.assertTrue(any(
            row["exact_callable_semantics"] and
            "base" in row["source_resolution_evidence"]
            for row in supers))
        callback_attributes = [
            row for row in self.sites
            if row["source"].startswith("self.play_sfx(")
        ]
        self.assertTrue(callback_attributes)
        self.assertTrue(any(
            row["exact_callable_semantics"] and
            "constructor argument flow" in row["source_resolution_evidence"]
            for row in callback_attributes))
        finite_world_rom = [row for row in self.sites
                            if row["source"].startswith("world.rom.word")]
        self.assertTrue(finite_world_rom)
        self.assertTrue(all(
            row["input_resolution_kind"] == "finite-dynamic-dispatch" and
            not row["exact_callable_semantics"]
            for row in finite_world_rom))
        fact_proof = self.inventory["interprocedural_fact_proof"]
        self.assertGreater(fact_proof["exact_fact_count"], 0)
        self.assertFalse(fact_proof["annotations_used_as_type_evidence"])

    def test_provider_evidence_is_real_and_55hz_provider_is_fail_closed(self) -> None:
        catalog = self.report["provider_catalog"]
        families = {row["family_id"]: row for row in catalog["families"]}
        self.assertEqual(set(families), {
            "ft812-video-draw", "tsconf-input-mouse", "frame-timing-55hz",
            "tsfm-music", "gs-sfx", "asset-level-loader-4mb",
            "c-z80-intrinsics",
        })
        for name in ("ft812-video-draw", "tsconf-input-mouse",
                     "tsfm-music", "gs-sfx", "asset-level-loader-4mb"):
            self.assertTrue(families[name]["provider_evidence"])
            self.assertEqual(families[name]["status"],
                             "PROVIDER_FAMILY_SYMBOLS_PROVEN")
        timing = families["frame-timing-55hz"]
        self.assertEqual(
            timing["status"],
            "SOURCE_DERIVED_55HZ_PROVIDER_UNMEASURED_UNLINKED")
        self.assertTrue(timing["provider_evidence"])
        self.assertIn(
            "RTypeFrameTiming_ApplyGenerated",
            {row["symbol"] for row in timing["provider_evidence"]})
        self.assertTrue(timing["incompatible_candidate_evidence"])
        self.assertTrue(catalog["exact_55hz_source_derived_provider_present"])
        self.assertFalse(catalog["exact_55hz_isr_provider_present"])
        self.assertEqual(catalog["physical_ts_ram_bytes"], 4 * 1024 * 1024)
        self.assertGreater(self.inventory["provider_family_counts"]["tsfm-music"],
                           0)
        self.assertGreater(self.inventory["provider_family_counts"]["gs-sfx"],
                           0)

    def test_only_current_narrow_min_max_intrinsic_is_capability_matched(self) -> None:
        matched = [row for row in self.sites
                   if row["provider_capability_match"]]
        self.assertTrue(matched)
        self.assertTrue(all(row["semantic"] in {
            "builtins.min", "builtins.max"} for row in matched))
        self.assertTrue(all(row["signature"]["positional_count"] == 2
                            for row in matched))
        other_builtins = [row for row in self.sites
                          if row["semantic"] == "builtins.range"]
        self.assertTrue(other_builtins)
        self.assertTrue(all(not row["provider_capability_match"]
                            for row in other_builtins))

    def test_mouse_contract_keeps_coordinates_and_controls_untouched(self) -> None:
        families = {row["family_id"]: row
                    for row in self.report["provider_catalog"]["families"]}
        symbols = {row["symbol"]
                   for row in families["tsconf-input-mouse"]["provider_evidence"]}
        self.assertIn("Input_MouseX", symbols)
        self.assertIn("Input_MouseY", symbols)
        input_groups = [row for row in self.inventory["semantic_groups"]
                        if row["provider_family_id"] == "tsconf-input-mouse"]
        self.assertTrue(input_groups)
        self.assertTrue(any(
            "treat mouse position providers as coordinates, never as direction"
            in row["adapter_abi_obligations"] for row in input_groups))

    def test_semantic_validator_rejects_tampering(self) -> None:
        tampered = copy.deepcopy(self.report)
        tampered["inventory"]["site_count"] += 1
        with self.assertRaises(ActiveTargetAdaptersError) as raised:
            validate_report(ROOT, tampered)
        self.assertEqual(raised.exception.code, "PZATA403")


if __name__ == "__main__":
    unittest.main()
