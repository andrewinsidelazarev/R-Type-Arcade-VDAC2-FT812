"""Conservative FT812 display-list scanline budget analysis.

The FT81x display-list engine walks the complete list for every scanline.  A
list word therefore costs one internal clock on every line, even when it only
changes graphics state.  Raster work is added to that fixed cost for CLEAR and
BITMAPS vertices.

This module deliberately rejects display-list control flow and drawing
primitives other than BITMAPS.  Silently ignoring either would make a budget
check optimistic, which is unsafe for a build-time validator.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from fractions import Fraction
import math
import struct
from typing import Mapping


MAX_DL_WORDS = 2048

# FT81x display-list opcodes used by the analyser.
_DISPLAY = 0x00
_BITMAP_SOURCE = 0x01
_BITMAP_HANDLE = 0x05
_CELL = 0x06
_BITMAP_LAYOUT = 0x07
_BITMAP_SIZE = 0x08
_POINT_SIZE = 0x0D
_LINE_WIDTH = 0x0E
_SCISSOR_XY = 0x1B
_SCISSOR_SIZE = 0x1C
_CALL = 0x1D
_JUMP = 0x1E
_BEGIN = 0x1F
_END = 0x21
_SAVE_CONTEXT = 0x22
_RESTORE_CONTEXT = 0x23
_RETURN = 0x24
_MACRO = 0x25
_CLEAR = 0x26
_VERTEX_FORMAT = 0x27
_BITMAP_LAYOUT_H = 0x28
_BITMAP_SIZE_H = 0x29
_PALETTE_SOURCE = 0x2A
_VERTEX_TRANSLATE_X = 0x2B
_VERTEX_TRANSLATE_Y = 0x2C

_BITMAPS = 1
_RECTS = 9

FORMAT_NAMES: Mapping[int, str] = {
    0: "ARGB1555",
    1: "L1",
    2: "L4",
    3: "L8",
    4: "RGB332",
    5: "ARGB2",
    6: "ARGB4",
    7: "RGB565",
    8: "PALETTED",
    9: "TEXT8X8",
    10: "TEXTVGA",
    11: "BARGRAPH",
    14: "PALETTED565",
    15: "PALETTED4444",
    16: "PALETTED8",
    17: "L2",
}

# BRT's published FT81x rates: these formats need two clocks per 16 pixels.
_SLOW_FORMATS = frozenset((9, 10, 14, 15))


class FT812BudgetError(RuntimeError):
    """A malformed, unsupported, or over-budget FT812 display list."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        word_index: int | None = None,
        report: "FT812BudgetReport | None" = None,
    ) -> None:
        self.code = code
        self.message = message
        self.word_index = word_index
        self.report = report
        where = "" if word_index is None else f" at DL word {word_index}"
        super().__init__(f"{code}{where}: {message}")


@dataclass(frozen=True)
class FT812Timing:
    """Physical FT812 timing and the accepted scanline utilisation.

    ``pclk`` is the REG_PCLK divisor.  The fail-closed VDAC2 model uses exactly
    ``hcycle * pclk`` clocks per line.  The separate 2048 value is the RAM_DL
    instruction-count limit, not extra scanline execution time.
    """

    width: int = 1024
    height: int = 768
    hcycle: int = 1344
    pclk: int = 1
    safety_utilization: float = 0.90

    def __post_init__(self) -> None:
        integer_fields = {
            "width": self.width,
            "height": self.height,
            "hcycle": self.hcycle,
            "pclk": self.pclk,
        }
        for name, value in integer_fields.items():
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise FT812BudgetError(
                    "FT812_BAD_TIMING", f"{name} must be a positive integer"
                )
        if (
            not isinstance(self.safety_utilization, (int, float))
            or isinstance(self.safety_utilization, bool)
            or not math.isfinite(float(self.safety_utilization))
            or not 0 < float(self.safety_utilization) <= 1
        ):
            raise FT812BudgetError(
                "FT812_BAD_TIMING", "safety_utilization must be in (0, 1]"
            )

    @property
    def line_cycles(self) -> int:
        return self.hcycle * self.pclk

    @property
    def safe_line_cycles(self) -> int:
        utilization = Fraction(str(self.safety_utilization))
        return (self.line_cycles * utilization.numerator) // utilization.denominator


@dataclass(frozen=True)
class FT812Bitmap:
    """Bitmap-handle state, also usable for externally configured ROM handles."""

    source: int | None = None
    format: int | None = None
    stride: int | None = None
    layout_height: int | None = None
    width: int | None = None
    height: int | None = None
    filter: int = 0
    wrap_x: int = 0
    wrap_y: int = 0


