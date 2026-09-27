#!/usr/bin/env python3
"""Host tests for the deterministic offline arcade upscaler."""
from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path

from PIL import Image

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import xbrz_offline as upscale


class XbrzToolTests(unittest.TestCase):
    def test_official_archive_and_helper_are_hash_locked(self) -> None:
        helper = upscale.build_helper()
        self.assertTrue(helper.is_file())
        self.assertEqual(
            upscale.XBRZ_ARCHIVE_SHA256,
            upscale.sha256(upscale.ARCHIVE),
        )
        self.assertEqual(
            upscale.XBRZ_MEMBERS,
            {path.name for path in upscale.SOURCE_ROOT.iterdir()
             if path.is_file()},
        )

    def test_alpha_aware_xbrz6_lanczos_is_deterministic(self) -> None:
        image = Image.new("RGBA", (8, 6), (0, 0, 0, 0))
        pixels = image.load()
        colors = [
            (255, 0, 0, 255),
            (0, 255, 0, 255),
            (0, 64, 255, 255),
            (255, 255, 255, 128),
        ]
        for y in range(6):
            for x in range(8):
                if x == y or x == 7 - y:
                    pixels[x, y] = colors[(x + y) % len(colors)]
                elif 2 <= x <= 5 and 2 <= y <= 3:
                    pixels[x, y] = (255, 192, 0, 255)

        result = upscale.upscale_image(image, (20, 15), factor=6)
        self.assertEqual((20, 15), result.size)
        self.assertEqual(
            "5c40577e78720e4e49833a5f4718a46adb3e394fdd8bb341aa136e721a5e2e39",
            hashlib.sha256(result.tobytes()).hexdigest(),
        )
        self.assertEqual((0, 0, 0, 0), result.getpixel((19, 14)))

    def test_rgb565_is_ft812_little_endian(self) -> None:
        image = Image.new("RGB", (4, 1))
        image.putdata([
            (0, 0, 0),
            (255, 255, 255),
            (255, 0, 0),
            (0, 255, 0),
        ])
        self.assertEqual(
            bytes((0x00, 0x00, 0xFF, 0xFF, 0x00, 0xF8, 0xE0, 0x07)),
            upscale.pack_rgb565(image),
        )

    def test_opaque_xbrz_uses_rgb_edges(self) -> None:
        image = Image.new("RGBA", (3, 2), (24, 80, 160, 255))
        result = upscale.upscale_image(image, (11, 9), factor=6)
        self.assertEqual((255, 255), result.getchannel("A").getextrema())
        self.assertEqual((24, 80, 160, 255), result.getpixel((0, 0)))
        self.assertEqual((24, 80, 160, 255), result.getpixel((10, 8)))

    def test_rgb565_rejects_transparency(self) -> None:
        image = Image.new("RGBA", (1, 1), (255, 0, 255, 0))
        with self.assertRaisesRegex(ValueError, "fully opaque"):
            upscale.pack_rgb565(image)


if __name__ == "__main__":
    unittest.main(verbosity=2)
