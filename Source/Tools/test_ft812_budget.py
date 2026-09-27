#!/usr/bin/env python3
"""Unit tests for the conservative FT812 RAM_DL line-budget analyser."""

from __future__ import annotations

import struct
import unittest

from pyz80_compiler.ft812_budget import (
    MAX_DL_WORDS,
    FT812Bitmap,
    FT812BudgetError,
    FT812Timing,
    analyze_display_list,
    bitmap_pixels_per_clock,
    expand_coprocessor_stream,
)


def dl(*words: int, pad_words: int = 0) -> bytes:
    values = words + ((0x2D << 24),) * pad_words
    return b"".join(struct.pack("<I", word & 0xFFFFFFFF) for word in values)


def op(code: int, value: int = 0) -> int:
    return (code << 24) | value


def bitmap_layout(format_code: int, stride: int, height: int) -> int:
    return op(0x07, (format_code << 19) | ((stride & 0x3FF) << 9) | (height & 0x1FF))


def bitmap_layout_h(stride: int, height: int) -> int:
    return op(0x28, (((stride >> 10) & 3) << 2) | ((height >> 9) & 3))


def bitmap_size(filter_mode: int, width: int, height: int) -> int:
    return op(0x08, (filter_mode << 20) | ((width & 0x1FF) << 9) | (height & 0x1FF))


def bitmap_size_h(width: int, height: int) -> int:
    return op(0x29, (((width >> 9) & 3) << 2) | ((height >> 9) & 3))


def vertex2f(x: int, y: int) -> int:
    return (1 << 30) | ((x & 0x7FFF) << 15) | (y & 0x7FFF)


def vertex2ii(x: int, y: int, handle: int, cell: int = 0) -> int:
    return (
        (1 << 31)
        | ((x & 0x1FF) << 21)
        | ((y & 0x1FF) << 12)
        | ((handle & 0x1F) << 7)
        | (cell & 0x7F)
    )


