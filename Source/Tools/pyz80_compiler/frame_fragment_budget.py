"""Fail-closed whole-frame budget proof for the translated sprite fragment.

The future C fragment is inserted into the already open ``Render_Frame``
display list immediately after ``Render_WorldBackground``.  It replaces the
three legacy draw calls for background particles, dynamic objects and the
fixed player attachments.  This module does not patch that renderer.  It
binds a translator-produced envelope both to the concrete assembly shape and
to the source-derived ``Game.render`` plan, then combines the complete GAME
and TITLE branches.  The assembly call list is therefore an implementation
boundary, never the sole authority for Python Z order.

Display-list words in a section certificate are *expanded RAM_DL words*.
For the chunked sprite stream the checker does the CMD_APPEND arithmetic
itself.  Every non-empty chunk has its own state prefix/suffix:

    chunk_count * (prefix + suffix)
      + 2 * frame_record_count + appended_template_words

The two per-record words are VERTEX_TRANSLATE_X/Y.  The three physical
CMD_APPEND words are FIFO traffic, not RAM_DL words.  DISPLAY is added by the
checker to every scene branch, so it cannot be lost from the reservation.

Raster envelopes contain only raster clocks.  The display-list walk cost is
the complete branch word count and is added on every physical scanline.  A
component-wise sum of independently maximal envelopes is conservative even
when their maxima cannot occur in the same Python frame.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
import struct
from typing import Any, Iterable, Mapping, Sequence

from .ft812_budget import analyze_display_list, expand_coprocessor_stream
from .frame_render_plan import (
    FRAME_RENDER_PLAN_FORMAT,
    FrameRenderPlanError,
    compile_active_frame_render_plan,
)


CONTRACT_FORMAT = "pyz80-ft812-frame-fragment-budget-v4"
DEFAULT_RAM_DL_WORD_LIMIT = 2048
DEFAULT_SAFE_LINE_CYCLES = 1209
DEFAULT_WIDTH = 1024
DEFAULT_HEIGHT = 768

# The current PyZ80FT_BuildSpriteBatch ABI.  These constants are also checked
# against the C source, so changing the implementation invalidates an old
# translator certificate instead of silently changing the arithmetic.
BATCH_PREFIX_WORDS = 10
BATCH_SUFFIX_WORDS = 3
BATCH_RECORD_EXPANDED_OVERHEAD_WORDS = 2
BATCH_RECORD_PHYSICAL_WORDS = 5
BATCH_MAX_RECORDS = 128  # per chunk, never the whole-frame record maximum

INSERT_AFTER_CALL = "Render_WorldBackground"
REPLACED_CALLS = (
    "RTypePyDrawBackgroundParticles",
    "RTypeObjects_Draw",
    "RTypeFixedPlayer_Draw",
)
MANDATORY_TAIL_CALLS = (
    "RTypePyLogicalBitmapState",
    "RTypePyRenderPlayerLifecycle",
    "Render_M72PlayerShots",
    "Render_M72WaveProjectile",
    "RTypePyRenderChargeOrb",
    "Render_WorldForeground",
    "Render_ArcadeBackground",
    "Render_M72Hud",
    "RTypePyRenderBeamMeter",
    "RTypePyRenderLives",
)
TITLE_CALLS = ("M72Video_DrawTitle",)
DEBUG_CALL_DEFINES = {
    "Render_TsfmDetectBar": "RTYPE_TSFM_TEST",
    "Render_TsfmDebug": "RTYPE_TSFM_DEBUG",
}

_ASSEMBLY_SUFFIXES = frozenset((".asm", ".inc"))
_PYTHON_SUFFIXES = frozenset((".py",))


class FrameFragmentBudgetError(RuntimeError):
    """Stable fail-closed diagnostic from the frame proof."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class RenderFrameShape:
    """Concrete insertion boundary extracted from ``render.asm``."""

    insert_after: str
    replaced_calls: tuple[str, ...]
    tail_calls: tuple[str, ...]
    title_calls: tuple[str, ...]
    optional_debug_calls: tuple[tuple[str, str], ...]
    direct_setup_words: int
    display_words: int


@dataclass(frozen=True)
class SectionEnvelope:
    name: str
    max_dl_words: int
    raster_cycles_by_line: tuple[int, ...]
    proof_method: str
    proof_bound: str


@dataclass(frozen=True)
class BatchEnvelope:
    max_records: int
    chunk_capacity: int
    max_chunks: int
    max_appended_words: int
    max_expanded_dl_words: int
    max_physical_command_words: int
    raster_cycles_by_line: tuple[int, ...]
    counter_symbol: str
    proof_method: str


@dataclass(frozen=True)
class SceneBudget:
    name: str
    word_count: int
    worst_line: int
    worst_cycles: int
    line_cycles: tuple[int, ...]
    headroom_cycles: int


@dataclass(frozen=True)
class FrameFragmentBudgetReport:
    frame_render_plan_source_sha256: str
    frame_render_plan_method_ast_sha256: str
    frame_render_plan_sink_order_sha256: str
    frame_render_plan_semantic_sha256: str
    prefix_before_fragment_words: int
    mandatory_tail_words: int
    remaining_dl_words: int
    fragment_max_expanded_dl_words: int
    fragment_max_physical_command_words: int
    fragment_chunk_capacity: int
    fragment_max_chunks: int
    game: SceneBudget
    title: SceneBudget
    safe_line_cycles: int
    ram_dl_word_limit: int

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        # The complete per-line proof remains available on the object, but a
        # build report only needs the maxima and compact headroom summary.
        result["game"].pop("line_cycles", None)
        result["title"].pop("line_cycles", None)
        return result


def _strip_comment(line: str) -> str:
    return line.split(";", 1)[0].strip()


def _label_block(text: str, label: str, next_global_label: str) -> str:
    start_match = re.search(
        rf"(?m)^\s*{re.escape(label)}:\s*(?:;.*)?$", text)
    if start_match is None:
        raise FrameFragmentBudgetError(
            "PZFB001", f"assembly label {label} was not found")
    end_match = re.search(
        rf"(?m)^\s*{re.escape(next_global_label)}:\s*(?:;.*)?$",
        text[start_match.end():],
    )
    if end_match is None:
        raise FrameFragmentBudgetError(
            "PZFB002", f"assembly label {next_global_label} was not found")
    return text[start_match.end():start_match.end() + end_match.start()]


