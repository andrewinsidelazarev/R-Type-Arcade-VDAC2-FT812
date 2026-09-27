#!/usr/bin/env python3
"""Unit-проверки страничной упаковки M72 VRAM-delta."""
from __future__ import annotations

import struct
import unittest

from m72_stage_stream import PAGE_JUMP, STREAM_END, pack_stream


class StreamPackingTests(unittest.TestCase):
    def test_packet_is_moved_whole_to_next_page(self) -> None:
        events = [
            (1, [(0x0100, 3)], []),
            (2, [(0x0101, 4), (0x0102, 5)], [(0x0200, 6)]),
        ]
        packed = pack_stream(events, page_size=20)
        first_packet_size = 4 + 4
        self.assertEqual(packed[first_packet_size:first_packet_size + 4], PAGE_JUMP)
        self.assertEqual(packed[20:24], struct.pack("<HBB", 2, 2, 1))
        self.assertEqual(packed[-4:], STREAM_END)

    def test_rejects_packet_larger_than_page(self) -> None:
        with self.assertRaises(ValueError):
            pack_stream([(1, [(index, 1) for index in range(8)], [])],
                        page_size=24)

    def test_page_jump_on_exact_boundary_adds_no_blank_page(self) -> None:
        # Пакет 16 Б оставляет ровно четыре байта под marker в странице 20 Б.
        packed = pack_stream([
            (1, [(0, 1), (1, 2), (2, 3)], []),
            (2, [], []),
        ], page_size=20)
        self.assertEqual(packed[16:20], PAGE_JUMP)
        self.assertEqual(packed[20:24], struct.pack("<HBB", 2, 0, 0))


if __name__ == "__main__":
    unittest.main()
