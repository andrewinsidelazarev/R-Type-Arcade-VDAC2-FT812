#!/usr/bin/env python3
"""Proof tests for the source-derived FT812 frame-timing provider."""

from __future__ import annotations

import copy
from fractions import Fraction
import hashlib
import unittest
from pathlib import Path

from check_pyz80_frame_timing_provider import probe, validate_report
from pyz80_compiler.frame_timing_provider import (
    DEFAULT_INCLUDE,
    DEFAULT_MANIFEST,
    DEFAULT_STATUS,
    FRAME_TIMING_CONTRACT_FORMAT,
    FRAME_TIMING_PROVIDER_FORMAT,
    FRAME_TIMING_PROVIDER_STATUS,
    FrameTimingProviderError,
    _closest_vcycle,
    render_frame_timing_include,
    render_frame_timing_manifest,
)


ROOT = Path(__file__).resolve().parents[2]


class FrameTimingMathTests(unittest.TestCase):
    def test_closest_integer_vcycle_is_866(self) -> None:
        selected, candidates, ideal = _closest_vcycle(
            64_000_000, 1344, Fraction(55, 1), 806)
        self.assertEqual(ideal, Fraction(200000, 231))
        self.assertEqual([row["vcycle"] for row in candidates], [865, 866])
        self.assertEqual(selected, 866)
        errors = {
            row["vcycle"]: Fraction(
                row["absolute_error_hz"]["numerator"],
                row["absolute_error_hz"]["denominator"])
            for row in candidates
        }
        self.assertLess(errors[866], errors[865])

    def test_exact_refresh_and_error_are_rational(self) -> None:
        refresh = Fraction(64_000_000, 1344 * 866)
        self.assertEqual(refresh, Fraction(500000, 9093))
        self.assertEqual(refresh - 55, Fraction(-115, 9093))
        self.assertEqual((refresh - 55) / 55, Fraction(-23, 100023))
        self.assertEqual(Fraction(1_000_000, 1) / refresh, 18186)

    def test_practical_scanline_limit_is_floor_of_ninety_percent(self) -> None:
        self.assertEqual(int(Fraction(1344 * 9, 10)), 1209)
        self.assertEqual(Fraction(1344 * 1_000_000, 64_000_000), 21)
        self.assertEqual(
            Fraction(1209 * 1_000_000, 64_000_000),
            Fraction(151125, 8000))


class FrameTimingProviderIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            cls.report = probe(ROOT)
        except FrameTimingProviderError as exc:
            if exc.code == "PZFTP110":
                raise unittest.SkipTest(
                    "active call graph/adapters await the coordinated stable regeneration")
            raise
        cls.contract = cls.report["contract"]

    def test_contract_is_source_derived_and_fail_closed(self) -> None:
        self.assertEqual(self.report["format"], FRAME_TIMING_PROVIDER_FORMAT)
        self.assertEqual(self.report["status"], FRAME_TIMING_PROVIDER_STATUS)
        self.assertEqual(self.contract["format"], FRAME_TIMING_CONTRACT_FORMAT)
        self.assertFalse(self.report["live"])
        self.assertEqual(
            [row["code"] for row in self.report["live_blockers"]],
            ["PZFTP201", "PZFTP202", "PZFTP203", "PZFTP204"])
        self.assertFalse(self.report["integration"]["backend_consumes_contract"])
        self.assertFalse(self.report["integration"]["assembler_link_proof_present"])
        self.assertFalse(
            self.report["integration"]["measured_ft812_timing_proof_present"])

    def test_python_tsfm_ft812_and_scanline_contract(self) -> None:
        source_rates = self.contract["source_rates"]
        self.assertEqual(source_rates["python_application_hz"]["numerator"], 55)
        self.assertEqual(source_rates["python_tsfm_hz"]["numerator"], 55)
        self.assertTrue(source_rates["rates_equal"])
        base = self.contract["base_profile"]
        self.assertEqual(base["system_clock_hz"], 64_000_000)
        self.assertEqual(base["pclk_divisor"], 1)
        self.assertEqual(base["pixel_clock_hz"], 64_000_000)
        self.assertEqual(base["horizontal_visible"], 1024)
        self.assertEqual(base["vertical_visible"], 768)
        self.assertEqual(base["registers"]["FT_REG_HCYCLE"], 1344)
        selected = self.contract["selected_profile"]
        self.assertEqual(selected["changed_registers"], ["FT_REG_VCYCLE"])
        self.assertEqual(selected["registers"]["FT_REG_VCYCLE"], 866)
        self.assertEqual(selected["vertical_blank_lines"], 98)
        self.assertEqual(selected["added_vertical_blank_lines"], 60)
        self.assertEqual(
            self.contract["scanline_budget"]["practical_cycle_limit_floor"],
            1209)

    def test_closest_refresh_and_dlswap_cadence_are_exactly_proven(self) -> None:
        selection = self.contract["selection_proof"]
        self.assertFalse(selection["exact_55hz_integer_vcycle_exists"])
        self.assertEqual(
            [row["vcycle"] for row in
             selection["integer_candidates_around_crossing"]], [865, 866])
        self.assertEqual(selection["selected_vcycle"], 866)
        cadence = self.contract["actual_cadence"]
        self.assertEqual(
            (cadence["refresh_hz"]["numerator"],
             cadence["refresh_hz"]["denominator"]), (500000, 9093))
        self.assertEqual(
            (cadence["signed_error_hz"]["numerator"],
             cadence["signed_error_hz"]["denominator"]), (-115, 9093))
        swap = self.contract["dl_swap_cadence"]
        self.assertEqual(swap["application_update_calls_per_loop"], 1)
        self.assertEqual(swap["tsfm_update_calls_per_loop"], 1)
        self.assertEqual(swap["render_calls_per_loop"], 1)
        self.assertEqual(swap["dlswap_frame_request_sites_per_render"], 1)
        self.assertEqual(swap["successful_render_submissions_per_loop_maximum"], 1)
        self.assertFalse(swap["request_is_unconditional"])
        self.assertTrue(swap["render_error_path_can_skip_swap_request"])
        self.assertTrue(swap["waits_for_previous_swap_before_next_render"])
        self.assertFalse(swap["measured_one_tick_per_physical_frame"])

    def test_active_adapter_family_binding_is_exact(self) -> None:
        binding = self.contract["adapter_family_binding"]
        self.assertEqual(binding["family_id"], "frame-timing-55hz")
        self.assertGreater(binding["site_count"], 0)
        self.assertEqual(binding["site_count"], len(binding["call_site_ids"]))
        self.assertEqual(
            binding["site_count"], len(binding["site_source_span_sha256"]))
        self.assertEqual(len(set(binding["call_site_ids"])),
                         binding["site_count"])

    def test_generated_artifacts_are_exact_and_do_not_claim_live(self) -> None:
        artifacts = self.report["generated_artifacts"]
        self.assertEqual(artifacts["include"]["path"], DEFAULT_INCLUDE)
        self.assertEqual(artifacts["manifest"]["path"], DEFAULT_MANIFEST)
        include = render_frame_timing_include(self.report).encode("utf-8")
        manifest = render_frame_timing_manifest(self.report).encode("utf-8")
        self.assertEqual(hashlib.sha256(include).hexdigest(),
                         artifacts["include"]["sha256"])
        self.assertEqual(hashlib.sha256(manifest).hexdigest(),
                         artifacts["manifest"]["sha256"])
        self.assertIn(b"RTYPE_PY_FT_VCYCLE                     EQU 866", include)
        self.assertIn(b'"live": false', manifest)
        self.assertEqual(self.report["integration"]["include_path"],
                         DEFAULT_INCLUDE)
        self.assertEqual(self.report["integration"]["manifest_path"],
                         DEFAULT_MANIFEST)
        self.assertEqual(DEFAULT_STATUS,
                         "Build/rtype_python_frame_timing_provider_status.json")

    def test_semantic_validator_rejects_tampering(self) -> None:
        tampered = copy.deepcopy(self.report)
        tampered["contract"]["selected_profile"]["registers"][
            "FT_REG_VCYCLE"] = 865
        with self.assertRaises(FrameTimingProviderError) as raised:
            validate_report(ROOT, tampered, validate_artifacts=False)
        self.assertEqual(raised.exception.code, "PZFTP403")


if __name__ == "__main__":
    unittest.main()