def _calls(block: str) -> tuple[str, ...]:
    result: list[str] = []
    for raw_line in block.splitlines():
        line = _strip_comment(raw_line)
        match = re.match(r"(?i)^CALL\s+([A-Za-z0-9_.$]+)$", line)
        if match:
            result.append(match.group(1))
    return tuple(result)


def inspect_render_frame(render_path: Path) -> RenderFrameShape:
    """Verify and return the exact current insertion topology.

    This is intentionally a shape check, not a permissive assembler parser.
    A new call, reordered Z layer, changed branch or moved DISPLAY invalidates
    the proof and requires regeneration by the Python translator.
    """

    try:
        text = render_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise FrameFragmentBudgetError(
            "PZFB003", f"cannot read {render_path}: {exc}") from exc
    block = _label_block(text, "Render_Frame", "Render_SubmitFrame")
    normalized = "\n".join(_strip_comment(line) for line in block.splitlines())

    if len(re.findall(r"(?mi)^FT_CMD_Start$", normalized)) != 1:
        raise FrameFragmentBudgetError(
            "PZFB004", "Render_Frame must open exactly one RAM_CMD stream")
    if len(re.findall(r"(?mi)^FT_DL_Start$", normalized)) != 1:
        raise FrameFragmentBudgetError(
            "PZFB005", "Render_Frame must contain exactly one CMD_DLSTART")
    setup_sequence = re.compile(
        r"FT_DL_Start\s+FT_VertexFormat\s+3\s+"
        r"FT_ClearColorRGB\s+0\s*,\s*0\s*,\s*0\s+FT_ClearAll",
        re.IGNORECASE,
    )
    if setup_sequence.search(normalized) is None:
        raise FrameFragmentBudgetError(
            "PZFB006", "Render_Frame setup no longer has VF3/black/CLEAR shape")
    if len(re.findall(r"(?mi)^FT_Display$", normalized)) != 1:
        raise FrameFragmentBudgetError(
            "PZFB007", "Render_Frame must terminate both scenes with one DISPLAY")

    game_match = re.search(
        r"(?ms)^\s*\.gameScene:\s*$([\s\S]*?)^\s*\.sceneDone:\s*$",
        block,
    )
    if game_match is None:
        raise FrameFragmentBudgetError(
            "PZFB008", "GAME/.sceneDone branch boundary was not found")
    game_calls = _calls(game_match.group(1))
    expected_game = (
        (INSERT_AFTER_CALL,) + REPLACED_CALLS + MANDATORY_TAIL_CALLS)
    if game_calls != expected_game:
        raise FrameFragmentBudgetError(
            "PZFB009",
            "GAME call order changed; expected " + " -> ".join(expected_game) +
            ", got " + " -> ".join(game_calls),
        )

    pre_game = block[:game_match.start()]
    title_seen = tuple(
        call for call in _calls(pre_game) if call in TITLE_CALLS)
    if title_seen != TITLE_CALLS:
        raise FrameFragmentBudgetError(
            "PZFB010", "TITLE branch no longer contains exactly M72Video_DrawTitle")

    optional: list[tuple[str, str]] = []
    for call, define in DEBUG_CALL_DEFINES.items():
        pattern = re.compile(
            rf"(?mis)^\s*ifdef\s+{re.escape(define)}\s*$"
            rf"[\s\S]*?^\s*CALL\s+{re.escape(call)}\s*$"
            rf"[\s\S]*?^\s*endif\s*$"
        )
        if pattern.search(normalized) is None:
            raise FrameFragmentBudgetError(
                "PZFB011", f"optional {call} is no longer guarded by {define}")
        optional.append((call, define))

    return RenderFrameShape(
        insert_after=INSERT_AFTER_CALL,
        replaced_calls=REPLACED_CALLS,
        tail_calls=MANDATORY_TAIL_CALLS,
        title_calls=TITLE_CALLS,
        optional_debug_calls=tuple(optional),
        direct_setup_words=3,
        display_words=1,
    )


def _hash_files(root: Path, paths: Iterable[Path]) -> str:
    digest = hashlib.sha256()
    normalized: list[tuple[str, Path]] = []
    for path in paths:
        absolute = path if path.is_absolute() else root / path
        if not absolute.is_file():
            raise FrameFragmentBudgetError(
                "PZFB012", f"proof dependency does not exist: {absolute}")
        try:
            relative = absolute.relative_to(root).as_posix()
        except ValueError as exc:
            raise FrameFragmentBudgetError(
                "PZFB013", f"proof dependency escapes project root: {absolute}") from exc
        normalized.append((relative, absolute))
    for relative, absolute in sorted(normalized):
        data = absolute.read_bytes()
        encoded = relative.encode("utf-8")
        digest.update(len(encoded).to_bytes(4, "little"))
        digest.update(encoded)
        digest.update(len(data).to_bytes(8, "little"))
        digest.update(data)
    return digest.hexdigest().upper()


def compute_source_bindings(project_root: Path) -> dict[str, str]:
    """Hash the complete active Python, renderer ASM and batch C surfaces."""

    assembly = [
        path for path in (project_root / "Source" / "ASM").rglob("*")
        if path.is_file() and path.suffix.lower() in _ASSEMBLY_SUFFIXES
    ]
    assembly.append(
        project_root / "Docs" / "TSLib" / "Include" / "FT" /
        "Coprocessor" / "BufferMacro.inc")
    python = [
        path for path in (project_root / "Source" / "Python").rglob("*")
        if path.is_file() and path.suffix.lower() in _PYTHON_SUFFIXES
    ]
    python.append(project_root / "run_python.cmd")
    batch = [
        project_root / "Source" / "C" / "ft812" / "pyz80_ft812.c",
        project_root / "Source" / "C" / "ft812" / "pyz80_ft812.h",
        project_root / "Source" / "C" / "ft812" /
        "pyz80_draw_fast_chunker.c",
        project_root / "Source" / "C" / "ft812" /
        "pyz80_draw_fast_chunker.h",
        project_root / "Source" / "C" / "generated" /
        "rtype_python_hq_templates.c",
        project_root / "Source" / "C" / "generated" /
        "rtype_python_hq_templates.h",
        project_root / "Source" / "C" / "generated" /
        "rtype_python_draw_vm.c",
        project_root / "Source" / "C" / "generated" /
        "rtype_python_draw_vm.h",
        project_root / "Source" / "C" / "generated" /
        "rtype_python_draw_vm.json",
    ]
    return {
        "assembly_tree_sha256": _hash_files(project_root, assembly),
        "active_python_tree_sha256": _hash_files(project_root, python),
        "batch_abi_sha256": _hash_files(project_root, batch),
    }


