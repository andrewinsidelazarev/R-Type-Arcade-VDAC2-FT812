#!/usr/bin/env python3
"""Focused tests for the complete source-derived HQT3 catalogue."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from check_pyz80_full_hqt3_inventory import validate_report
from pyz80_compiler.full_hqt3_inventory import (
    FULL_HQT3_INVENTORY_FORMAT,
    FULL_HQT3_INVENTORY_STATUS,
    HQT3_RECORD_BYTES,
    HQT3_RECORD_STRUCT_FORMAT,
    FullHQT3InventoryError,
    concrete_templates_for_pairs,
    fixed_hqt3_bytes,
    validate_descriptor_witnesses,
)
from pyz80_compiler.sprite_coverage import (
    DescriptorRef,
    DescriptorResourcePair,
    PythonBankKey,
)


ROOT = Path(__file__).resolve().parents[2]
STATUS = ROOT / "Build" / "rtype_python_full_hqt3_inventory_status.json"


def _descriptor(address: int, code: int, *, width: int = 1) -> DescriptorRef:
    return DescriptorRef(
        address=address, dx=-2, dy=3, code=code, attribute=0,
        width=width, height=1, flip_x=False, flip_y=False)


class FullHQT3InventoryTests(unittest.TestCase):
    def test_relation_aliases_collapse_only_same_concrete_key(self) -> None:
        descriptor = _descriptor(0x1234, 0x20, width=2)
        fallback = PythonBankKey("palette-fallback", 3)
        typed = PythonBankKey("typed-resource", 0x21)
        pairs = (
            DescriptorResourcePair(0x20, descriptor, (fallback,)),
            DescriptorResourcePair(0x21, descriptor, (fallback, typed)),
        )
        templates = concrete_templates_for_pairs(pairs)
        self.assertEqual(len(templates), 2)
        by_bank = {item.bank: item for item in templates}
        self.assertEqual(by_bank[fallback].resource_types, (0x20, 0x21))
        self.assertEqual(by_bank[typed].resource_types, (0x21,))
        self.assertEqual(by_bank[fallback].cell_count, 2)
        self.assertEqual(
            by_bank[fallback].semantic_row()["append_words_conservative_max"],
            8)

    def test_same_resolver_key_cannot_hide_descriptor_disagreement(self) -> None:
        bank = PythonBankKey("typed-resource", 1)
        pairs = (
            DescriptorResourcePair(1, _descriptor(0x1000, 1), (bank,)),
            DescriptorResourcePair(1, _descriptor(0x1000, 2), (bank,)),
        )
        with self.assertRaisesRegex(
                FullHQT3InventoryError, "different ROM descriptors"):
            concrete_templates_for_pairs(pairs)

    def test_hqt3_fixed_bytes_are_exact_and_state_bytes_stay_separate(
            self) -> None:
        bank = PythonBankKey("typed-resource", 1)
        templates = concrete_templates_for_pairs((
            DescriptorResourcePair(
                1, _descriptor(0x1000, 1, width=2), (bank,)),
            DescriptorResourcePair(1, _descriptor(0x1006, 3), (bank,)),
        ))
        size = fixed_hqt3_bytes(templates)
        self.assertEqual(size["record_count"], 2)
        self.assertEqual(size["cell_count"], 3)
        self.assertEqual(HQT3_RECORD_STRUCT_FORMAT, "<HBBHhhHBBHH")
        self.assertEqual(HQT3_RECORD_BYTES, 18)
        self.assertEqual(size["record_bytes"], 36)
        self.assertEqual(size["cell_bytes"], 27)
        self.assertEqual(size["fixed_bytes_excluding_state_table"], 83)
        self.assertEqual(size["state_record_bytes"], 8)

    def test_descriptor_witness_is_independent_of_coverage_object(self) -> None:
        rom = bytearray(0x100000)
        base = 0x10000 + 0x2000
        rom[base:base + 6] = bytes((0xFE, 3, 0x20, 0, 0, 0))
        expected = _descriptor(0x2000, 0x20)
        proof = validate_descriptor_witnesses(bytes(rom), (expected,))
        self.assertEqual(proof["descriptor_count"], 1)
        with self.assertRaisesRegex(
                FullHQT3InventoryError, "differs from active ROM"):
            validate_descriptor_witnesses(
                bytes(rom), (_descriptor(0x2000, 0x21),))

    def test_active_status_preserves_hqt_blocker_and_nonrendering_proof(
            self) -> None:
        value = json.loads(STATUS.read_text(encoding="utf-8"))
        validate_report(value)
        self.assertEqual(value["format"], FULL_HQT3_INVENTORY_FORMAT)
        self.assertEqual(value["status"], FULL_HQT3_INVENTORY_STATUS)
        self.assertTrue(value["inventory_complete"])
        self.assertFalse(value["live"])
        catalog = value["global_catalog"]
        current = value["current_bootstrap_hqt3"]
        crosscheck = value["frame_sprite_fragment_envelope_crosscheck"]
        self.assertEqual(catalog["template_count"], 10776)
        self.assertEqual(current["record_count"], 40)
        self.assertEqual(current["outside_active_coverage_count"], 4)
        self.assertEqual(current["covered_active_template_count"], 36)
        self.assertEqual(current["missing_template_count"], 10740)
        self.assertEqual(
            crosscheck["missing_from_current_hqt3_count"], 6922)
        self.assertTrue(
            crosscheck["missing_current_identities_present_in_full_catalog"])
        self.assertEqual(
            crosscheck["unresolved_empty_draw_action_domain_count"], 0)
        self.assertEqual(
            crosscheck["source_proved_nonrendering_witness_count"], 19)
        self.assertTrue(crosscheck["empty_draw_action_domains_resolved"])
        self.assertEqual(value["load_plan"]["resident_combinations"], [])


if __name__ == "__main__":
    unittest.main()
