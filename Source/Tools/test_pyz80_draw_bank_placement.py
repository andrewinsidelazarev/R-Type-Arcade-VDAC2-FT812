from __future__ import annotations

import json
import unittest
from pathlib import Path

from check_pyz80_draw_bank_placement import (
    DrawBankPlacementError,
    FORMAT,
    STATUS,
    _asm_equ,
    _extract_lookup_slices,
    _integer_define,
    _json_bytes,
    probe,
    validate_intervals,
)


ROOT = Path(__file__).resolve().parents[2]


class DrawBankPlacementPureTests(unittest.TestCase):
    def test_half_open_resident_ranges_allow_touching_boundaries(self) -> None:
        rows = validate_intervals((
            ("gate", 0x07A0, 0x0850),
            ("cache", 0x0B00, 0x1000),
            ("coordinates", 0x1000, 0x2000),
        ))
        self.assertEqual([row["name"] for row in rows], [
            "gate", "cache", "coordinates",
        ])

    def test_any_gate_cache_overlap_fails_closed(self) -> None:
        with self.assertRaises(DrawBankPlacementError):
            validate_intervals((
                ("gate", 0x07A0, 0x0B01),
                ("cache", 0x0B00, 0x1000),
            ))

    def test_stale_or_duplicate_source_constants_fail_closed(self) -> None:
        self.assertEqual(_asm_equ("PAGE EQU #F2\n", "PAGE"), 0xF2)
        with self.assertRaises(DrawBankPlacementError):
            _asm_equ("PAGE EQU #F1\nPAGE EQU #F2\n", "PAGE")
        self.assertEqual(_integer_define(
            "#define QUEUE 0xC000u\n", "QUEUE"), 0xC000)
        with self.assertRaises(DrawBankPlacementError):
            _integer_define("#define OTHER 1u\n", "QUEUE")

    def test_lookup_partition_is_exact_and_deterministic(self) -> None:
        first = _extract_lookup_slices(ROOT)
        second = _extract_lookup_slices(ROOT)
        self.assertEqual(first, second)
        self.assertIn("PyZ80FT_FindHQTemplate", first["ft_source"])
        self.assertNotIn("PyZ80FT_ResolveBankKey(", first["ft_source"])
        self.assertIn("PyZ80FT_HQTemplates", first["hq_source"])
        self.assertIn("PyZ80FT_HQTemplateHash", first["hq_source"])
        self.assertNotIn("PyZ80FT_HQBatchGeometry", first["hq_source"])


class DrawBankPlacementIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = probe(ROOT)

    def test_report_is_deterministic_and_checked_in(self) -> None:
        path = ROOT / "Build/rtype_python_draw_bank_placement_status.json"
        self.assertEqual(path.read_bytes(), _json_bytes(self.result))
        self.assertEqual(
            json.loads(path.read_text(encoding="utf-8")), self.result)

    def test_actual_two_bank_links_fit_without_data_overlap(self) -> None:
        result = self.result
        self.assertEqual(result["format"], FORMAT)
        self.assertEqual(result["status"], STATUS)
        unsplit = result["unsplit_source_derived_bundle"]
        self.assertEqual(unsplit["code_bytes"], 17137)
        self.assertEqual(unsplit["data_bytes"], 1280)
        self.assertEqual(unsplit["single_bank_overflow_bytes"], 753)
        page_f1 = result["links"]["page_f1"]
        page_f2 = result["links"]["page_f2"]
        self.assertEqual(page_f1["code"]["bytes"], 13899)
        self.assertEqual(page_f2["code"]["bytes"], 4349)
        self.assertTrue(page_f1["code"]["fits_one_bank"])
        self.assertTrue(page_f2["code"]["fits_one_bank"])
        self.assertEqual(page_f1["data"]["bytes"], 0)
        self.assertEqual(page_f2["data"], {
            "origin_hex": "0x0B00",
            "end_exclusive_hex": "0x1000",
            "bytes": 1280,
        })

    def test_physical_pages_and_ft812_storage_are_exact(self) -> None:
        memory = self.result["memory"]
        self.assertEqual(memory["physical_ram_bytes"], 4 * 1024 * 1024)
        self.assertEqual(memory["existing_compiler_page"]["page_hex"], "0xF0")
        self.assertEqual(
            [row["page_hex"] for row in memory["draw_code_banks"]],
            ["0xF1", "0xF2"])
        storage = self.result["ft812_storage"]
        self.assertEqual(storage["queue_pages"], ["0xED", "0xEE"])
        self.assertEqual(storage["queue_vma"]["start_hex"], "0xC000")
        self.assertEqual(storage["queue_vma"]["bytes"], 0x4000)
        self.assertEqual(storage["record_tail"]["start_hex"], "0xCA44")
        self.assertEqual(storage["record_tail"]["end_exclusive_hex"], "0x10000")
        self.assertEqual(storage["batch_cache"]["start_hex"], "0x0B00")
        self.assertEqual(storage["batch_cache"]["end_exclusive_hex"], "0x1000")
        self.assertEqual(storage["command_template_page_hex"], "0xEF")

    def test_cross_bank_abi_has_one_tail_edge_and_linked_entry(self) -> None:
        edges = self.result["source_partition"]["cross_bank_edges"]
        self.assertEqual(len(edges), 1)
        edge = edges[0]
        self.assertEqual((edge["from_page_hex"], edge["to_page_hex"]),
                         ("0xF1", "0xF2"))
        self.assertEqual(edge["callee_entry_address_hex"], "0x8000")
        self.assertIn("tail JP", edge["abi"])
        gate = self.result["resident_gate"]
        self.assertEqual(gate["origin_hex"], "0x07A0")
        self.assertLessEqual(int(gate["end_exclusive_hex"], 16), 0x0B00)
        self.assertGreater(gate["headroom_bytes"], 0)
        self.assertEqual(self.result["memory"]["mmu_services"], {
            "Memory.GetPage2": {"address_hex": "0x0014"},
            "Memory.SetPage2": {"address_hex": "0x0010"},
        })

    def test_final_binding_and_live_claim_remain_fail_closed(self) -> None:
        self.assertFalse(self.result["live"])
        evidence = self.result["final_binding_evidence"]
        self.assertFalse(evidence["proved"])
        self.assertIsNone(evidence["final_link_map_path"])
        self.assertIsNone(evidence["callback_binding_symbols"])
        checks = self.result["checks"]
        self.assertFalse(checks["real_final_link_proved"])
        self.assertFalse(checks["production_packer_binding_proved"])
        self.assertFalse(checks["live_callback_binding_proved"])
        self.assertFalse(checks["isr_preemption_composition_proved"])
        self.assertEqual(
            {row["code"] for row in self.result["live_blockers"]},
            {"PZBP001", "PZBP002", "PZBP003", "PZBP004", "PZBP005",
             "PZBP006"})


if __name__ == "__main__":
    unittest.main()

