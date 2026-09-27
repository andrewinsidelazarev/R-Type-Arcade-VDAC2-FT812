#!/usr/bin/env python3
"""Host tests for the byte-exact M72 arcade extractor."""
from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import m72_arcade as m72


class ManifestTests(unittest.TestCase):
    def test_all_supplied_roms_match(self) -> None:
        self.assertEqual([], m72.verify_roms(quiet=True))

    def test_manifest_is_unique(self) -> None:
        self.assertEqual(len(m72.ROMS), len({x.local_name for x in m72.ROMS}))
        self.assertEqual(len(m72.ROMS), len({x.mame_name for x in m72.ROMS}))


class RegionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.regions = m72.assemble_regions()

    def test_region_sizes(self) -> None:
        self.assertEqual(0x100000, len(self.regions["maincpu"]))
        self.assertEqual(0x80000, len(self.regions["sprites"]))
        self.assertEqual(0x20000, len(self.regions["tiles0"]))
        self.assertEqual(0x20000, len(self.regions["tiles1"]))

    def test_maincpu_interleave_and_reload(self) -> None:
        low0 = (m72.ROM_DIR / "rt_r-l0-b.3b").read_bytes()
        high0 = (m72.ROM_DIR / "rt_r-h0-b.1b").read_bytes()
        low1 = (m72.ROM_DIR / "rt_r-l1-b.3c").read_bytes()
        high1 = (m72.ROM_DIR / "rt_r-h1-b.1c").read_bytes()
        main = self.regions["maincpu"]
        self.assertEqual(low0, main[0x00000:0x20000:2])
        self.assertEqual(high0, main[0x00001:0x20001:2])
        self.assertEqual(low1, main[0x20000:0x40000:2])
        self.assertEqual(high1, main[0x20001:0x40001:2])
        self.assertEqual(low1, main[0xE0000:0x100000:2])
        self.assertEqual(high1, main[0xE0001:0x100001:2])

    def test_sprite_rom_reload(self) -> None:
        sprites = self.regions["sprites"]
        self.assertEqual(sprites[0x10000:0x18000], sprites[0x18000:0x20000])
        self.assertEqual(sprites[0x30000:0x38000], sprites[0x38000:0x40000])
        self.assertEqual(sprites[0x50000:0x58000], sprites[0x58000:0x60000])
        self.assertEqual(sprites[0x70000:0x78000], sprites[0x78000:0x80000])

    def test_regions_have_stable_hashes(self) -> None:
        # These hashes lock down assembly offsets/reloads independently of PNG.
        expected = {
            "maincpu": "6322ab95d854c2cff75ff91eee29699deed4a7d677a9e413d49a598c647a34b2",
            "sprites": "47072309ae1b8531e48dc45ae17ff1b5f213a33525ba526b636659e2f594d910",
            "tiles0": "c4d290bf39bf9bcc97595b2f1b4168fb247032aee378548607f045d0b1a1007c",
            "tiles1": "411744b9f5fa9261c12d12afcd72a5d773399cae459ca01c6c0867d8c567c83f",
        }
        actual = {name: hashlib.sha256(data).hexdigest()
                  for name, data in self.regions.items()}
        self.assertEqual(expected, actual)


class DecodeTests(unittest.TestCase):
    def test_nibble_pack_round_trip(self) -> None:
        pixels = bytes(range(16)) * 17
        self.assertEqual(pixels, m72.unpack_nibbles(m72.pack_nibbles(pixels)))

    def test_tile_plane_order_and_msb_x_order(self) -> None:
        region = bytearray(32)
        quarter = 8
        # Plane 0, x=0 -> pen 1. Plane 3, x=7 -> pen 8.
        region[0 * quarter + 0] = 0x80
        region[3 * quarter + 0] = 0x01
        pixels = m72.decode_tile(bytes(region), 0)
        self.assertEqual(1, pixels[0])
        self.assertEqual(8, pixels[7])
        self.assertEqual(0, pixels[8])

    def test_sprite_second_half_x_offset(self) -> None:
        region = bytearray(128)
        quarter = 32
        region[1 * quarter + 0] = 0x80       # x=0, y=0, pen bit 1
        region[2 * quarter + 16] = 0x80      # x=8, y=0, pen bit 2
        pixels = m72.decode_sprite(bytes(region), 0)
        self.assertEqual(2, pixels[0])
        self.assertEqual(4, pixels[8])
        self.assertEqual(0, pixels[16])


if __name__ == "__main__":
    unittest.main(verbosity=2)