def compute_frame_render_plan_binding(project_root: Path) -> dict[str, Any]:
    """Return the exact active-Python frame-plan input to the budget proof.

    The broad ``active_python_tree_sha256`` binding remains useful for
    invalidating any Python change.  This narrower binding is deliberately
    redundant: it proves which ``Game.render`` semantics and sink order the
    frame envelopes describe, rather than asking a hand-maintained ASM call
    list to stand in for the source program.
    """

    try:
        plan = compile_active_frame_render_plan(project_root)
    except (FrameRenderPlanError, OSError) as exc:
        raise FrameFragmentBudgetError(
            "PZFB066", f"active Python frame render plan is invalid: {exc}") from exc

    paths = tuple(item.call_path for item in plan.sinks)

    def ordinal(path: str, *, after: int = -1) -> int:
        matches = [
            item.ordinal for item in plan.sinks
            if item.call_path == path and item.ordinal > after
        ]
        if not matches:
            raise FrameFragmentBudgetError(
                "PZFB066", f"frame render plan has no {path!r} after {after}")
        return matches[0]

    clear = ordinal("target.fill")
    background = ordinal("self.stage.draw_back")
    enemy_world = ordinal("self.enemy_world.draw")
    force = ordinal("self.force.draw")
    bits = ordinal("self.bits.draw")
    foreground = ordinal("self.stage.draw_front")
    hud = ordinal("target.blit", after=foreground)
    distance = ordinal("self._draw_debug_distance")
    major_sinks = (
        ("clear", "target.fill", clear),
        ("background", "self.stage.draw_back", background),
        ("enemy_world", "self.enemy_world.draw", enemy_world),
        ("force", "self.force.draw", force),
        ("bits", "self.bits.draw", bits),
        ("foreground", "self.stage.draw_front", foreground),
        ("hud", "target.blit", hud),
        ("distance", "self._draw_debug_distance", distance),
    )
    if (
            clear != 0 or background != 1 or
            (enemy_world, force, bits) != (2, 3, 4) or
            foreground >= hud or distance != len(paths) - 1):
        raise FrameFragmentBudgetError(
            "PZFB066",
            "active Python major Z order changed; required fill@0, "
            "stage.draw_back@1, enemy->Force->Bits, stage.draw_front before "
            "HUD, and distance last",
        )

    return {
        "format": FRAME_RENDER_PLAN_FORMAT,
        "source_path": plan.source_path,
        "source_sha256": plan.source_sha256,
        "launcher_sha256": plan.launcher_sha256,
        "method_ast_sha256": plan.method_ast_sha256,
        "sink_order_sha256": plan.sink_order_sha256,
        "semantic_sha256": plan.semantic_sha256,
        "major_z_order": {
            "sinks": [
                {"role": role, "call_path": path, "ordinal": sink_ordinal}
                for role, path, sink_ordinal in major_sinks
            ],
            "background_is_lowest_visible_layer": background == 1,
            "enemy_force_bits_are_ordered": enemy_world < force < bits,
            "foreground_before_hud": foreground < hud,
            "distance_is_last": distance == len(paths) - 1,
            "total_sink_count": len(paths),
        },
    }


def _verify_frame_render_plan_binding(
        project_root: Path, value: Any) -> dict[str, Any]:
    supplied = _mapping(value, "frame_render_plan")
    current = compute_frame_render_plan_binding(project_root)
    hash_fields = (
        "source_sha256",
        "launcher_sha256",
        "method_ast_sha256",
        "sink_order_sha256",
        "semantic_sha256",
    )
    identity_fields = ("format", "source_path")
    for name in identity_fields + hash_fields:
        if supplied.get(name) != current[name]:
            raise FrameFragmentBudgetError(
                "PZFB067",
                f"stale frame_render_plan.{name}; regenerate with translator",
            )
    if supplied.get("major_z_order") != current["major_z_order"]:
        raise FrameFragmentBudgetError(
            "PZFB068",
            "frame_render_plan.major_z_order does not match active Game.render",
        )
    return current


def _verify_batch_abi_source(project_root: Path) -> None:
    c_path = project_root / "Source" / "C" / "ft812" / "pyz80_ft812.c"
    h_path = project_root / "Source" / "C" / "ft812" / "pyz80_ft812.h"
    bridge_c_path = (
        project_root / "Source" / "C" / "ft812" /
        "pyz80_draw_fast_chunker.c")
    bridge_h_path = (
        project_root / "Source" / "C" / "ft812" /
        "pyz80_draw_fast_chunker.h")
    hq_path = (
        project_root / "Source" / "C" / "generated" /
        "rtype_python_hq_templates.h")
    try:
        c_text = c_path.read_text(encoding="utf-8")
        h_text = h_path.read_text(encoding="utf-8")
        bridge_c_text = bridge_c_path.read_text(encoding="utf-8")
        bridge_h_text = bridge_h_path.read_text(encoding="utf-8")
        hq_text = hq_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise FrameFragmentBudgetError(
            "PZFB014", f"cannot read current fast C pipeline ABI: {exc}") from exc

    def define(text: str, symbol: str) -> int:
        match = re.search(
            rf"(?m)^\s*#define\s+{re.escape(symbol)}\s+"
            r"(0x[0-9A-Fa-f]+|[0-9]+)u?\s*$", text)
        if match is None:
            raise FrameFragmentBudgetError(
                "PZFB015", f"C batch ABI constant {symbol} is missing")
        return int(match.group(1), 0)

    actual = {
        "prefix": define(c_text, "PYZ80_FT_BATCH_PREFIX_WORDS"),
        "suffix": define(c_text, "PYZ80_FT_BATCH_SUFFIX_WORDS"),
        "records": define(h_text, "PYZ80_FT_BATCH_MAX_RECORDS"),
    }
    expected = {
        "prefix": BATCH_PREFIX_WORDS,
        "suffix": BATCH_SUFFIX_WORDS,
        "records": BATCH_MAX_RECORDS,
    }
    if actual != expected:
        raise FrameFragmentBudgetError(
            "PZFB016", f"C batch ABI changed: expected {expected}, got {actual}")
    if (bridge_c_text.count("PyZ80FT_FindHQTemplate(") != 1 or
            bridge_c_text.count("PyZ80FT_BuildSpriteBatchFast(") != 1 or
            "rtype_python_draw_vm_stream(" not in bridge_c_text or
            "PYZ80_FT_BATCH_MAX_RECORDS" not in bridge_c_text or
            "rtype_python_draw_vm_record" not in bridge_h_text or
            define(hq_text, "PYZ80_FT_HQ_TEMPLATE_COUNT") <= 0):
        raise FrameFragmentBudgetError(
            "PZFB069",
            "fast VM/HQT3/FT812 bridge no longer has the certified ABI",
        )