@dataclass(frozen=True)
class FT812DrawCost:
    """Raster contribution made by one bitmap vertex."""

    word_index: int
    vertex_kind: str
    handle: int
    cell: int
    source: int | None
    palette_source: int
    format: int
    filter: int
    bitmap_stride: int | None
    bitmap_layout_height: int | None
    x_sixteenths: int
    y_sixteenths: int
    bitmap_width: int
    bitmap_height: int
    clipped_x0: int
    clipped_y0: int
    clipped_x1: int
    clipped_y1: int
    pixels_per_clock: int
    clocks_per_covered_line: int

    @property
    def clipped_width(self) -> int:
        return self.clipped_x1 - self.clipped_x0

    @property
    def clipped_height(self) -> int:
        return self.clipped_y1 - self.clipped_y0


@dataclass(frozen=True)
class FT812PrimitiveCost:
    """Raster contribution from a non-bitmap hardware primitive."""

    word_index: int
    primitive: str
    clipped_x0: int
    clipped_y0: int
    clipped_x1: int
    clipped_y1: int
    pixels_per_clock: int
    clocks_per_covered_line: int


@dataclass(frozen=True)
class FT812BudgetReport:
    """Complete per-line result for one display list."""

    timing: FT812Timing
    word_count: int
    display_word_index: int
    clear_count: int
    draws: tuple[FT812DrawCost, ...]
    primitives: tuple[FT812PrimitiveCost, ...]
    line_raster_cycles: tuple[int, ...]
    line_cycles: tuple[int, ...]
    worst_line: int
    worst_cycles: int
    over_budget_lines: tuple[int, ...]
    hardware_overflow_lines: tuple[int, ...]

    @property
    def passed(self) -> bool:
        return not self.over_budget_lines

    @property
    def safe_line_cycles(self) -> int:
        return self.timing.safe_line_cycles

    @property
    def available_line_cycles(self) -> int:
        return self.timing.line_cycles

    @property
    def headroom_cycles(self) -> int:
        return self.safe_line_cycles - self.worst_cycles

    @property
    def utilization(self) -> float:
        return self.worst_cycles / self.available_line_cycles


@dataclass(frozen=True)
class FT812CoprocessorExpansion:
    """Conservative RAM_DL image lowered from one RAM_CMD frame stream."""

    display_list: bytes
    input_words: int
    expanded_words: int
    text_commands: int
    append_commands: int


@dataclass
class _BitmapState:
    source: int | None = None
    format: int | None = None
    stride_low: int | None = None
    stride_high: int = 0
    layout_height_low: int | None = None
    layout_height_high: int = 0
    width_low: int | None = None
    width_high: int = 0
    height_low: int | None = None
    height_high: int = 0
    filter: int = 0
    wrap_x: int = 0
    wrap_y: int = 0

    @classmethod
    def from_public(cls, bitmap: FT812Bitmap) -> "_BitmapState":
        state = cls(
            source=bitmap.source,
            format=bitmap.format,
            filter=bitmap.filter,
            wrap_x=bitmap.wrap_x,
            wrap_y=bitmap.wrap_y,
        )
        if bitmap.stride is not None:
            state.stride_low = bitmap.stride & 0x3FF
            state.stride_high = (bitmap.stride >> 10) & 0x3
        if bitmap.layout_height is not None:
            state.layout_height_low = bitmap.layout_height & 0x1FF
            state.layout_height_high = (bitmap.layout_height >> 9) & 0x3
        if bitmap.width is not None:
            state.width_low = bitmap.width & 0x1FF
            state.width_high = (bitmap.width >> 9) & 0x3
        if bitmap.height is not None:
            state.height_low = bitmap.height & 0x1FF
            state.height_high = (bitmap.height >> 9) & 0x3
        return state

    @property
    def width(self) -> int | None:
        if self.width_low is None:
            return None
        return (self.width_high << 9) | self.width_low

    @property
    def height(self) -> int | None:
        if self.height_low is None:
            return None
        return (self.height_high << 9) | self.height_low

    @property
    def stride(self) -> int | None:
        if self.stride_low is None:
            return None
        return (self.stride_high << 10) | self.stride_low

    @property
    def layout_height(self) -> int | None:
        if self.layout_height_low is None:
            return None
        return (self.layout_height_high << 9) | self.layout_height_low


