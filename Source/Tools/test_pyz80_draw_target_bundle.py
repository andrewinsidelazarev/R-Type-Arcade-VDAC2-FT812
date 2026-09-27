from __future__ import annotations

import json
import unittest
from pathlib import Path

from check_pyz80_draw_target_bundle import (
    DrawTargetBundleError,
    FORMAT,
    HQ_EXCLUDED_SYMBOLS,
    HQ_REQUIRED_SYMBOLS,
    STATUS,
    _area_map,
    _extract_c_array,
    _json_bytes,
    _linked_files,
    _map_definitions,
    _sdnm_symbols,
    build_dependency_slices,
    probe,
)


ROOT = Path(__file__).resolve().parents[2]


class DrawTargetBundlePureTests(unittest.TestCase):
    def test_dependency_slices_are_deterministic_and_minimal(self) -> None:
        first = build_dependency_slices(ROOT)
        second = build_dependency_slices(ROOT)
        self.assertEqual(first, second)
        hq_source = str(first["hq_source"])
        ft_source = str(first["ft_source"])
        for symbol in HQ_REQUIRED_SYMBOLS:
            self.assertIn(symbol, hq_source)
        for symbol in HQ_EXCLUDED_SYMBOLS:
            self.assertNotIn("\n" + symbol + "[", hq_source)
        self.assertIn("PyZ80FT_BuildSpriteBatchFast", ft_source)
        self.assertIn("PyZ80FT_FindHQTemplate", ft_source)
        self.assertNotIn("PyZ80FT_QueueCommit(", ft_source)
        self.assertNotIn("PyZ80FT_ResolveBankKey(", ft_source)

    def test_array_extractor_fails_closed(self) -> None:
        with self.assertRaises(DrawTargetBundleError):
            _extract_c_array("const uint8_t Other[1] = { 0 };\n", "Wanted")
        with self.assertRaises(DrawTargetBundleError):
            _extract_c_array(
                "const uint8_t Wanted[1] = { 0 };\n"
                "const uint8_t Wanted[1] = { 1 };\n",
                "Wanted")

    def test_link_map_parsers_measure_areas_and_inventory(self) -> None:
        sample = """
_CODE                               00008000    000042F1 = 17137. bytes
_DATA                               0000C000    00000500 = 1280. bytes
Files Linked                              [ module(s) ]
one.rel                                   [ one ]
two.rel                                   [ two ]
Libraries Linked                          [ object file ]
C:\\sdcc\\z80.lib                       [ memcpy.rel ]
User Base Address Definitions
     00008000  _long_symbol_prefix_12345678901234   one
"""
        self.assertEqual(
            _area_map(sample),
            {"_CODE": (0x8000, 0x42F1), "_DATA": (0xC000, 0x500)})
        self.assertEqual(
            _linked_files(sample),
            (["one.rel", "two.rel"], ["memcpy.rel"]))
        self.assertEqual(
            _map_definitions(sample)["_long_symbol_prefix_12345678901234"],
            (0x8000, "one"))

    def test_sdnm_parser_separates_definitions_and_references(self) -> None:
        defined, undefined = _sdnm_symbols(
            "00000000 A .__.ABS.\n"
            "         U ___memcpy\n"
            "00000123 T _entry\n")
        self.assertEqual(defined, {".__.ABS.": "A", "_entry": "T"})
        self.assertEqual(undefined, {"___memcpy"})


class DrawTargetBundleIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = probe(ROOT)

    def test_linked_certificate_is_deterministic_checked_in_status(self) -> None:
        status_path = ROOT / "Build/rtype_python_draw_target_bundle_status.json"
        self.assertEqual(status_path.read_bytes(), _json_bytes(self.result))
        parsed = json.loads(status_path.read_text(encoding="utf-8"))
        self.assertEqual(parsed, self.result)

    def test_actual_combined_link_facts(self) -> None:
        self.assertEqual(self.result["format"], FORMAT)
        self.assertEqual(self.result["status"], STATUS)
        self.assertFalse(self.result["live"])
        link = self.result["link"]
        self.assertEqual(link["code"]["bytes"], 17137)
        self.assertEqual(link["code"]["banks_required"], 2)
        self.assertEqual(link["code"]["single_bank_overflow_bytes"], 753)
        self.assertEqual(link["data"]["bytes"], 1280)
        self.assertTrue(link["placement"]["code_data_overlap"])
        self.assertEqual(len(link["direct_objects"]), 6)
        self.assertEqual(
            sorted(link["runtime_objects"]),
            ["__sdcc_call_iy.rel", "memcpy.rel"])

    def test_known_stack_is_bounded_but_complete_stack_is_not_claimed(self) -> None:
        stack = self.result["stack"]
        self.assertEqual(stack["maximum_known_candidate_bytes"], 245)
        self.assertGreater(stack["known_candidate_headroom_bytes"], 0)
        self.assertIsNone(stack["complete_bound_bytes"])
        self.assertFalse(stack["complete_bound_certified"])
        missing = {item["code"] for item in stack["missing_bounds"]}
        self.assertEqual(missing, {
            "PZTB_STACK_RESOURCE_RESOLVER",
            "PZTB_STACK_BANK_RESOLVER",
            "PZTB_STACK_OBJECT_PROVIDER_BINDING",
            "PZTB_STACK_CHUNK_SUBMIT_BINDING",
            "PZTB_STACK_TARGET_PROVIDER",
            "PZTB_STACK_INTERRUPT_COMPOSITION",
        })

    def test_frame_budget_v4_atomicity_is_an_explicit_blocker(self) -> None:
        frame = self.result["frame_publication_contract"]
        self.assertEqual(
            frame["required_contract_format"],
            "pyz80-ft812-frame-fragment-budget-v4")
        self.assertFalse(frame["full_frame_proved"])
        self.assertTrue(
            frame["current_bridge"][
                "successful_chunk_prefixes_may_publish_before_vm_completion"])
        self.assertFalse(
            frame["current_bridge"][
                "compatible_with_v4_atomic_whole_frame_commit"])
        blockers = {item["code"] for item in self.result["live_blockers"]}
        self.assertIn("PZTB008", blockers)


if __name__ == "__main__":
    unittest.main()