def _pack_words(words: Iterable[int]) -> bytes:
    return b"".join(struct.pack("<I", word & 0xFFFFFFFF) for word in words)


def _rle(values: Sequence[int]) -> list[list[int]]:
    if not values:
        return []
    result: list[list[int]] = []
    start = 0
    current = values[0]
    for index, value in enumerate(values[1:], 1):
        if value == current:
            continue
        result.append([start, index, current])
        start = index
        current = value
    result.append([start, len(values), current])
    return result


def audit_distance_cmd_text(project_root: Path) -> dict[str, Any]:
    """Lower the concrete ``DIST 0000`` path with the real FT812 parser.

    ``RTypePyRenderDistance`` is generated assembly but its two strings are
    copied dynamically, so an assembly macro count alone would miss the ROM
    font expansion.  The source shape is checked first, then the exact RAM_CMD
    stream is sent through the same parser used by the hardware budget tests.
    """

    source = (project_root / "Source" / "ASM" /
              "generated_python_gameplay_tables.inc")
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise FrameFragmentBudgetError(
            "PZFB017", f"cannot read generated distance renderer: {exc}") from exc
    block = _label_block(text, "RTypePyRenderDistance", "RTypePyDistanceBuffer")
    normalized = "\n".join(_strip_comment(line) for line in block.splitlines())
    required_patterns = (
        r"(?mi)^FT_LoadIdentity$",
        r"(?mi)^FT_Scale\s+#0001999A\s*,\s*#0001999A$",
        r"(?mi)^FT_SetMatrix$",
        r"(?mi)^FT_ColorRGB\s+0\s*,\s*0\s*,\s*0$",
        r"(?mi)^FT_ColorRGB\s+255\s*,\s*255\s*,\s*255$",
        r"(?mi)^FT_Text\s+915\s*,\s*711\s*,\s*26\s*,\s*0$",
        r"(?mi)^FT_Text\s+914\s*,\s*710\s*,\s*26\s*,\s*0$",
    )
    for pattern in required_patterns:
        if re.search(pattern, normalized) is None:
            raise FrameFragmentBudgetError(
                "PZFB018", "generated DIST renderer no longer matches its FT812 model")
    if len(re.findall(r"(?mi)^LD\s+BC\s*,\s*12$", normalized)) != 2:
        raise FrameFragmentBudgetError(
            "PZFB019", "DIST must copy two exact 12-byte padded strings")
    buffer_match = re.search(
        r"(?ms)^\s*RTypePyDistanceBuffer:\s*$"
        r"[\s\S]*?^\s*DEFM\s+\"DIST \"\s*$"
        r"[\s\S]*?^\s*DEFS\s+4\s*,\s*'0'\s*$"
        r"[\s\S]*?^\s*DEFB\s+0\s*,\s*0\s*,\s*0\s*$",
        text,
    )
    if buffer_match is None:
        raise FrameFragmentBudgetError(
            "PZFB019", "DIST buffer is not the exact padded nine-character string")

    cmd_dlstart = 0xFFFFFF00
    cmd_loadidentity = 0xFFFFFF26
    cmd_scale = 0xFFFFFF28
    cmd_setmatrix = 0xFFFFFF2A
    cmd_text = 0xFFFFFF0C
    text_bytes = b"DIST 0000\0\0\0"
    stream = _pack_words((
        cmd_dlstart,
        cmd_loadidentity,
        cmd_scale, 0x0001999A, 0x0001999A,
        cmd_setmatrix,
        0x04000000,
        cmd_text, (711 << 16) | 915, 26,
    ))
    stream += text_bytes
    stream += _pack_words((
        0x04FFFFFF,
        cmd_text, (710 << 16) | 914, 26,
    ))
    stream += text_bytes
    # Shared Render_Frame DISPLAY is included for the real parser, then
    # removed from the section word reservation below.
    stream += _pack_words((0,))
    expansion = expand_coprocessor_stream(stream)
    budget = analyze_display_list(expansion.display_list)
    if (expansion.text_commands != 2 or expansion.append_commands != 0 or
            expansion.expanded_words != 61 or budget.word_count != 61):
        raise FrameFragmentBudgetError(
            "PZFB019",
            "real FT812 parser changed DIST expansion; regenerate the proof model",
        )
    return {
        "source": source.relative_to(project_root).as_posix(),
        "parser": "pyz80_compiler.ft812_budget.expand_coprocessor_stream",
        "input_ram_cmd_words": expansion.input_words,
        "text_commands": expansion.text_commands,
        "expanded_words_with_display": expansion.expanded_words,
        "section_expanded_dl_words": expansion.expanded_words - 1,
        "display_words_removed_from_section": 1,
        "worst_line_with_display": budget.worst_line,
        "worst_cycles_with_display": budget.worst_cycles,
        "raster_cycles_by_line": {"rle": _rle(budget.line_raster_cycles)},
    }


def _require_int(value: Any, name: str, *, minimum: int = 0) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise FrameFragmentBudgetError(
            "PZFB020", f"{name} must be an integer >= {minimum}")
    return value