@dataclass
class _GraphicsContext:
    current_handle: int = 0
    cell: int = 0
    scissor_x: int = 0
    scissor_y: int = 0
    scissor_width: int = 2048
    scissor_height: int = 2048
    vertex_frac: int = 4
    translate_x: int = 0
    translate_y: int = 0
    point_size: int = 16
    line_width: int = 16
    # FT81x reset value is RAM_G. Unlike BITMAP_SOURCE this is graphics
    # context, so SAVE_CONTEXT/RESTORE_CONTEXT must carry it.
    palette_source: int = 0


def _sign_extend(value: int, bits: int) -> int:
    sign = 1 << (bits - 1)
    return (value ^ sign) - sign


def _ceil_div(value: int, divisor: int) -> int:
    return -(-value // divisor)


def _dl_op(opcode: int, value: int = 0) -> int:
    return ((opcode & 0x3F) << 24) | (value & 0xFFFFFF)


def _dl_vertex2f(x16: int, y16: int) -> int:
    if not -0x4000 <= x16 < 0x4000 or not -0x4000 <= y16 < 0x4000:
        raise FT812BudgetError(
            "FT812_COPRO_TEXT_RANGE",
            f"expanded text vertex ({x16}, {y16}) is outside signed 15-bit VERTEX2F",
        )
    return 0x40000000 | ((x16 & 0x7FFF) << 15) | (y16 & 0x7FFF)


def _signed16(value: int) -> int:
    return _sign_extend(value & 0xFFFF, 16)


def expand_coprocessor_stream(
    stream: bytes | bytearray | memoryview,
    *,
    ram_g: bytes | bytearray | memoryview | None = None,
    rom_font_metrics: Mapping[int, tuple[int, int]] | None = None,
) -> FT812CoprocessorExpansion:
    """Lower the supported RAM_CMD frame subset to a conservative RAM_DL.

    The project simulator intentionally does not execute widget commands.  A
    raw simulator RAM_DL therefore still contains ``CMD_TEXT`` and matrix
    commands and cannot be scored as hardware RAM_DL.  This routine handles
    the exact universal subset used by the translator: ``DLSTART``,
    ``LOADIDENTITY``, axis-aligned ``SCALE``, ``SETMATRIX``, ``TEXT`` and
    ``APPEND``.  Unknown commands fail closed.

    ROM font 26 is documented by the VDAC2 reference as 8x16.  Callers may
    provide other metrics as ``font -> (maximum advance, height)``.  Text is
    expanded to one CELL/VERTEX pair per character plus conservative context
    setup, so both DL-walk and scanline raster costs include the widget.
    """

    try:
        data = bytes(stream)
    except (TypeError, ValueError) as exc:
        raise FT812BudgetError(
            "FT812_COPRO_TYPE", "RAM_CMD stream must be bytes-like") from exc
    if len(data) % 4:
        raise FT812BudgetError(
            "FT812_COPRO_ALIGNMENT",
            f"RAM_CMD byte length {len(data)} is not divisible by four",
        )
    words = [item[0] for item in struct.iter_unpack("<I", data)]
    metrics = {26: (8, 16)}
    if rom_font_metrics:
        metrics.update(rom_font_metrics)
    ram_g_bytes = bytes(ram_g) if ram_g is not None else None
    output: list[int] = []
    index = 0
    started = False
    scale_x = Fraction(1, 1)
    scale_y = Fraction(1, 1)
    text_commands = 0
    append_commands = 0

    def require(count: int, command: str) -> None:
        if index + count > len(words):
            raise FT812BudgetError(
                "FT812_COPRO_TRUNCATED",
                f"{command} is missing {index + count - len(words)} argument words",
                word_index=index,
            )

    while index < len(words):
        word = words[index]
        if word == 0 and started:
            output.append(0)
            index += 1
            break
        if (word & 0xFFFFFF00) != 0xFFFFFF00:
            if not started:
                raise FT812BudgetError(
                    "FT812_COPRO_DLSTART",
                    "RAM_CMD frame does not begin with CMD_DLSTART",
                    word_index=index,
                )
            output.append(word)
            index += 1
            continue

        command = word & 0xFF
        if command == 0x00:  # CMD_DLSTART
            output.clear()
            started = True
            scale_x = Fraction(1, 1)
            scale_y = Fraction(1, 1)
            index += 1
        elif not started:
            raise FT812BudgetError(
                "FT812_COPRO_DLSTART",
                "coprocessor command appears before CMD_DLSTART",
                word_index=index,
            )
        elif command == 0x26:  # CMD_LOADIDENTITY
            scale_x = Fraction(1, 1)
            scale_y = Fraction(1, 1)
            index += 1
        elif command == 0x28:  # CMD_SCALE, signed 16.16
            require(3, "CMD_SCALE")
            raw_x = _sign_extend(words[index + 1], 32)
            raw_y = _sign_extend(words[index + 2], 32)
            if raw_x <= 0 or raw_y <= 0:
                raise FT812BudgetError(
                    "FT812_COPRO_MATRIX",
                    "only positive axis-aligned CMD_SCALE is supported",
                    word_index=index,
                )
            scale_x *= Fraction(raw_x, 1 << 16)
            scale_y *= Fraction(raw_y, 1 << 16)
            index += 3
        elif command == 0x2A:  # CMD_SETMATRIX -> six DL transform words
            # Geometry below already applies the scale to synthetic text.
            # Six explicit words conservatively preserve the real DL walk.
            output.extend(_dl_op(opcode, 0) for opcode in range(0x15, 0x1B))
            index += 1
        elif command == 0x0C:  # CMD_TEXT
            require(3, "CMD_TEXT")
            xy = words[index + 1]
            font_options = words[index + 2]
            x = _signed16(xy)
            y = _signed16(xy >> 16)
            font = font_options & 0xFFFF
            options = (font_options >> 16) & 0xFFFF
            if options:
                raise FT812BudgetError(
                    "FT812_COPRO_TEXT_OPTIONS",
                    f"CMD_TEXT options 0x{options:04X} require an explicit model",
                    word_index=index,
                )
            metric = metrics.get(font)
            if metric is None:
                raise FT812BudgetError(
                    "FT812_COPRO_FONT",
                    f"ROM font {font} has no declared metrics",
                    word_index=index,
                )
            string_offset = (index + 3) * 4
            terminator = data.find(b"\0", string_offset)
            if terminator < 0:
                raise FT812BudgetError(
                    "FT812_COPRO_TEXT_ENCODING",
                    "CMD_TEXT string has no zero terminator",
                    word_index=index,
                )
            string_bytes = data[string_offset:terminator]
            try:
                text = string_bytes.decode("latin-1")
            except UnicodeDecodeError as exc:  # pragma: no cover: latin-1 total.
                raise FT812BudgetError(
                    "FT812_COPRO_TEXT_ENCODING", "invalid CMD_TEXT bytes",
                    word_index=index,
                ) from exc
            advance = max(1, _ceil_div(metric[0] * scale_x.numerator,
                                        scale_x.denominator))
            glyph_height = max(1, _ceil_div(
                metric[1] * scale_y.numerator, scale_y.denominator))
            # SAVE/RESTORE keeps translator Z-order state intact. Bitmap
            # parameters are handle-global on FT812, matching real ROM handles.
            output.extend((
                _dl_op(_SAVE_CONTEXT),
                _dl_op(_BITMAP_HANDLE, font & 0x1F),
                _dl_op(_BITMAP_LAYOUT,
                       (9 << 19) | ((metric[0] & 0x3FF) << 9) |
                       (metric[1] & 0x1FF)),
                _dl_op(_BITMAP_SIZE,
                       ((advance & 0x1FF) << 9) | (glyph_height & 0x1FF)),
                _dl_op(_VERTEX_FORMAT, 4),
                _dl_op(_BEGIN, _BITMAPS),
            ))
            cursor_x = x
            for character in text:
                output.append(_dl_op(_CELL, ord(character) & 0x7F))
                output.append(_dl_vertex2f(cursor_x * 16, y * 16))
                cursor_x += advance
            output.extend((_dl_op(_END), _dl_op(_RESTORE_CONTEXT)))
            text_commands += 1
            padded_end = (terminator + 4) & ~3
            index = padded_end // 4
        elif command == 0x1E:  # CMD_APPEND(address, bytes)
            require(3, "CMD_APPEND")
            if ram_g_bytes is None:
                raise FT812BudgetError(
                    "FT812_COPRO_APPEND_MEMORY",
                    "CMD_APPEND requires a RAM_G snapshot",
                    word_index=index,
                )
            source = words[index + 1] & 0x3FFFFF
            size = words[index + 2]
            if size % 4 or source + size > len(ram_g_bytes):
                raise FT812BudgetError(
                    "FT812_COPRO_APPEND_RANGE",
                    f"CMD_APPEND range 0x{source:X}+0x{size:X} is invalid",
                    word_index=index,
                )
            output.extend(item[0] for item in struct.iter_unpack(
                "<I", ram_g_bytes[source:source + size]))
            append_commands += 1
            index += 3
        elif command == 0x01:  # CMD_SWAP: frame stream is complete.
            if not output or output[-1] != 0:
                output.append(0)
            index += 1
            break
        else:
            raise FT812BudgetError(
                "FT812_COPRO_COMMAND_UNSUPPORTED",
                f"coprocessor command 0xFFFFFF{command:02X} is unsupported",
                word_index=index,
            )

    if not started:
        raise FT812BudgetError(
            "FT812_COPRO_DLSTART", "RAM_CMD stream has no CMD_DLSTART")
    if not output or output[-1] != 0:
        raise FT812BudgetError(
            "FT812_DISPLAY_MISSING",
            "expanded coprocessor stream has no terminating DISPLAY",
        )
    encoded = b"".join(struct.pack("<I", word & 0xFFFFFFFF)
                       for word in output)
    return FT812CoprocessorExpansion(
        display_list=encoded,
        input_words=index,
        expanded_words=len(output),
        text_commands=text_commands,
        append_commands=append_commands,
    )


def bitmap_pixels_per_clock(format_code: int, filter_mode: int) -> int:
    """Return the conservative documented FT812 bitmap raster rate."""

    if filter_mode not in (0, 1):
        raise FT812BudgetError(
            "FT812_BITMAP_FILTER", f"invalid bitmap filter {filter_mode}"
        )
    slow = format_code in _SLOW_FORMATS
    if filter_mode:  # BILINEAR
        return 2 if slow else 4
    return 8 if slow else 16


def _clip_rectangle(
    x16: int,
    y16: int,
    width: int,
    height: int,
    context: _GraphicsContext,
    timing: FT812Timing,
) -> tuple[int, int, int, int]:
    # A sub-pixel edge can touch both adjacent integer pixels, hence floor for
    # the leading edge and ceil for the trailing edge.
    bitmap_x0 = x16 // 16
    bitmap_y0 = y16 // 16
    bitmap_x1 = _ceil_div(x16 + width * 16, 16)
    bitmap_y1 = _ceil_div(y16 + height * 16, 16)

    clip_x0 = max(0, context.scissor_x)
    clip_y0 = max(0, context.scissor_y)
    clip_x1 = min(timing.width, context.scissor_x + context.scissor_width)
    clip_y1 = min(timing.height, context.scissor_y + context.scissor_height)
    if clip_x1 < clip_x0:
        clip_x1 = clip_x0
    if clip_y1 < clip_y0:
        clip_y1 = clip_y0

    x0 = max(bitmap_x0, clip_x0)
    y0 = max(bitmap_y0, clip_y0)
    x1 = max(x0, min(bitmap_x1, clip_x1))
    y1 = max(y0, min(bitmap_y1, clip_y1))
    return x0, y0, x1, y1


def _find_display(words: tuple[int, ...]) -> int:
    for index, word in enumerate(words[:MAX_DL_WORDS]):
        if (word >> 30) != 0:
            continue
        if (word >> 24) == _DISPLAY:
            if word != 0:
                raise FT812BudgetError(
                    "FT812_RESERVED_BITS",
                    "DISPLAY has non-zero reserved bits",
                    word_index=index,
                )
            word_count = index + 1
            if word_count >= MAX_DL_WORDS:
                raise FT812BudgetError(
                    "FT812_DL_WORD_LIMIT",
                    f"display list uses {word_count} words; limit is <{MAX_DL_WORDS}",
                    word_index=index,
                )
            return index
    if len(words) >= MAX_DL_WORDS:
        raise FT812BudgetError(
            "FT812_DL_WORD_LIMIT",
            f"DISPLAY was not reached before the {MAX_DL_WORDS}-word limit",
            word_index=MAX_DL_WORDS - 1,
        )
    raise FT812BudgetError(
        "FT812_DISPLAY_MISSING", "display list has no terminating DISPLAY"
    )


def analyze_display_list(
    ram_dl: bytes | bytearray | memoryview,
    timing: FT812Timing | None = None,
    *,
    initial_bitmaps: Mapping[int, FT812Bitmap] | None = None,
    fail_on_budget: bool = True,
) -> FT812BudgetReport:
    """Parse and conservatively score actual little-endian FT812 RAM_DL.

    Data after the first DISPLAY is ignored, so a complete 8192-byte RAM_DL
    snapshot can be passed directly.  Invalid lists always raise
    :class:`FT812BudgetError`.  Budget failures raise by default; set
    ``fail_on_budget=False`` to inspect the returned failing report.
    """

    timing = timing or FT812Timing()
    try:
        data = bytes(ram_dl)
    except (TypeError, ValueError) as exc:
        raise FT812BudgetError(
            "FT812_DL_TYPE", "RAM_DL must be a bytes-like object"
        ) from exc
    if len(data) % 4:
        raise FT812BudgetError(
            "FT812_DL_ALIGNMENT",
            f"RAM_DL byte length {len(data)} is not divisible by four",
        )

    words = tuple(word[0] for word in struct.iter_unpack("<I", data))
    display_index = _find_display(words)
    executed = words[: display_index + 1]

    bitmaps: dict[int, _BitmapState] = {}
    if initial_bitmaps:
        for handle, bitmap in initial_bitmaps.items():
            if not isinstance(handle, int) or isinstance(handle, bool) or not 0 <= handle <= 31:
                raise FT812BudgetError(
                    "FT812_BITMAP_HANDLE", f"initial bitmap handle {handle!r} is outside 0..31"
                )
            if not isinstance(bitmap, FT812Bitmap):
                raise FT812BudgetError(
                    "FT812_BITMAP_STATE",
                    f"initial bitmap handle {handle} is not an FT812Bitmap",
                )
            bitmaps[handle] = _BitmapState.from_public(bitmap)

    context = _GraphicsContext()
    context_stack: list[_GraphicsContext] = []
    primitive: int | None = None
    raster = [0] * timing.height
    draws: list[FT812DrawCost] = []
    primitives: list[FT812PrimitiveCost] = []
    clear_count = 0
    pending_rectangle: tuple[int, int, int] | None = None

    def bitmap_state(handle: int) -> _BitmapState:
        return bitmaps.setdefault(handle, _BitmapState())

    def add_bitmap_draw(
        index: int,
        vertex_kind: str,
        handle: int,
        cell: int,
        x16: int,
        y16: int,
    ) -> None:
        state = bitmaps.get(handle)
        if (
            state is None
            or state.format is None
            or state.width is None
            or state.height is None
        ):
            raise FT812BudgetError(
                "FT812_BITMAP_STATE",
                f"bitmap handle {handle} has no complete LAYOUT/SIZE state",
                word_index=index,
            )
        if state.format not in FORMAT_NAMES:
            raise FT812BudgetError(
                "FT812_BITMAP_FORMAT",
                f"bitmap handle {handle} uses reserved format {state.format}",
                word_index=index,
            )
        palette_alignment = {
            8: 4,   # deprecated PALETTED uses ARGB8888 entries
            14: 2,  # PALETTED565
            15: 2,  # PALETTED4444
            16: 4,  # PALETTED8 uses ARGB8888 entries
        }.get(state.format)
        if (palette_alignment is not None and
                context.palette_source % palette_alignment):
            raise FT812BudgetError(
                "FT812_PALETTE_ALIGNMENT",
                f"format {FORMAT_NAMES[state.format]} needs a "
                f"{palette_alignment}-byte-aligned PALETTE_SOURCE, got "
                f"0x{context.palette_source:X}",
                word_index=index,
            )
        width = state.width
        height = state.height
        assert width is not None and height is not None and state.format is not None
        x0, y0, x1, y1 = _clip_rectangle(
            x16, y16, width, height, context, timing
        )
        rate = bitmap_pixels_per_clock(state.format, state.filter)
        per_line = _ceil_div(x1 - x0, rate) if x1 > x0 and y1 > y0 else 0
        if per_line:
            for line in range(y0, y1):
                raster[line] += per_line
        draws.append(
            FT812DrawCost(
                word_index=index,
                vertex_kind=vertex_kind,
                handle=handle,
                cell=cell,
                source=state.source,
                palette_source=context.palette_source,
                format=state.format,
                filter=state.filter,
                bitmap_stride=state.stride,
                bitmap_layout_height=state.layout_height,
                x_sixteenths=x16,
                y_sixteenths=y16,
                bitmap_width=width,
                bitmap_height=height,
                clipped_x0=x0,
                clipped_y0=y0,
                clipped_x1=x1,
                clipped_y1=y1,
                pixels_per_clock=rate,
                clocks_per_covered_line=per_line,
            )
        )

    def add_rectangle_vertex(index: int, x16: int, y16: int) -> None:
        nonlocal pending_rectangle
        if pending_rectangle is None:
            pending_rectangle = (index, x16, y16)
            return
        first_index, first_x16, first_y16 = pending_rectangle
        pending_rectangle = None
        # LINE_WIDTH is in 1/16 pixel units and rounds/extends rectangle edges.
        half_width16 = max(1, _ceil_div(context.line_width, 2))
        raw_x0 = min(first_x16, x16) - half_width16
        raw_y0 = min(first_y16, y16) - half_width16
        raw_x1 = max(first_x16, x16) + half_width16
        raw_y1 = max(first_y16, y16) + half_width16
        x0 = max(0, context.scissor_x, raw_x0 // 16)
        y0 = max(0, context.scissor_y, raw_y0 // 16)
        x1 = min(
            timing.width,
            context.scissor_x + context.scissor_width,
            _ceil_div(raw_x1, 16),
        )
        y1 = min(
            timing.height,
            context.scissor_y + context.scissor_height,
            _ceil_div(raw_y1, 16),
        )
        x1 = max(x0, x1)
        y1 = max(y0, y1)
        # Solid primitives are normally faster; 8 px/clock is deliberately
        # conservative and matches the slow-bitmap class used by the target.
        rate = 8
        per_line = _ceil_div(x1 - x0, rate) if x1 > x0 and y1 > y0 else 0
        if per_line:
            for line in range(y0, y1):
                raster[line] += per_line
        primitives.append(FT812PrimitiveCost(
            word_index=first_index,
            primitive="RECTS",
            clipped_x0=x0,
            clipped_y0=y0,
            clipped_x1=x1,
            clipped_y1=y1,
            pixels_per_clock=rate,
            clocks_per_covered_line=per_line,
        ))

    def add_vertex(
            index: int, vertex_kind: str, handle: int, cell: int,
            x16: int, y16: int) -> None:
        if primitive is None:
            return
        if primitive == _BITMAPS:
            add_bitmap_draw(index, vertex_kind, handle, cell, x16, y16)
            return
        if primitive == _RECTS:
            add_rectangle_vertex(index, x16, y16)
            return
        raise FT812BudgetError(
            "FT812_PRIMITIVE_UNSUPPORTED",
            f"cannot conservatively score primitive {primitive}",
            word_index=index,
        )

    for index, word in enumerate(executed):
        if word & 0x80000000:  # VERTEX2II: bit 31 is one.
            x = (word >> 21) & 0x1FF
            y = (word >> 12) & 0x1FF
            handle = (word >> 7) & 0x1F
            cell = word & 0x7F
            add_vertex(
                index,
                "VERTEX2II",
                handle,
                cell,
                x * 16 + context.translate_x,
                y * 16 + context.translate_y,
            )
            continue
        if word & 0x40000000:  # VERTEX2F: bits 31:30 are 01.
            raw_x = _sign_extend((word >> 15) & 0x7FFF, 15)
            raw_y = _sign_extend(word & 0x7FFF, 15)
            shift = 4 - context.vertex_frac
            add_vertex(
                index,
                "VERTEX2F",
                context.current_handle,
                context.cell,
                (raw_x << shift) + context.translate_x,
                (raw_y << shift) + context.translate_y,
            )
            continue

        opcode = (word >> 24) & 0x3F
        if opcode == _DISPLAY:
            break
        if opcode > 0x2D:
            raise FT812BudgetError(
                "FT812_UNKNOWN_OPCODE",
                f"reserved display-list opcode 0x{opcode:02X}",
                word_index=index,
            )
        if opcode in (_CALL, _JUMP, _RETURN, _MACRO):
            raise FT812BudgetError(
                "FT812_CONTROL_FLOW_UNSUPPORTED",
                f"opcode 0x{opcode:02X} needs external display-list state",
                word_index=index,
            )
        if opcode == _BITMAP_HANDLE:
            context.current_handle = word & 0x1F
        elif opcode == _CELL:
            context.cell = word & 0x7F
        elif opcode == _BITMAP_SOURCE:
            bitmap_state(context.current_handle).source = word & 0x3FFFFF
        elif opcode == _BITMAP_LAYOUT:
            state = bitmap_state(context.current_handle)
            state.format = (word >> 19) & 0x1F
            state.stride_low = (word >> 9) & 0x3FF
            state.layout_height_low = word & 0x1FF
        elif opcode == _BITMAP_LAYOUT_H:
            state = bitmap_state(context.current_handle)
            state.stride_high = (word >> 2) & 0x3
            state.layout_height_high = word & 0x3
        elif opcode == _BITMAP_SIZE:
            state = bitmap_state(context.current_handle)
            state.filter = (word >> 20) & 1
            state.wrap_x = (word >> 19) & 1
            state.wrap_y = (word >> 18) & 1
            state.width_low = (word >> 9) & 0x1FF
            state.height_low = word & 0x1FF
        elif opcode == _BITMAP_SIZE_H:
            state = bitmap_state(context.current_handle)
            state.width_high = (word >> 2) & 0x3
            state.height_high = word & 0x3
        elif opcode == _PALETTE_SOURCE:
            context.palette_source = word & 0x3FFFFF
        elif opcode == _SCISSOR_XY:
            context.scissor_x = (word >> 11) & 0x7FF
            context.scissor_y = word & 0x7FF
        elif opcode == _SCISSOR_SIZE:
            context.scissor_width = (word >> 12) & 0xFFF
            context.scissor_height = word & 0xFFF
        elif opcode == _BEGIN:
            if pending_rectangle is not None:
                raise FT812BudgetError(
                    "FT812_PRIMITIVE_VERTEX_PAIR",
                    "RECTS has an unmatched first vertex",
                    word_index=index,
                )
            primitive = word & 0xF
        elif opcode == _END:
            if primitive == _RECTS and pending_rectangle is not None:
                raise FT812BudgetError(
                    "FT812_PRIMITIVE_VERTEX_PAIR",
                    "RECTS has an unmatched first vertex",
                    word_index=index,
                )
            primitive = None
        elif opcode == _SAVE_CONTEXT:
            if len(context_stack) == 4:
                context_stack.pop(0)
            context_stack.append(replace(context))
        elif opcode == _RESTORE_CONTEXT:
            context = context_stack.pop() if context_stack else _GraphicsContext()
        elif opcode == _CLEAR:
            if word & 0x7:
                clear_count += 1
                x0 = max(0, context.scissor_x)
                y0 = max(0, context.scissor_y)
                x1 = min(timing.width, context.scissor_x + context.scissor_width)
                y1 = min(timing.height, context.scissor_y + context.scissor_height)
                per_line = _ceil_div(max(0, x1 - x0), 16)
                if per_line:
                    for line in range(y0, max(y0, y1)):
                        raster[line] += per_line
        elif opcode == _VERTEX_FORMAT:
            frac = word & 0x7
            if frac > 4:
                raise FT812BudgetError(
                    "FT812_VERTEX_FORMAT",
                    f"fractional-bit count {frac} is outside 0..4",
                    word_index=index,
                )
            context.vertex_frac = frac
        elif opcode == _VERTEX_TRANSLATE_X:
            context.translate_x = _sign_extend(word & 0x1FFFF, 17)
        elif opcode == _VERTEX_TRANSLATE_Y:
            context.translate_y = _sign_extend(word & 0x1FFFF, 17)
        elif opcode == _POINT_SIZE:
            context.point_size = word & 0x1FFF
        elif opcode == _LINE_WIDTH:
            context.line_width = word & 0xFFF

    word_count = len(executed)
    line_cycles = tuple(value + word_count for value in raster)
    worst_line = max(range(timing.height), key=line_cycles.__getitem__)
    worst_cycles = line_cycles[worst_line]
    over_budget = tuple(
        line for line, clocks in enumerate(line_cycles)
        if clocks > timing.safe_line_cycles
    )
    hardware_overflow = tuple(
        line for line, clocks in enumerate(line_cycles)
        if clocks > timing.line_cycles
    )
    report = FT812BudgetReport(
        timing=timing,
        word_count=word_count,
        display_word_index=display_index,
        clear_count=clear_count,
        draws=tuple(draws),
        primitives=tuple(primitives),
        line_raster_cycles=tuple(raster),
        line_cycles=line_cycles,
        worst_line=worst_line,
        worst_cycles=worst_cycles,
        over_budget_lines=over_budget,
        hardware_overflow_lines=hardware_overflow,
    )
    if fail_on_budget and over_budget:
        if hardware_overflow:
            code = "FT812_LINE_OVERFLOW"
            limit = timing.line_cycles
        else:
            code = "FT812_SAFETY_MARGIN"
            limit = timing.safe_line_cycles
        raise FT812BudgetError(
            code,
            f"scanline {worst_line} needs {worst_cycles} clocks; limit is {limit}",
            report=report,
        )
    return report


def validate_display_list(
    ram_dl: bytes | bytearray | memoryview,
    timing: FT812Timing | None = None,
    *,
    initial_bitmaps: Mapping[int, FT812Bitmap] | None = None,
) -> FT812BudgetReport:
    """Validate a display list and return its passing budget report."""

    return analyze_display_list(
        ram_dl,
        timing,
        initial_bitmaps=initial_bitmaps,
        fail_on_budget=True,
    )


__all__ = [
    "FORMAT_NAMES",
    "MAX_DL_WORDS",
    "FT812Bitmap",
    "FT812BudgetError",
    "FT812BudgetReport",
    "FT812CoprocessorExpansion",
    "FT812DrawCost",
    "FT812PrimitiveCost",
    "FT812Timing",
    "analyze_display_list",
    "bitmap_pixels_per_clock",
    "expand_coprocessor_stream",
    "validate_display_list",
]