class FT812BudgetTests(unittest.TestCase):
    def test_coprocessor_text_is_expanded_with_rom_font_metrics(self) -> None:
        prefix = dl(
            0xFFFFFF00,                         # CMD_DLSTART
            op(0x27, 3),
            0xFFFFFF26,                         # CMD_LOADIDENTITY
            0xFFFFFF28, 0x0001999A, 0x0001999A, # CMD_SCALE(1.6, 1.6)
            0xFFFFFF2A,                         # CMD_SETMATRIX
            0xFFFFFF0C,                         # CMD_TEXT
            (711 << 16) | 914,
            26,
        )
        string = b"DIST 1234\0"
        string += bytes((-len(string)) & 3)
        expansion = expand_coprocessor_stream(prefix + string + dl(0))
        report = analyze_display_list(
            expansion.display_list,
            FT812Timing(safety_utilization=1),
        )

        self.assertEqual(expansion.text_commands, 1)
        self.assertGreater(expansion.expanded_words, expansion.input_words)
        self.assertEqual(len(report.draws), 9)
        self.assertEqual(report.draws[0].bitmap_width, 13)
        self.assertEqual(report.draws[0].bitmap_height, 26)
        self.assertEqual(report.draws[0].clipped_x0, 914)
        self.assertEqual(report.draws[-1].clipped_x1, 1024)

    def test_clear_bitmap_and_dl_walk_are_charged_per_line(self) -> None:
        timing = FT812Timing(
            width=64, height=16, hcycle=128, pclk=1,
            safety_utilization=1,
        )
        image = dl(
            op(0x26, 0x07),
            op(0x05, 2),
            op(0x01, 0x12345),
            bitmap_layout(6, 32, 4),
            bitmap_size(0, 32, 4),
            op(0x1F, 1),
            vertex2f(16, 32),  # default frac=4 -> (1, 2)
            op(0x21),
            0,
        )
        report = analyze_display_list(image, timing)

        self.assertEqual(report.word_count, 9)
        self.assertEqual(report.clear_count, 1)
        self.assertEqual(report.line_raster_cycles[0], 4)
        self.assertEqual(report.line_raster_cycles[2], 6)  # clear 4 + bitmap 2
        self.assertEqual(report.line_cycles[2], 15)         # plus all 9 DL words
        self.assertEqual(report.draws[0].source, 0x12345)
        self.assertEqual(report.draws[0].clipped_width, 32)

    def test_documented_bitmap_rates(self) -> None:
        self.assertEqual(bitmap_pixels_per_clock(6, 0), 16)
        self.assertEqual(bitmap_pixels_per_clock(15, 0), 8)
        self.assertEqual(bitmap_pixels_per_clock(9, 0), 8)
        self.assertEqual(bitmap_pixels_per_clock(6, 1), 4)
        self.assertEqual(bitmap_pixels_per_clock(14, 1), 2)

    def test_size_high_v2ii_and_special_bilinear_rate(self) -> None:
        timing = FT812Timing(
            width=700, height=8, hcycle=4096, pclk=1,
            safety_utilization=1,
        )
        image = dl(
            op(0x05, 7),
            bitmap_layout_h(1200, 600),
            bitmap_layout(15, 1200, 600),
            bitmap_size_h(520, 4),
            bitmap_size(1, 520, 4),
            op(0x1F, 1),
            vertex2ii(100, 1, 7, 12),
            op(0x21),
            0,
        )
        report = analyze_display_list(image, timing)
        draw = report.draws[0]

        self.assertEqual(draw.bitmap_width, 520)
        self.assertEqual(draw.bitmap_stride, 1200)
        self.assertEqual(draw.bitmap_layout_height, 600)
        self.assertEqual(draw.handle, 7)
        self.assertEqual(draw.cell, 12)
        self.assertEqual(draw.pixels_per_clock, 2)
        self.assertEqual(draw.clocks_per_covered_line, 260)

    def test_palette_source_is_exact_graphics_context_and_aligned(self) -> None:
        timing = FT812Timing(
            width=64, height=8, hcycle=128, pclk=1,
            safety_utilization=1,
        )
        image = dl(
            bitmap_layout(15, 16, 2),
            bitmap_size(0, 16, 2),
            op(0x2A, 0x120),
            op(0x22),
            op(0x2A, 0x340),
            op(0x1F, 1),
            vertex2f(0, 0),
            op(0x23),
            vertex2f(0, 32),
            op(0x21),
            0,
        )
        report = analyze_display_list(image, timing)

        self.assertEqual(
            [draw.palette_source for draw in report.draws],
            [0x340, 0x120],
        )

        bad = dl(
            bitmap_layout(15, 16, 2),
            bitmap_size(0, 16, 2),
            op(0x2A, 0x121),
            op(0x1F, 1),
            vertex2f(0, 0),
            op(0x21),
            0,
        )
        with self.assertRaises(FT812BudgetError) as caught:
            analyze_display_list(bad, timing)
        self.assertEqual(caught.exception.code, "FT812_PALETTE_ALIGNMENT")

    def test_vertex_format_signed_translation_scissor_and_restore(self) -> None:
        timing = FT812Timing(
            width=80, height=16, hcycle=256, pclk=1,
            safety_utilization=1,
        )
        image = dl(
            op(0x05, 1),
            bitmap_layout(6, 32, 4),
            bitmap_size(0, 32, 4),
            op(0x27, 3),                       # VERTEX_FORMAT(3)
            op(0x2B, (-16) & 0x1FFFF),        # translate -1 pixel
            op(0x22),                          # SAVE_CONTEXT
            op(0x1B, (20 << 11) | 0),         # scissor starts at x=20
            op(0x2B, 0),
            op(0x1F, 1),
            vertex2f(80, 8),                   # (10,1), clipped to x=20..42
            op(0x23),                          # restore translate=-1, full clip
            vertex2f(80, 48),                  # (9,6) after translation
            op(0x21),
            0,
        )
        report = analyze_display_list(image, timing)

        self.assertEqual(report.draws[0].clipped_x0, 20)
        self.assertEqual(report.draws[0].clipped_width, 22)
        self.assertEqual(report.draws[1].x_sixteenths, 9 * 16)
        self.assertEqual(report.draws[1].clipped_x0, 9)
        self.assertEqual(report.draws[1].clipped_y0, 6)

    def test_bitmap_parameters_are_not_part_of_saved_context(self) -> None:
        timing = FT812Timing(
            width=64, height=8, hcycle=128, pclk=1,
            safety_utilization=1,
        )
        image = dl(
            op(0x05, 3),
            bitmap_layout(6, 8, 2),
            bitmap_size(0, 8, 2),
            op(0x22),
            bitmap_size(0, 24, 2),
            op(0x23),
            op(0x1F, 1),
            vertex2f(0, 0),
            op(0x21),
            0,
        )
        report = analyze_display_list(image, timing)
        self.assertEqual(report.draws[0].bitmap_width, 24)

    def test_external_handle_state_supports_rom_or_persistent_handles(self) -> None:
        timing = FT812Timing(
            width=64, height=8, hcycle=128, pclk=1,
            safety_utilization=1,
        )
        image = dl(op(0x1F, 1), vertex2ii(2, 3, 31, 65), op(0x21), 0)
        report = analyze_display_list(
            image,
            timing,
            initial_bitmaps={31: FT812Bitmap(format=9, width=8, height=8)},
        )
        self.assertEqual(report.draws[0].handle, 31)
        self.assertEqual(report.draws[0].clocks_per_covered_line, 1)

    def test_safety_margin_and_physical_overflow_have_stable_codes(self) -> None:
        image = dl(
            op(0x05, 0),
            bitmap_layout(15, 64, 2),
            bitmap_size(0, 64, 2),
            op(0x1F, 1),
            vertex2f(0, 0),
            op(0x21),
            0,
        )
        safety_timing = FT812Timing(
            width=64, height=2, hcycle=16, pclk=1,
            safety_utilization=0.75,
        )
        report = analyze_display_list(image, safety_timing, fail_on_budget=False)
        self.assertFalse(report.passed)
        self.assertEqual(report.worst_cycles, 15)  # 7 words + 64/8 raster clocks
        with self.assertRaises(FT812BudgetError) as caught:
            analyze_display_list(image, safety_timing)
        self.assertEqual(caught.exception.code, "FT812_SAFETY_MARGIN")
        self.assertIsNotNone(caught.exception.report)
        assert caught.exception.report is not None
        self.assertEqual(caught.exception.report.worst_cycles, 15)

        physical_timing = replace_timing(safety_timing, safety_utilization=1)
        # Two overlapping draws need 23 clocks, beyond the physical 16.
        original_words = struct.unpack("<7I", image)
        doubled = dl(*original_words[:5], vertex2f(0, 0), *original_words[5:])
        with self.assertRaises(FT812BudgetError) as caught_physical:
            analyze_display_list(doubled, physical_timing)
        self.assertEqual(caught_physical.exception.code, "FT812_LINE_OVERFLOW")

    def test_invalid_lists_have_stable_diagnostics(self) -> None:
        cases = (
            (b"x", "FT812_DL_ALIGNMENT"),
            (dl(op(0x2D)), "FT812_DISPLAY_MISSING"),
            (dl(op(0x1D), 0), "FT812_CONTROL_FLOW_UNSUPPORTED"),
            (dl(op(0x27, 5), 0), "FT812_VERTEX_FORMAT"),
            (dl(op(0x1F, 1), vertex2f(0, 0), 0), "FT812_BITMAP_STATE"),
        )
        for image, code in cases:
            with self.subTest(code=code), self.assertRaises(FT812BudgetError) as caught:
                analyze_display_list(image)
            self.assertEqual(caught.exception.code, code)

    def test_display_list_must_use_fewer_than_2048_words(self) -> None:
        image = dl(*([op(0x2D)] * (MAX_DL_WORDS - 1)), 0)
        with self.assertRaises(FT812BudgetError) as caught:
            analyze_display_list(image)
        self.assertEqual(caught.exception.code, "FT812_DL_WORD_LIMIT")


def replace_timing(timing: FT812Timing, **changes: object) -> FT812Timing:
    values = {
        "width": timing.width,
        "height": timing.height,
        "hcycle": timing.hcycle,
        "pclk": timing.pclk,
        "safety_utilization": timing.safety_utilization,
    }
    values.update(changes)
    return FT812Timing(**values)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
