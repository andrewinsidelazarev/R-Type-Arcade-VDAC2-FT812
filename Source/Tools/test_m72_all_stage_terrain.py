"""Регрессия точного ROM-конвертера ландшафтов восьми stages."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "Source" / "Tools"
PYTHON = ROOT / "Source" / "Python"
for directory in (TOOLS, PYTHON):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from m72_all_stage_terrain import (ROM_PATH, apply_strip, blank_vram, build,
                                   checkpoints, decode_strip,
                                   stage_source_bounds)
from rtype_port.stage import M72Tilemaps


class AllStageTerrainTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rom = ROM_PATH.read_bytes()

    def test_all_descriptor_streams_are_partitioned_without_gaps(self) -> None:
        points = checkpoints(self.rom)
        expected = ((0, 4200), (0, 5240))
        for layer_name, whole in zip(("foreground", "background"), expected,
                                     strict=True):
            ranges = [stage_source_bounds(points, stage, layer_name)
                      for stage in range(1, 9)]
            self.assertEqual(whole[0], ranges[0][0])
            self.assertEqual(whole[1], ranges[-1][1])
            self.assertTrue(all(left[1] == right[0]
                                for left, right in zip(ranges, ranges[1:])))

    def test_stage1_preload_matches_existing_rom_interpreter(self) -> None:
        expected = M72Tilemaps()
        for layer in range(2):
            actual = blank_vram(layer)
            # Stage-1 constructor models frames 723..851: the seven F01B
            # preload strips plus one FG/two BG crossings before frame 852.
            strip_count = expected.source[layer] // 10
            for index in range(strip_count):
                apply_strip(actual, index * 0x10,
                            decode_strip(self.rom, layer, index * 10))
            self.assertEqual(expected.vram[layer], actual)

    def test_manifest_covers_all_events_and_stages(self) -> None:
        # Unit tests must not rewrite generated assets: autocheck may run in
        # parallel and must always observe an immutable artifact set.
        manifest = build(write_outputs=False)
        self.assertEqual(8, manifest["stage_count"])
        self.assertEqual(788, manifest["event_count"])
        self.assertEqual([1, 2, 3, 4, 5, 6, 7, 8],
                         [item["stage"] for item in manifest["stages"]])


if __name__ == "__main__":
    unittest.main()