def _raster_vector(value: Any, height: int, name: str) -> tuple[int, ...]:
    if isinstance(value, list):
        if len(value) != height:
            raise FrameFragmentBudgetError(
                "PZFB021", f"{name} must contain exactly {height} scanlines")
        return tuple(_require_int(item, f"{name}[{index}]")
                     for index, item in enumerate(value))
    if not isinstance(value, Mapping):
        raise FrameFragmentBudgetError(
            "PZFB022", f"{name} must be a full vector or {{'rle': [...]}}")
    spans = value.get("rle")
    if not isinstance(spans, list) or not spans:
        raise FrameFragmentBudgetError(
            "PZFB023", f"{name}.rle must be a non-empty covering list")
    result = [0] * height
    cursor = 0
    for index, span in enumerate(spans):
        if (not isinstance(span, list) or len(span) != 3):
            raise FrameFragmentBudgetError(
                "PZFB024", f"{name}.rle[{index}] must be [start,end,cycles]")
        start = _require_int(span[0], f"{name}.rle[{index}].start")
        end = _require_int(span[1], f"{name}.rle[{index}].end")
        cycles = _require_int(span[2], f"{name}.rle[{index}].cycles")
        if start != cursor or end <= start or end > height:
            raise FrameFragmentBudgetError(
                "PZFB025",
                f"{name}.rle must cover 0..{height} exactly; "
                f"span {index} begins {start}, expected {cursor}",
            )
        result[start:end] = [cycles] * (end - start)
        cursor = end
    if cursor != height:
        raise FrameFragmentBudgetError(
            "PZFB026", f"{name}.rle ends at {cursor}, expected {height}")
    return tuple(result)


def _proof(value: Any, name: str) -> tuple[str, str]:
    if not isinstance(value, Mapping) or value.get("complete") is not True:
        raise FrameFragmentBudgetError(
            "PZFB027", f"{name}.proof.complete must be true")
    method = value.get("method")
    bound = value.get("bound")
    if not isinstance(method, str) or not method.strip():
        raise FrameFragmentBudgetError(
            "PZFB028", f"{name}.proof.method must name the translator proof")
    if bound not in ("exact", "conservative"):
        raise FrameFragmentBudgetError(
            "PZFB029", f"{name}.proof.bound must be exact or conservative")
    return method, bound


def _section(name: str, value: Any, height: int) -> SectionEnvelope:
    if not isinstance(value, Mapping):
        raise FrameFragmentBudgetError(
            "PZFB030", f"missing translator envelope for {name}")
    if value.get("dl_words_kind") != "expanded_ram_dl":
        raise FrameFragmentBudgetError(
            "PZFB031", f"{name} must count expanded RAM_DL words")
    method, bound = _proof(value.get("proof"), name)
    return SectionEnvelope(
        name=name,
        max_dl_words=_require_int(value.get("max_dl_words"),
                                  f"{name}.max_dl_words"),
        raster_cycles_by_line=_raster_vector(
            value.get("raster_cycles_by_line"), height,
            f"{name}.raster_cycles_by_line"),
        proof_method=method,
        proof_bound=bound,
    )


def _batch(value: Any, height: int) -> BatchEnvelope:
    name = "fragment"
    if not isinstance(value, Mapping):
        raise FrameFragmentBudgetError(
            "PZFB032", "missing translator sprite-fragment envelope")
    if tuple(value.get("replaces_calls", ())) != REPLACED_CALLS:
        raise FrameFragmentBudgetError(
            "PZFB033", "fragment does not replace the exact three renderer calls")
    if value.get("dl_words_kind") != "expanded_ram_dl":
        raise FrameFragmentBudgetError(
            "PZFB034", "fragment must count expanded RAM_DL words")
    method, _ = _proof(value.get("proof"), name)
    records = _require_int(value.get("max_records"), "fragment.max_records")
    if records > 0xFFFF:
        raise FrameFragmentBudgetError(
            "PZFB035", f"frame needs {records} records; stream counter limit is 65535")
    chunk_capacity = _require_int(
        value.get("chunk_capacity"), "fragment.chunk_capacity", minimum=1)
    if chunk_capacity > BATCH_MAX_RECORDS:
        raise FrameFragmentBudgetError(
            "PZFB063", f"chunk capacity {chunk_capacity} exceeds batch ABI "
            f"limit {BATCH_MAX_RECORDS}")
    chunks = 0 if records == 0 else (
        records + chunk_capacity - 1) // chunk_capacity
    if _require_int(value.get("max_chunks"), "fragment.max_chunks") != chunks:
        raise FrameFragmentBudgetError(
            "PZFB064", "max_chunks is not ceil(max_records/chunk_capacity)")
    appended = _require_int(
        value.get("max_appended_words"), "fragment.max_appended_words")

    counter = value.get("record_counter")
    if not isinstance(counter, Mapping):
        raise FrameFragmentBudgetError(
            "PZFB036", "fragment.record_counter contract is missing")
    symbol = counter.get("symbol")
    if not isinstance(symbol, str) or not symbol.strip():
        raise FrameFragmentBudgetError(
            "PZFB037", "fragment.record_counter.symbol is missing")
    if _require_int(counter.get("maximum"), "record_counter.maximum") != records:
        raise FrameFragmentBudgetError(
            "PZFB038", "record counter maximum differs from max_records")
    if counter.get("origin") != "active_python_render_order":
        raise FrameFragmentBudgetError(
            "PZFB039", "record counter is not derived from active Python render order")
    if counter.get("overflow_policy") != "fail_before_frame_publication":
        raise FrameFragmentBudgetError(
            "PZFB040", "record counter must fail before frame publication")

    append_bound = value.get("append_bound")
    if (not isinstance(append_bound, Mapping) or
            append_bound.get("cmd_append_expanded") is not True or
            append_bound.get("all_reachable_templates") is not True or
            _require_int(append_bound.get("maximum"),
                         "append_bound.maximum") != appended):
        raise FrameFragmentBudgetError(
            "PZFB041", "CMD_APPEND bound is not complete for all reachable templates")

    prepublication = value.get("prepublication")
    if not isinstance(prepublication, Mapping):
        raise FrameFragmentBudgetError(
            "PZFB070", "fragment prepublication proof is missing")
    required_prepublication = {
        "complete_record_count_preflight": True,
        "complete_template_lookup_preflight": True,
        "complete_append_budget_preflight": True,
        "no_queue_fragment_ready_before_preflight": True,
        "atomic_complete_frame_commit": True,
    }
    if any(prepublication.get(name) is not expected
           for name, expected in required_prepublication.items()):
        raise FrameFragmentBudgetError(
            "PZFB071",
            "count/lookup/append must be proved before the first queue "
            "publication and the complete frame must commit atomically",
        )

    if records == 0 and appended != 0:
        raise FrameFragmentBudgetError(
            "PZFB065", "zero-record frame cannot append template words")
    expanded = (chunks * (BATCH_PREFIX_WORDS + BATCH_SUFFIX_WORDS) +
                BATCH_RECORD_EXPANDED_OVERHEAD_WORDS * records + appended)
    physical = (chunks * (BATCH_PREFIX_WORDS + BATCH_SUFFIX_WORDS) +
                BATCH_RECORD_PHYSICAL_WORDS * records)
    if _require_int(value.get("max_expanded_dl_words"),
                    "fragment.max_expanded_dl_words") != expanded:
        raise FrameFragmentBudgetError(
            "PZFB042",
            "fragment expanded count does not equal chunks*(prefix+suffix)+"
            "2*records+CMD_APPEND words",
        )
    if _require_int(value.get("max_physical_command_words"),
                    "fragment.max_physical_command_words") != physical:
        raise FrameFragmentBudgetError(
            "PZFB043", "fragment physical count does not equal "
            "chunks*(prefix+suffix)+5*records")
    return BatchEnvelope(
        max_records=records,
        chunk_capacity=chunk_capacity,
        max_chunks=chunks,
        max_appended_words=appended,
        max_expanded_dl_words=expanded,
        max_physical_command_words=physical,
        raster_cycles_by_line=_raster_vector(
            value.get("raster_cycles_by_line"), height,
            "fragment.raster_cycles_by_line"),
        counter_symbol=symbol,
        proof_method=method,
    )


