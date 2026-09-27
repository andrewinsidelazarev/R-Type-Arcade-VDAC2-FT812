#!/usr/bin/env python3
"""Tests for the generic banked CPU/TS physical-memory validator."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "Source" / "Tools"
sys.path.insert(0, str(TOOLS))

from pyz80_compiler import CompileError  # noqa: E402
from pyz80_compiler.memory import (  # noqa: E402
    CPU_ADDRESS_SPACE,
    MEMORY_LAYOUT_FORMAT,
    TS_PAGE_SIZE,
    TS_PHYSICAL_PAGE_COUNT,
    LifecycleOverlay,
    MemoryLayout,
    MemoryRegion,
    PhysicalPageRange,
    PhysicalAllocation,
    VmaRange,
    load_memory_layout,
    validate_physical_allocations,
)


MANIFEST = TOOLS / "rtype_memory_layout.json"


def _layout(
        *regions: MemoryRegion,
        overlays: tuple[LifecycleOverlay, ...] = (),
        ) -> MemoryLayout:
    return MemoryLayout(
        format=MEMORY_LAYOUT_FORMAT,
        cpu_address_space=CPU_ADDRESS_SPACE,
        physical_page_size=TS_PAGE_SIZE,
        physical_page_count=TS_PHYSICAL_PAGE_COUNT,
        regions=tuple(regions),
        lifecycle_overlays=overlays,
    )


def _region(name: str, *, vma: tuple[int, int], pages: tuple[int, int]
            ) -> MemoryRegion:
    return MemoryRegion(
        name=name,
        purpose=name,
        vma=VmaRange(*vma),
        physical_pages=(PhysicalPageRange(*pages),),
    )


class PyZ80MemoryTests(unittest.TestCase):
    def test_project_manifest_has_the_proposed_non_overlapping_pages(self) -> None:
        layout, report = load_memory_layout(MANIFEST)

        expected = {
            "fixed-tables": ((0x00, 0x00),),
            "core-slot1": ((0x05, 0x05),),
            "core-slot2": ((0x06, 0x06),),
            "object-code": ((0x0A, 0x0D),),
            "loader-code": ((0x0E, 0x0E),),
            "rawpak-buffer": ((0x0F, 0x0F),),
            "bootstrap-assets": ((0x10, 0x48),),
            "active-stage": ((0x49, 0x76),),
            "sprite-rom": ((0x77, 0xAF), (0xDE, 0xE4)),
            "stage-staging": ((0xB0, 0xDD),),
            "collision-code": ((0xE5, 0xE5),),
            "fixed-player-code": ((0xE6, 0xE6),),
            "python-lut": ((0xE7, 0xE7),),
            "charge-beam-assets": ((0xE8, 0xEB),),
            "sprite-metadata": ((0xEC, 0xEC),),
            "ft812-render-queues": ((0xED, 0xEE),),
            "ft812-command-templates": ((0xEF, 0xEF),),
            "compiler-code": ((0xF0, 0xFF),),
        }
        actual = {
            region.name: tuple(
                (page_range.first, page_range.last)
                for page_range in region.physical_pages)
            for region in layout.regions
        }
        self.assertEqual(actual, expected)
        self.assertEqual(report.vma_overlays, (
            "slot2-runtime-page", "slot3-stream-page"))
        self.assertEqual(report.physical_overlays, ())
        self.assertEqual(report.owners_of_page(0x49), ("active-stage",))
        self.assertEqual(report.owners_of_page(0xB0), ("stage-staging",))
        self.assertEqual(report.owners_of_page(0xE7), ("python-lut",))
        self.assertEqual(report.owners_of_page(0xEC), ("sprite-metadata",))
        self.assertEqual(
            report.owners_of_page(0xEF), ("ft812-command-templates",))

    def test_concrete_allocations_must_stay_inside_owner_region(self) -> None:
        layout, _ = load_memory_layout(MANIFEST)
        report = validate_physical_allocations(layout, (
            PhysicalAllocation("title", "bootstrap-assets", (0x10, 0x11)),
            PhysicalAllocation("stage", "active-stage", (0x49, 0x4A)),
        ))
        self.assertEqual(report.page_allocations[0x10], ("title",))
        self.assertEqual(report.page_allocations[0x49], ("stage",))

        with self.assertRaises(CompileError) as raised:
            validate_physical_allocations(layout, (
                PhysicalAllocation("escaped", "bootstrap-assets", (0x49,)),
            ))
        self.assertEqual(raised.exception.diagnostic.code, "PZ1213")

    def test_concrete_allocations_cannot_share_one_page(self) -> None:
        layout, _ = load_memory_layout(MANIFEST)
        with self.assertRaises(CompileError) as raised:
            validate_physical_allocations(layout, (
                PhysicalAllocation("first", "bootstrap-assets", (0x10,)),
                PhysicalAllocation("second", "bootstrap-assets", (0x10,)),
            ))
        self.assertEqual(raised.exception.diagnostic.code, "PZ1214")

    def test_cpu_vma_overlap_is_rejected_without_named_lifecycle(self) -> None:
        layout = _layout(
            _region("first", vma=(0x8000, 0xC000), pages=(0x10, 0x10)),
            _region("second", vma=(0x8000, 0xC000), pages=(0x11, 0x11)),
        )
        with self.assertRaises(CompileError) as raised:
            layout.validate()
        self.assertEqual(raised.exception.diagnostic.code, "PZ1210")
        self.assertIn("$8000..$BFFF", str(raised.exception))

    def test_named_vma_lifecycle_allows_only_its_members(self) -> None:
        regions = (
            _region("first", vma=(0x8000, 0xC000), pages=(0x10, 0x10)),
            _region("second", vma=(0x8000, 0xC000), pages=(0x11, 0x11)),
        )
        overlay = LifecycleOverlay(
            name="slot2",
            domain="vma",
            lifecycle="one mapped page at a time",
            members=frozenset(("first", "second")),
        )
        report = _layout(*regions, overlays=(overlay,)).validate()
        self.assertEqual(report.vma_overlays, ("slot2",))
        self.assertEqual(report.owners_of_page(0x10), ("first",))
        self.assertEqual(report.owners_of_page(0x11), ("second",))

    def test_vma_lifecycle_does_not_hide_a_physical_collision(self) -> None:
        regions = (
            _region("first", vma=(0x8000, 0xC000), pages=(0x10, 0x10)),
            _region("second", vma=(0x8000, 0xC000), pages=(0x10, 0x10)),
        )
        overlay = LifecycleOverlay(
            name="slot2",
            domain="vma",
            lifecycle="one mapped page at a time",
            members=frozenset(("first", "second")),
        )
        with self.assertRaises(CompileError) as raised:
            _layout(*regions, overlays=(overlay,)).validate()
        self.assertEqual(raised.exception.diagnostic.code, "PZ1211")
        self.assertIn("#10", str(raised.exception))

    def test_physical_overlap_requires_its_own_named_lifecycle(self) -> None:
        regions = (
            _region("boot", vma=(0x4000, 0x5000), pages=(0x20, 0x20)),
            _region("game", vma=(0x5000, 0x6000), pages=(0x20, 0x20)),
        )
        overlay = LifecycleOverlay(
            name="boot-to-game",
            domain="physical",
            lifecycle="boot image is discarded before game image is loaded",
            members=frozenset(("boot", "game")),
        )
        report = _layout(*regions, overlays=(overlay,)).validate()
        self.assertEqual(report.physical_overlays, ("boot-to-game",))
        self.assertEqual(report.owners_of_page(0x20), ("boot", "game"))

    def test_adjacent_half_open_vma_ranges_do_not_overlap(self) -> None:
        report = _layout(
            _region("low", vma=(0x4000, 0x8000), pages=(0x30, 0x30)),
            _region("high", vma=(0x8000, 0xC000), pages=(0x31, 0x31)),
        ).validate()
        self.assertEqual(report.owners_of_page(0x30), ("low",))
        self.assertEqual(report.owners_of_page(0x31), ("high",))

    def test_overlay_cannot_reference_an_unknown_region(self) -> None:
        region = _region(
            "known", vma=(0x8000, 0xC000), pages=(0x40, 0x40))
        overlay = LifecycleOverlay(
            name="bad",
            domain="vma",
            lifecycle="invalid test lifecycle",
            members=frozenset(("known", "missing")),
        )
        with self.assertRaises(CompileError) as raised:
            _layout(region, overlays=(overlay,)).validate()
        self.assertEqual(raised.exception.diagnostic.code, "PZ1208")

    def test_duplicate_pages_inside_one_region_are_rejected(self) -> None:
        region = MemoryRegion(
            name="duplicate",
            purpose="duplicate",
            vma=VmaRange(0x8000, 0xC000),
            physical_pages=(
                PhysicalPageRange(0x50, 0x51),
                PhysicalPageRange(0x51, 0x52),
            ),
        )
        with self.assertRaises(CompileError) as raised:
            _layout(region).validate()
        self.assertEqual(raised.exception.diagnostic.code, "PZ1205")

    def test_json_loader_rejects_wrong_ts_page_size(self) -> None:
        payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
        payload["physical_page_size"] = 8192
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "layout.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(CompileError) as raised:
                MemoryLayout.load(path)
        self.assertEqual(raised.exception.diagnostic.code, "PZ1202")


if __name__ == "__main__":
    unittest.main()