def _sum_raster(height: int, envelopes: Sequence[Sequence[int]]) -> tuple[int, ...]:
    result = [0] * height
    for envelope in envelopes:
        if len(envelope) != height:
            raise FrameFragmentBudgetError(
                "PZFB044", "internal raster envelope height mismatch")
        for line, cycles in enumerate(envelope):
            result[line] += cycles
    return tuple(result)


def _scene(name: str, words: int, raster: Sequence[int], safe: int,
           ram_dl_limit: int) -> SceneBudget:
    # The existing project analyser deliberately requires fewer than 2048
    # words: DISPLAY at word index 2047 is rejected.
    if words >= ram_dl_limit:
        raise FrameFragmentBudgetError(
            "PZFB050", f"{name} uses {words} RAM_DL words; required <{ram_dl_limit}")
    line_cycles = tuple(words + value for value in raster)
    worst_line = max(range(len(line_cycles)), key=line_cycles.__getitem__)
    worst = line_cycles[worst_line]
    if worst > safe:
        raise FrameFragmentBudgetError(
            "PZFB051",
            f"{name} scanline {worst_line} needs {worst} clocks; practical limit is {safe}",
        )
    return SceneBudget(
        name=name,
        word_count=words,
        worst_line=worst_line,
        worst_cycles=worst,
        line_cycles=line_cycles,
        headroom_cycles=safe - worst,
    )


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise FrameFragmentBudgetError("PZFB052", f"{name} must be an object")
    return value


def prove_frame_fragment_budget(
    project_root: Path,
    render_path: Path,
    contract: Mapping[str, Any],
    *,
    defines: Iterable[str] = (),
) -> FrameFragmentBudgetReport:
    """Bind ``contract`` to current sources and prove both scene branches."""

    if contract.get("format") != CONTRACT_FORMAT:
        raise FrameFragmentBudgetError(
            "PZFB053", f"unsupported contract format {contract.get('format')!r}")

    source_program = _mapping(contract.get("source_program"), "source_program")
    if (source_program.get("launcher") != "run_python.cmd" or
            source_program.get("module") != "rtype_port.app" or
            source_program.get("canonical") is not False):
        raise FrameFragmentBudgetError(
            "PZFB054", "certificate is not bound to run_python.cmd / rtype_port.app")

    # Validate the narrow Game.render semantic binding before inspecting any
    # envelope or doing budget arithmetic.  A stale plan or moved background
    # must never be masked by an unrelated missing/invalid layer envelope.
    frame_render_plan = _verify_frame_render_plan_binding(
        project_root, contract.get("frame_render_plan"))

    shape = inspect_render_frame(render_path)
    _verify_batch_abi_source(project_root)
    expected_insertion = {
        "after": shape.insert_after,
        "replaces_calls": list(shape.replaced_calls),
        "mandatory_tail_calls": list(shape.tail_calls),
        "display_words_reserved": shape.display_words,
    }
    if contract.get("insertion") != expected_insertion:
        raise FrameFragmentBudgetError(
            "PZFB072",
            "certificate insertion boundary differs from the inspected "
            "renderer",
        )
    distance_audit = audit_distance_cmd_text(project_root)
    expected_static = {"RTypePyRenderDistance": distance_audit}
    if contract.get("statically_audited_sublayers") != expected_static:
        raise FrameFragmentBudgetError(
            "PZFB073",
            "certificate omitted or changed the exact DIST sublayer audit",
        )

    target = _mapping(contract.get("target"), "target")
    width = _require_int(target.get("width"), "target.width", minimum=1)
    height = _require_int(target.get("height"), "target.height", minimum=1)
    ram_dl_limit = _require_int(
        target.get("ram_dl_word_limit"), "target.ram_dl_word_limit", minimum=2)
    safe_line_cycles = _require_int(
        target.get("safe_line_cycles"), "target.safe_line_cycles", minimum=1)
    if (width, height, ram_dl_limit, safe_line_cycles) != (
            DEFAULT_WIDTH, DEFAULT_HEIGHT, DEFAULT_RAM_DL_WORD_LIMIT,
            DEFAULT_SAFE_LINE_CYCLES):
        raise FrameFragmentBudgetError(
            "PZFB055", "certificate target is not FT812 1024x768 / 2048 / 1209")

    bindings = _mapping(contract.get("bindings"), "bindings")
    current_bindings = compute_source_bindings(project_root)
    for name, current in current_bindings.items():
        if bindings.get(name) != current:
            raise FrameFragmentBudgetError(
                "PZFB056", f"stale source binding {name}; regenerate with translator")

    enabled_defines = frozenset(defines)
    declared_defines = contract.get("assembly_defines")
    if (not isinstance(declared_defines, list) or
            any(not isinstance(item, str) for item in declared_defines) or
            frozenset(declared_defines) != enabled_defines):
        raise FrameFragmentBudgetError(
            "PZFB057", "assembly_defines do not match the assembled renderer")

    sections_obj = _mapping(contract.get("sections"), "sections")
    required_names = list(shape.title_calls)
    required_names.extend((shape.insert_after,))
    required_names.extend(shape.tail_calls)
    for call, define in shape.optional_debug_calls:
        if define in enabled_defines:
            required_names.append(call)
    sections = {
        name: _section(name, sections_obj.get(name), height)
        for name in required_names
    }
    distance_raster = _raster_vector(
        distance_audit["raster_cycles_by_line"], height,
        "RTypePyRenderDistance.raster_cycles_by_line")
    beam_section = sections.get("RTypePyRenderBeamMeter")
    if (beam_section is None or
            beam_section.max_dl_words <
            distance_audit["section_expanded_dl_words"] or
            any(beam_section.raster_cycles_by_line[line] < cycles
                for line, cycles in enumerate(distance_raster))):
        raise FrameFragmentBudgetError(
            "PZFB074",
            "RTypePyRenderBeamMeter envelope does not dominate its exact "
            "RTypePyRenderDistance tail",
        )
    batch = _batch(contract.get("fragment"), height)

    # Initial VF3/CLEAR_COLOR/CLEAR are literal words.  CLEAR contributes one
    # clock per 16 pixels across every line in the reset full-screen scissor.
    clear_raster = tuple((width + 15) // 16 for _ in range(height))
    debug_names = [
        call for call, define in shape.optional_debug_calls
        if define in enabled_defines
    ]
    common_words = shape.direct_setup_words + sum(
        sections[name].max_dl_words for name in debug_names)
    common_raster = _sum_raster(
        height,
        [clear_raster] + [sections[name].raster_cycles_by_line
                          for name in debug_names],
    )

    pre = sections[shape.insert_after]
    prefix_words = common_words + pre.max_dl_words
    prefix_raster = _sum_raster(
        height, [common_raster, pre.raster_cycles_by_line])

    tail_sections = [sections[name] for name in shape.tail_calls]
    tail_words = (sum(item.max_dl_words for item in tail_sections) +
                  shape.display_words)
    tail_raster = _sum_raster(
        height, [item.raster_cycles_by_line for item in tail_sections])

    # At most 2047 words including DISPLAY are accepted by the project's
    # FT812 analyser.  This is the exact value to pass to the C batch builder.
    remaining = (ram_dl_limit - 1) - prefix_words - tail_words
    if remaining < 0:
        raise FrameFragmentBudgetError(
            "PZFB058", "fixed GAME prefix/tail already exhaust RAM_DL")
    if batch.max_expanded_dl_words > remaining:
        raise FrameFragmentBudgetError(
            "PZFB059",
            f"fragment needs {batch.max_expanded_dl_words} expanded words; "
            f"caller may pass only {remaining}",
        )

    game_words = prefix_words + batch.max_expanded_dl_words + tail_words
    game_raster = _sum_raster(
        height,
        [prefix_raster, batch.raster_cycles_by_line, tail_raster],
    )
    game = _scene(
        "GAME", game_words, game_raster, safe_line_cycles, ram_dl_limit)

    title_sections = [sections[name] for name in shape.title_calls]
    title_words = (common_words +
                   sum(item.max_dl_words for item in title_sections) +
                   shape.display_words)
    title_raster = _sum_raster(
        height,
        [common_raster] + [item.raster_cycles_by_line
                           for item in title_sections],
    )
    title = _scene(
        "TITLE", title_words, title_raster, safe_line_cycles, ram_dl_limit)

    return FrameFragmentBudgetReport(
        frame_render_plan_source_sha256=frame_render_plan["source_sha256"],
        frame_render_plan_method_ast_sha256=(
            frame_render_plan["method_ast_sha256"]),
        frame_render_plan_sink_order_sha256=(
            frame_render_plan["sink_order_sha256"]),
        frame_render_plan_semantic_sha256=(
            frame_render_plan["semantic_sha256"]),
        prefix_before_fragment_words=prefix_words,
        mandatory_tail_words=tail_words,
        remaining_dl_words=remaining,
        fragment_max_expanded_dl_words=batch.max_expanded_dl_words,
        fragment_max_physical_command_words=batch.max_physical_command_words,
        fragment_chunk_capacity=batch.chunk_capacity,
        fragment_max_chunks=batch.max_chunks,
        game=game,
        title=title,
        safe_line_cycles=safe_line_cycles,
        ram_dl_word_limit=ram_dl_limit,
    )


def contract_requirements(project_root: Path, render_path: Path) -> dict[str, Any]:
    """Return the exact certificate surface the translator must emit."""

    frame_render_plan = compute_frame_render_plan_binding(project_root)
    shape = inspect_render_frame(render_path)
    _verify_batch_abi_source(project_root)
    section_names = list(shape.title_calls) + [shape.insert_after]
    section_names.extend(shape.tail_calls)
    return {
        "format": CONTRACT_FORMAT,
        "source_program": {
            "launcher": "run_python.cmd",
            "module": "rtype_port.app",
            "canonical": False,
        },
        "frame_render_plan": frame_render_plan,
        "bindings": compute_source_bindings(project_root),
        "target": {
            "width": DEFAULT_WIDTH,
            "height": DEFAULT_HEIGHT,
            "ram_dl_word_limit": DEFAULT_RAM_DL_WORD_LIMIT,
            "safe_line_cycles": DEFAULT_SAFE_LINE_CYCLES,
        },
        "assembly_defines": [],
        "insertion": {
            "after": shape.insert_after,
            "replaces_calls": list(shape.replaced_calls),
            "mandatory_tail_calls": list(shape.tail_calls),
            "display_words_reserved": shape.display_words,
        },
        "required_section_envelopes": section_names,
        "optional_section_envelopes": [
            {"call": call, "define": define}
            for call, define in shape.optional_debug_calls
        ],
        "section_schema": {
            "dl_words_kind": "expanded_ram_dl",
            "max_dl_words": "non-negative integer",
            "raster_cycles_by_line": (
                "768 integers or exact covering {'rle': [[start,end,cycles], ...]}"),
            "proof": {
                "complete": True,
                "method": "translator proof name",
                "bound": "exact|conservative",
            },
        },
        "fragment_schema": {
            "replaces_calls": list(shape.replaced_calls),
            "dl_words_kind": "expanded_ram_dl",
            "max_records": "0..65535 whole-frame records",
            "chunk_capacity": f"1..{BATCH_MAX_RECORDS}",
            "max_chunks": "ceil(max_records/chunk_capacity), or 0 when empty",
            "max_appended_words": (
                "maximum sum of expanded CMD_APPEND template words in one frame"),
            "max_expanded_dl_words": (
                "max_chunks*("
                f"{BATCH_PREFIX_WORDS}+{BATCH_SUFFIX_WORDS})+"
                "2*max_records+max_appended_words"),
            "max_physical_command_words": (
                "max_chunks*("
                f"{BATCH_PREFIX_WORDS}+{BATCH_SUFFIX_WORDS})+5*max_records"),
            "record_counter": {
                "symbol": "translator-generated runtime counter",
                "maximum": "same as max_records",
                "origin": "active_python_render_order",
                "overflow_policy": "fail_before_frame_publication",
            },
            "append_bound": {
                "maximum": "same as max_appended_words",
                "cmd_append_expanded": True,
                "all_reachable_templates": True,
            },
            "prepublication": {
                "complete_record_count_preflight": True,
                "complete_template_lookup_preflight": True,
                "complete_append_budget_preflight": True,
                "no_queue_fragment_ready_before_preflight": True,
                "atomic_complete_frame_commit": True,
            },
            "raster_cycles_by_line": "complete 768-line conservative envelope",
            "proof": {
                "complete": True,
                "method": "active Python reachable-frame enumeration/abstract proof",
                "bound": "exact|conservative",
            },
        },
        "statically_audited_sublayers": {
            "RTypePyRenderDistance": audit_distance_cmd_text(project_root),
        },
    }


def current_budget_status(
    project_root: Path,
    render_path: Path,
    contract_path: Path,
    *,
    defines: Iterable[str] = (),
) -> dict[str, Any]:
    """Machine-readable current gate state, including explicit blockers."""

    requirements = contract_requirements(project_root, render_path)
    shape = inspect_render_frame(render_path)
    status: dict[str, Any] = {
        "format": "pyz80-ft812-frame-fragment-budget-status-v2",
        "contract_format_required": CONTRACT_FORMAT,
        "contract_path": str(contract_path.resolve()),
        "source_program": requirements["source_program"],
        "frame_render_plan": requirements["frame_render_plan"],
        "bindings": requirements["bindings"],
        "insertion": requirements["insertion"],
        "live_target_lowering_present": False,
        "static_proof": {
            "direct_setup_words": shape.direct_setup_words,
            "display_words_reserved_per_scene": shape.display_words,
            "clear_raster_cycles_per_line": DEFAULT_WIDTH // 16,
            "distance_cmd_text": audit_distance_cmd_text(project_root),
            "cmd_append_expansion_formula": (
                f"{BATCH_PREFIX_WORDS}+{BATCH_SUFFIX_WORDS}+"
                "2*max_records+max_appended_words"),
            "cmd_append_physical_formula": (
                f"{BATCH_PREFIX_WORDS}+{BATCH_SUFFIX_WORDS}+5*max_records"),
        },
        "full_frame_proved": False,
        "remaining_dl_words": None,
    }
    if not contract_path.is_file():
        status.update({
            "status": "BLOCKED_MISSING_TRANSLATOR_CERTIFICATE",
            "blockers": {
                "missing_section_envelopes": requirements[
                    "required_section_envelopes"],
                "missing_fragment_contracts": [
                    "bounded active-Python draw-record counter",
                    "maximum per-frame sum of expanded CMD_APPEND template words",
                    "complete 768-line fragment raster envelope",
                    "complete prepublication preflight and atomic frame commit",
                ],
                "required_counter_contract": requirements[
                    "fragment_schema"]["record_counter"],
            },
        })
        return status
    try:
        contract = load_contract(contract_path)
        report = prove_frame_fragment_budget(
            project_root, render_path, contract, defines=defines)
    except FrameFragmentBudgetError as exc:
        status.update({
            "status": "BLOCKED_INVALID_TRANSLATOR_CERTIFICATE",
            "diagnostic": {"code": exc.code, "message": exc.message},
        })
        return status
    status.update({
        "status": "PASS",
        "full_frame_proved": True,
        "remaining_dl_words": report.remaining_dl_words,
        "report": report.to_dict(),
    })
    return status


def load_contract(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise FrameFragmentBudgetError(
            "PZFB060", f"translator frame certificate is missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise FrameFragmentBudgetError(
            "PZFB061", f"invalid translator frame certificate: {exc}") from exc
    if not isinstance(value, Mapping):
        raise FrameFragmentBudgetError(
            "PZFB062", "translator frame certificate root must be an object")
    return value


__all__ = [
    "BATCH_MAX_RECORDS",
    "BATCH_PREFIX_WORDS",
    "BATCH_RECORD_EXPANDED_OVERHEAD_WORDS",
    "BATCH_RECORD_PHYSICAL_WORDS",
    "BATCH_SUFFIX_WORDS",
    "CONTRACT_FORMAT",
    "FrameFragmentBudgetError",
    "FrameFragmentBudgetReport",
    "RenderFrameShape",
    "audit_distance_cmd_text",
    "compute_frame_render_plan_binding",
    "compute_source_bindings",
    "contract_requirements",
    "current_budget_status",
    "inspect_render_frame",
    "load_contract",
    "prove_frame_fragment_budget",
]
