"""Source-derived FT812 frame-timing contract for the active Python game.

The base TSLib mode remains ``VM_1024_768_59Hz`` because it is the proven
64 MHz / PCLK=1 / HCYCLE=1344 / 1024x768 register profile.  This stage derives
one generated override: REG_VCYCLE.  It is selected from the active Python
FRAME_RATE, changes blanking only, and remains non-live until assembler/link
and measured-device timing proofs exist.
"""

from __future__ import annotations

import ast
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Callable, Mapping

from .active_target_adapters import (
    ActiveTargetAdaptersError,
    validate_active_target_adapters_report,
)


FRAME_TIMING_PROVIDER_FORMAT = "pyz80.frame-timing-provider.v1"
FRAME_TIMING_CONTRACT_FORMAT = "pyz80.frame-timing-contract.v1"
FRAME_TIMING_PROVIDER_STATUS = (
    "FRAME_TIMING_CONTRACT_GENERATED_ASSEMBLE_MEASURE_BLOCKED")

DEFAULT_STATUS = "Build/rtype_python_frame_timing_provider_status.json"
DEFAULT_MANIFEST = "Build/rtype_python_frame_timing_contract.json"
DEFAULT_INCLUDE = "Source/ASM/generated_python_frame_timing.inc"

__all__ = [
    "FRAME_TIMING_PROVIDER_FORMAT",
    "FRAME_TIMING_CONTRACT_FORMAT",
    "FRAME_TIMING_PROVIDER_STATUS",
    "FrameTimingProviderError",
    "analyze_frame_timing_provider",
    "render_frame_timing_include",
    "render_frame_timing_manifest",
    "validate_frame_timing_provider_report",
]


class FrameTimingProviderError(ValueError):
    """A fail-closed source/timing/contract error."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_sha256(value: object) -> str:
    return _sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8"))


def _semantic_payload(report: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(report)
    for key in ("semantic_sha256", "status", "live", "live_blockers"):
        payload.pop(key, None)
    return payload


def _read_text(root: Path, relative: str) -> tuple[bytes, str]:
    path = root / Path(relative)
    try:
        data = path.read_bytes()
        return data, data.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise FrameTimingProviderError(
            "PZFTP101", f"source unavailable {relative}: {exc}") from exc


def _source_span(relative: str, data: bytes, text: str,
                 first_line: int, last_line: int, role: str) -> dict[str, Any]:
    lines = text.splitlines()
    if not (1 <= first_line <= last_line <= len(lines)):
        raise FrameTimingProviderError(
            "PZFTP102", f"invalid source span {relative}:{first_line}-{last_line}")
    source = "\n".join(lines[first_line - 1:last_line])
    return {
        "role": role,
        "path": relative,
        "first_line": first_line,
        "last_line": last_line,
        "source": source,
        "source_span_sha256": _sha256(source.encode("utf-8")),
        "file_sha256": _sha256(data),
    }


def _ast_constant(root: Path, relative: str, name: str,
                  role: str) -> tuple[Fraction, dict[str, Any]]:
    data, text = _read_text(root, relative)
    try:
        tree = ast.parse(text, filename=relative)
    except SyntaxError as exc:
        raise FrameTimingProviderError(
            "PZFTP103", f"cannot parse {relative}: {exc}") from exc
    matches: list[tuple[ast.AST, ast.expr]] = []
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1 and
                isinstance(node.targets[0], ast.Name) and
                node.targets[0].id == name):
            matches.append((node, node.value))
        elif (isinstance(node, ast.AnnAssign) and
              isinstance(node.target, ast.Name) and node.target.id == name and
              node.value is not None):
            matches.append((node, node.value))
    if len(matches) != 1:
        raise FrameTimingProviderError(
            "PZFTP104", f"expected one module constant {relative}:{name}")
    node, value_node = matches[0]
    try:
        value = ast.literal_eval(value_node)
    except (ValueError, TypeError) as exc:
        raise FrameTimingProviderError(
            "PZFTP105", f"{relative}:{name} is not a literal") from exc
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FrameTimingProviderError(
            "PZFTP105", f"{relative}:{name} is not numeric")
    value_fraction = Fraction(str(value))
    evidence = _source_span(
        relative, data, text, int(node.lineno), int(node.end_lineno or node.lineno),
        role)
    evidence["ast_sha256"] = _sha256(ast.dump(
        node, annotate_fields=True, include_attributes=False).encode("utf-8"))
    evidence["value_numerator"] = value_fraction.numerator
    evidence["value_denominator"] = value_fraction.denominator
    return value_fraction, evidence


def _ast_expression_evidence(
        root: Path, relative: str, role: str,
        predicate: Callable[[ast.AST], bool]) -> dict[str, Any]:
    data, text = _read_text(root, relative)
    try:
        tree = ast.parse(text, filename=relative)
    except SyntaxError as exc:
        raise FrameTimingProviderError(
            "PZFTP103", f"cannot parse {relative}: {exc}") from exc
    matches = [node for node in ast.walk(tree) if predicate(node)]
    if len(matches) != 1:
        raise FrameTimingProviderError(
            "PZFTP106", f"expected one {role} expression in {relative}, got {len(matches)}")
    node = matches[0]
    evidence = _source_span(
        relative, data, text, int(node.lineno), int(node.end_lineno or node.lineno),
        role)
    evidence["ast_sha256"] = _sha256(ast.dump(
        node, annotate_fields=True, include_attributes=False).encode("utf-8"))
    return evidence


def _equ_constants(root: Path, relative: str,
                   names: set[str]) -> tuple[dict[str, int], dict[str, Any]]:
    data, text = _read_text(root, relative)
    found: dict[str, tuple[int, int, str]] = {}
    pattern = re.compile(
        r"(?m)^\s*([A-Za-z_][A-Za-z0-9_]*)\s+EQU\s+"
        r"(?:0x([0-9A-Fa-f]+)|#([0-9A-Fa-f]+)|(\d+))\b")
    for match in pattern.finditer(text):
        name = match.group(1)
        if name not in names:
            continue
        raw = match.group(2) or match.group(3) or match.group(4)
        base = 16 if match.group(2) or match.group(3) else 10
        line = text.count("\n", 0, match.start()) + 1
        if name in found:
            raise FrameTimingProviderError(
                "PZFTP107", f"duplicate EQU {relative}:{name}")
        found[name] = (int(raw, base), line, match.group(0).strip())
    missing = sorted(names - set(found))
    if missing:
        raise FrameTimingProviderError(
            "PZFTP108", f"missing EQU in {relative}: {missing}")
    values = {name: found[name][0] for name in sorted(found)}
    rows = [{
        "name": name, "value": value, "line": found[name][1],
        "source": found[name][2],
        "source_span_sha256": _sha256(found[name][2].encode("utf-8")),
    } for name, value in values.items()]
    return values, {
        "role": "TSLib FT812 register/mode constants",
        "path": relative,
        "file_sha256": _sha256(data),
        "constants": rows,
    }


def _asm_block(root: Path, relative: str, label: str,
               role: str) -> tuple[str, dict[str, Any]]:
    data, text = _read_text(root, relative)
    lines = text.splitlines()
    start: int | None = None
    label_pattern = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):")
    for index, line in enumerate(lines):
        match = label_pattern.match(line.strip())
        if match and match.group(1) == label:
            start = index
            break
    if start is None:
        raise FrameTimingProviderError(
            "PZFTP109", f"ASM label absent {relative}:{label}")
    end = len(lines)
    for index in range(start + 1, len(lines)):
        match = label_pattern.match(lines[index].strip())
        if match:
            end = index
            break
    block = "\n".join(lines[start:end])
    return block, _source_span(
        relative, data, text, start + 1, end, role)


def _asm_macro_block(root: Path, relative: str, macro: str,
                     role: str) -> tuple[str, dict[str, Any]]:
    data, text = _read_text(root, relative)
    lines = text.splitlines()
    start: int | None = None
    declaration = re.compile(
        rf"^{re.escape(macro)}\s+macro(?:\s|$)", re.IGNORECASE)
    for index, line in enumerate(lines):
        if declaration.match(line.strip()):
            if start is not None:
                raise FrameTimingProviderError(
                    "PZFTP109", f"duplicate ASM macro {relative}:{macro}")
            start = index
    if start is None:
        raise FrameTimingProviderError(
            "PZFTP109", f"ASM macro absent {relative}:{macro}")
    end: int | None = None
    for index in range(start + 1, len(lines)):
        if lines[index].strip().lower() == "endm":
            end = index + 1
            break
    if end is None:
        raise FrameTimingProviderError(
            "PZFTP109", f"ASM macro is unterminated {relative}:{macro}")
    block = "\n".join(lines[start:end])
    return block, _source_span(
        relative, data, text, start + 1, end, role)


def _fraction_row(value: Fraction) -> dict[str, Any]:
    return {
        "numerator": value.numerator,
        "denominator": value.denominator,
        "decimal": f"{float(value):.12f}",
    }


def _closest_vcycle(pixel_clock: int, hcycle: int, target: Fraction,
                    minimum: int) -> tuple[int, list[dict[str, Any]], Fraction]:
    ideal = Fraction(pixel_clock, hcycle) / target
    lower = ideal.numerator // ideal.denominator
    candidates = sorted({max(minimum, lower), max(minimum, lower + 1)})
    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        refresh = Fraction(pixel_clock, hcycle * candidate)
        error = refresh - target
        rows.append({
            "vcycle": candidate,
            "refresh_hz": _fraction_row(refresh),
            "signed_error_hz": _fraction_row(error),
            "absolute_error_hz": _fraction_row(abs(error)),
        })
    selected_row = min(rows, key=lambda row: (
        Fraction(row["absolute_error_hz"]["numerator"],
                 row["absolute_error_hz"]["denominator"]),
        row["vcycle"]))
    selected = int(selected_row["vcycle"])
    return selected, rows, ideal


def _load_adapter_binding(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    relative = "Build/rtype_python_active_target_adapters_status.json"
    data, text = _read_text(root, relative)
    try:
        report = json.loads(text)
        validate_active_target_adapters_report(root, report)
    except (json.JSONDecodeError, ActiveTargetAdaptersError) as exc:
        raise FrameTimingProviderError(
            "PZFTP110", f"active adapter status rejected: {exc}") from exc
    families = [row for row in report["provider_catalog"]["families"]
                if row.get("family_id") == "frame-timing-55hz"]
    if len(families) != 1:
        raise FrameTimingProviderError(
            "PZFTP111", "frame-timing-55hz adapter family is not unique")
    sites = [row for row in report["inventory"]["sites"]
             if "frame-timing-55hz" in row.get("provider_family_ids", [])]
    if not sites:
        raise FrameTimingProviderError(
            "PZFTP112", "frame-timing-55hz has no active source sites")
    binding = {
        "path": relative,
        "file_sha256": _sha256(data),
        "semantic_sha256": report["semantic_sha256"],
        "family_id": "frame-timing-55hz",
        "family_status_at_generation": families[0]["status"],
        "family_semantic_sha256": families[0]["semantic_sha256"],
        "site_count": len(sites),
        "call_site_ids": sorted(str(row["call_site_id"]) for row in sites),
        "site_source_span_sha256": sorted(
            str(row["source_span_sha256"]) for row in sites),
    }
    return report, binding


def _input_file_row(root: Path, relative: str, role: str) -> dict[str, Any]:
    data, _text = _read_text(root, relative)
    return {"role": role, "path": relative, "sha256": _sha256(data)}


def analyze_frame_timing_provider(project_root: Path | str) -> dict[str, Any]:
    root = Path(project_root).resolve()
    app_rate, app_rate_evidence = _ast_constant(
        root, "Source/Python/rtype_port/app.py", "FRAME_RATE",
        "active Python application frame rate")
    tsfm_rate, tsfm_rate_evidence = _ast_constant(
        root, "Source/Python/rtype_port/tsfm.py", "FRAME_RATE",
        "active Python TSFM stream tick rate")
    if app_rate != 55 or tsfm_rate != app_rate:
        raise FrameTimingProviderError(
            "PZFTP113", f"Python/TSFM rate mismatch: {app_rate} vs {tsfm_rate}")
    app_deadline_evidence = _ast_expression_evidence(
        root, "Source/Python/rtype_port/app.py",
        "application deadline uses FRAME_RATE",
        lambda node: isinstance(node, ast.BinOp) and
        isinstance(node.op, ast.Div) and isinstance(node.right, ast.Name) and
        node.right.id == "FRAME_RATE")
    tsfm_divmod_evidence = _ast_expression_evidence(
        root, "Source/Python/rtype_port/tsfm.py",
        "TSFM sample cadence uses FRAME_RATE",
        lambda node: isinstance(node, ast.Call) and
        isinstance(node.func, ast.Name) and node.func.id == "divmod" and
        any(isinstance(arg, ast.Name) and arg.id == "FRAME_RATE"
            for arg in node.args))

    constant_names = {
        "F6_MUL", "H6_FPORCH", "H6_SYNC", "H6_BPORCH", "H6_VISIBLE",
        "V6_FPORCH", "V6_SYNC", "V6_BPORCH", "V6_VISIBLE",
        "FT_REG_HCYCLE", "FT_REG_HOFFSET", "FT_REG_HSYNC0",
        "FT_REG_HSYNC1", "FT_REG_HSIZE", "FT_REG_VCYCLE",
        "FT_REG_VOFFSET", "FT_REG_VSYNC0", "FT_REG_VSYNC1",
        "FT_REG_VSIZE", "FT_REG_PCLK", "FT_REG_DLSWAP",
        "FT_REG_INT_FLAGS", "FT_DLSWAP_FRAME", "FT_INT_SWAP",
    }
    constants, constants_evidence = _equ_constants(
        root, "Docs/TSLib/Include/FT/81x Const.inc", constant_names)
    const_data, const_text = _read_text(
        root, "Docs/TSLib/Include/FT/81x Const.inc")
    clock_header = re.search(
        r"(?m)^;\s*1024x768@59Hz\s*\(64Mhz\)\s*$", const_text)
    if clock_header is None:
        raise FrameTimingProviderError(
            "PZFTP114", "TSLib 1024x768 64MHz source claim is absent")
    clock_line = const_text.count("\n", 0, clock_header.start()) + 1
    clock_evidence = _source_span(
        "Docs/TSLib/Include/FT/81x Const.inc", const_data, const_text,
        clock_line, clock_line, "TSLib 1024x768 system clock")

    initialize_block, initialize_evidence = _asm_block(
        root, "Docs/TSLib/Include/FT/812 Func.asm", "Initialize",
        "FT.Initialize clock and register table loader")
    required_initialize = (
        "LD B, FT_CMD_CLKSEL", "OR #C0", "FT_WR_REG8 FT_REG_PCLK, 1",
        "FT_TAB_LOAD FT_REG_HCYCLE", "FT_TAB_LOAD FT_REG_VCYCLE",
    )
    if any(token not in initialize_block for token in required_initialize):
        raise FrameTimingProviderError(
            "PZFTP115", "FT.Initialize source contract changed")
    resolution_macro, resolution_macro_evidence = _asm_macro_block(
        root, "Docs/TSLib/Include/FT/812 Macro.inc", "FT_RESOLUTION",
        "FT_RESOLUTION selects the mode table and invokes FT.Initialize")
    if (resolution_macro.count("LD HL, Resolution?") != 1 or
            resolution_macro.count("CALL FT.Initialize") != 1):
        raise FrameTimingProviderError(
            "PZFTP115", "FT_RESOLUTION no longer invokes FT.Initialize once")

    manifest_relative = "Source/Tools/rtype_python_compiler.json"
    manifest_data, manifest_text = _read_text(root, manifest_relative)
    try:
        compiler_manifest = json.loads(manifest_text)
        ft_manifest = compiler_manifest["target"]["ft812"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise FrameTimingProviderError(
            "PZFTP116", f"compiler FT812 manifest invalid: {exc}") from exc
    expected_manifest = {
        "mode": "VM_1024_768_59Hz", "width": 1024, "height": 768,
        "hcycle": 1344, "pclk": 1, "safety_utilization": 0.90,
    }
    if any(ft_manifest.get(key) != value
           for key, value in expected_manifest.items()):
        raise FrameTimingProviderError(
            "PZFTP117", "compiler base FT812 profile changed")

    hsync0 = constants["H6_FPORCH"]
    hsync1 = hsync0 + constants["H6_SYNC"]
    hoffset = hsync1 + constants["H6_BPORCH"]
    hsize = constants["H6_VISIBLE"]
    hcycle = hoffset + hsize
    vsync0 = constants["V6_FPORCH"] - 1
    vsync1 = constants["V6_FPORCH"] + constants["V6_SYNC"] - 1
    voffset = (constants["V6_FPORCH"] + constants["V6_SYNC"] +
               constants["V6_BPORCH"] - 1)
    vsize = constants["V6_VISIBLE"]
    base_vcycle = (constants["V6_FPORCH"] + constants["V6_SYNC"] +
                   constants["V6_BPORCH"] + vsize)
    if (constants["F6_MUL"] != 8 or hsize != 1024 or vsize != 768 or
            hcycle != 1344 or constants["FT_REG_PCLK"] != 0x302070):
        raise FrameTimingProviderError(
            "PZFTP118", "TSLib base-mode derivation changed")
    system_clock_hz = 64_000_000
    pclk_divisor = int(ft_manifest["pclk"])
    pixel_clock_hz = system_clock_hz // pclk_divisor
    if system_clock_hz % pclk_divisor:
        raise FrameTimingProviderError("PZFTP119", "non-integral pixel clock")
    safe_line_cycles = int(hcycle * Fraction(9, 10))
    if safe_line_cycles != 1209:
        raise FrameTimingProviderError(
            "PZFTP120", f"practical scanline limit changed: {safe_line_cycles}")

    minimum_vcycle = voffset + vsize + 1
    selected_vcycle, candidate_rows, ideal_vcycle = _closest_vcycle(
        pixel_clock_hz, hcycle, app_rate, minimum_vcycle)
    refresh = Fraction(pixel_clock_hz, hcycle * selected_vcycle)
    signed_error = refresh - app_rate
    relative_error = signed_error / app_rate
    if selected_vcycle != 866:
        raise FrameTimingProviderError(
            "PZFTP121", f"unexpected closest VCYCLE {selected_vcycle}")

    main_loop, main_loop_evidence = _asm_block(
        root, "Source/ASM/main.asm", "MainLoop",
        "one Python/TSFM/render pass per target loop")
    ordered_calls = (
        "CALL Application_Update", "CALL TsfmMusic_Update", "CALL Render_Frame")
    if (any(main_loop.count(token) != 1 for token in ordered_calls) or
            not (main_loop.index(ordered_calls[0]) <
                 main_loop.index(ordered_calls[1]) <
                 main_loop.index(ordered_calls[2])) or
            "JR   MainLoop" not in main_loop):
        raise FrameTimingProviderError(
            "PZFTP122", "MainLoop no longer has one ordered Python/TSFM/render pass")
    render_frame, render_frame_evidence = _asm_block(
        root, "Source/ASM/render.asm", "Render_Frame",
        "render waits for previous FT812 swap")
    submit, submit_evidence = _asm_block(
        root, "Source/ASM/render.asm", "Render_SubmitFrame",
        "one FT812 frame-swap request")
    wait_swap, wait_swap_evidence = _asm_block(
        root, "Source/ASM/render.asm", "Render_WaitPreviousSwap",
        "FT812 swap interrupt and DLSWAP retirement fence")
    if render_frame.count("CALL Render_WaitPreviousSwap") != 1:
        raise FrameTimingProviderError(
            "PZFTP123", "Render_Frame swap wait count changed")
    swap_source = "FT_WR_REG8 FT_REG_DLSWAP, FT_DLSWAP_FRAME"
    if submit.count(swap_source) != 1:
        raise FrameTimingProviderError(
            "PZFTP124", "Render_SubmitFrame DLSWAP_FRAME count changed")
    if ("FT_RD_REG8 FT_REG_INT_FLAGS" not in wait_swap or
            "AND  FT_INT_SWAP" not in wait_swap or
            "FT_RD_REG8 FT_REG_DLSWAP" not in wait_swap or
            "JR   NZ, .waitDLSwap" not in wait_swap):
        raise FrameTimingProviderError(
            "PZFTP125", "swap retirement fence changed")

    platform_block, platform_evidence = _asm_block(
        root, "Source/ASM/platform.asm", "RTypeFrameTiming_ApplyGenerated",
        "generic generated timing platform hook")
    if (platform_block.count(
            "FT_WR_REG16 FT_REG_VCYCLE, RTYPE_PY_FT_VCYCLE") != 1 or
            len(re.findall(r"FT_WR_REG(?:8|16|32)\s+FT_REG_", platform_block)) != 1):
        raise FrameTimingProviderError(
            "PZFTP126", "platform timing hook is not a VCYCLE-only contract")
    init_video, init_video_evidence = _asm_block(
        root, "Source/ASM/platform.asm", "Init_Video",
        "base mode followed by generated timing hook")
    if ("FT_RESOLUTION VM_1024_768_59Hz, ResolutionWidthPtr" not in init_video or
            "CALL RTypeFrameTiming_ApplyGenerated" not in init_video or
            init_video.index("FT_RESOLUTION VM_1024_768_59Hz") >
            init_video.index("CALL RTypeFrameTiming_ApplyGenerated")):
        raise FrameTimingProviderError(
            "PZFTP127", "generated hook is not applied after the base mode")
    main_data, main_text = _read_text(root, "Source/ASM/main.asm")
    include_match = re.search(
        r'(?m)^\s*include\s+"generated_python_frame_timing\.inc"\s*$',
        main_text)
    if include_match is None:
        raise FrameTimingProviderError(
            "PZFTP128", "main.asm does not include generated timing contract")
    include_line = main_text.count("\n", 0, include_match.start()) + 1
    include_evidence = _source_span(
        "Source/ASM/main.asm", main_data, main_text, include_line, include_line,
        "generated timing include integration")

    _adapter_report, adapter_binding = _load_adapter_binding(root)

    base_registers = {
        "FT_REG_HSYNC0": hsync0, "FT_REG_HSYNC1": hsync1,
        "FT_REG_HOFFSET": hoffset, "FT_REG_HSIZE": hsize,
        "FT_REG_HCYCLE": hcycle, "FT_REG_VSYNC0": vsync0,
        "FT_REG_VSYNC1": vsync1, "FT_REG_VOFFSET": voffset,
        "FT_REG_VSIZE": vsize, "FT_REG_VCYCLE": base_vcycle,
        "FT_REG_PCLK": pclk_divisor,
    }
    selected_registers = dict(base_registers)
    selected_registers["FT_REG_VCYCLE"] = selected_vcycle
    changed_registers = [name for name in selected_registers
                         if selected_registers[name] != base_registers[name]]
    if changed_registers != ["FT_REG_VCYCLE"]:
        raise FrameTimingProviderError(
            "PZFTP129", f"non-blanking register changed: {changed_registers}")

    input_files = [
        _input_file_row(root, "Source/Python/rtype_port/app.py", "active game cadence"),
        _input_file_row(root, "Source/Python/rtype_port/tsfm.py", "active TSFM cadence"),
        _input_file_row(root, "Docs/TSLib/Include/FT/81x Const.inc", "FT812 mode/register constants"),
        _input_file_row(root, "Docs/TSLib/Include/FT/812 Func.asm", "FT812 clock/mode loader"),
        _input_file_row(root, "Docs/TSLib/Include/FT/812 Macro.inc", "FT812 resolution-to-initialize call path"),
        _input_file_row(root, manifest_relative, "base target manifest"),
        _input_file_row(root, "Source/ASM/main.asm", "one-tick main loop and generated include"),
        _input_file_row(root, "Source/ASM/render.asm", "DLSWAP cadence"),
        _input_file_row(root, "Source/ASM/platform.asm", "generic timing hook"),
        _input_file_row(root, "Source/Tools/pyz80_compiler/frame_timing_provider.py", "timing provider generator"),
    ]
    contract: dict[str, Any] = {
        "format": FRAME_TIMING_CONTRACT_FORMAT,
        "source_rates": {
            "python_application_hz": _fraction_row(app_rate),
            "python_tsfm_hz": _fraction_row(tsfm_rate),
            "rates_equal": app_rate == tsfm_rate,
        },
        "base_profile": {
            "mode": ft_manifest["mode"],
            "system_clock_hz": system_clock_hz,
            "clock_select_table_value": constants["F6_MUL"],
            "clock_select_command_parameter": 0xC0 | constants["F6_MUL"],
            "pclk_divisor": pclk_divisor,
            "pixel_clock_hz": pixel_clock_hz,
            "registers": base_registers,
            "horizontal_visible": hsize,
            "vertical_visible": vsize,
            "base_vertical_blank_lines": base_vcycle - vsize,
        },
        "selected_profile": {
            "registers": selected_registers,
            "changed_registers": changed_registers,
            "register_writes": [{
                "register": "FT_REG_VCYCLE",
                "address": constants["FT_REG_VCYCLE"],
                "width_bits": 16,
                "value": selected_vcycle,
                "source_symbol": "RTYPE_PY_FT_VCYCLE",
            }],
            "vertical_blank_lines": selected_vcycle - vsize,
            "added_vertical_blank_lines": selected_vcycle - base_vcycle,
            "effective_front_porch_lines": (
                constants["V6_FPORCH"] + selected_vcycle - base_vcycle),
            "sync_and_back_porch_unchanged": True,
            "visible_and_horizontal_timing_unchanged": True,
        },
        "selection_proof": {
            "formula": "refresh_hz = pixel_clock_hz / (HCYCLE * VCYCLE)",
            "ideal_vcycle": _fraction_row(ideal_vcycle),
            "exact_55hz_integer_vcycle_exists": ideal_vcycle.denominator == 1,
            "integer_candidates_around_crossing": candidate_rows,
            "selected_vcycle": selected_vcycle,
            "selection": "minimum absolute frequency error; lower VCYCLE on exact tie",
        },
        "actual_cadence": {
            "refresh_hz": _fraction_row(refresh),
            "signed_error_hz": _fraction_row(signed_error),
            "relative_error": _fraction_row(relative_error),
            "relative_error_percent": f"{float(relative_error * 100):.12f}",
            "relative_error_ppm": f"{float(relative_error * 1_000_000):.9f}",
            "frame_period_microseconds": _fraction_row(
                Fraction(1_000_000, 1) / refresh),
        },
        "scanline_budget": {
            "theoretical_cycles": hcycle,
            "safety_fraction": {"numerator": 9, "denominator": 10},
            "practical_cycle_limit_floor": safe_line_cycles,
            "scanline_period_microseconds": _fraction_row(
                Fraction(hcycle * 1_000_000, pixel_clock_hz)),
            "practical_budget_microseconds": _fraction_row(
                Fraction(safe_line_cycles * 1_000_000, pixel_clock_hz)),
        },
        "dl_swap_cadence": {
            "application_update_calls_per_loop": 1,
            "tsfm_update_calls_per_loop": 1,
            "render_calls_per_loop": 1,
            "dlswap_frame_request_sites_per_render": 1,
            "successful_render_submissions_per_loop_maximum": 1,
            "request_is_unconditional": False,
            "render_error_path_can_skip_swap_request": True,
            "waits_for_previous_swap_before_next_render": True,
            "dlswap_value": constants["FT_DLSWAP_FRAME"],
            "swap_interrupt_mask": constants["FT_INT_SWAP"],
            "static_one_tick_per_successfully_requested_frame": True,
            "measured_one_tick_per_physical_frame": False,
        },
        "adapter_family_binding": adapter_binding,
        "source_evidence": [
            app_rate_evidence, app_deadline_evidence,
            tsfm_rate_evidence, tsfm_divmod_evidence,
            constants_evidence, clock_evidence, resolution_macro_evidence,
            initialize_evidence,
            main_loop_evidence, render_frame_evidence, submit_evidence,
            wait_swap_evidence, include_evidence, init_video_evidence,
            platform_evidence,
        ],
        "proof": {
            "active_python_rate_is_literal_55hz": True,
            "tsfm_tick_rate_is_literal_55hz": True,
            "pixel_clock_is_64mhz_at_pclk_divisor_1": True,
            "physical_resolution_remains_1024x768": True,
            "hcycle_remains_1344": True,
            "practical_scanline_limit_is_1209": True,
            "only_vcycle_changes": True,
            "closest_integer_vcycle_is_proven": True,
            "platform_hook_uses_generated_vcycle_only": True,
            "source_python_was_not_modified": True,
        },
    }
    contract["semantic_sha256"] = _json_sha256(contract)

    report: dict[str, Any] = {
        "format": FRAME_TIMING_PROVIDER_FORMAT,
        "input_binding": {
            "files": input_files,
            "compiler_ft812_manifest": {
                "path": manifest_relative,
                "file_sha256": _sha256(manifest_data),
                "values": expected_manifest,
            },
            "active_target_adapters": adapter_binding,
        },
        "contract": contract,
        "generated_artifacts": {},
        "integration": {
            "include_path": DEFAULT_INCLUDE,
            "manifest_path": DEFAULT_MANIFEST,
            "platform_hook": "RTypeFrameTiming_ApplyGenerated",
            "base_mode_load": "FT_RESOLUTION VM_1024_768_59Hz",
            "generated_override_registers": ["FT_REG_VCYCLE"],
            "backend_consumes_contract": False,
            "assembler_link_proof_present": False,
            "measured_ft812_timing_proof_present": False,
        },
    }
    include_data = render_frame_timing_include(report).encode("utf-8")
    manifest_output = render_frame_timing_manifest(report).encode("utf-8")
    report["generated_artifacts"] = {
        "include": {"path": DEFAULT_INCLUDE, "sha256": _sha256(include_data),
                    "size": len(include_data)},
        "manifest": {"path": DEFAULT_MANIFEST,
                     "sha256": _sha256(manifest_output),
                     "size": len(manifest_output)},
    }
    blockers = [
        {"code": "PZFTP201", "count": 1,
         "detail": "generated include has no assembler/link/map proof"},
        {"code": "PZFTP202", "count": 1,
         "detail": "64MHz, VCYCLE and refresh have no on-device REG_CLOCK/scanout measurement"},
        {"code": "PZFTP203", "count": 1,
         "detail": "DLSWAP-to-logical-tick cadence has no emulator/hardware trace proof"},
        {"code": "PZFTP204", "count": 1,
         "detail": "active adapter/backend still reports frame-timing-55hz unconnected"},
    ]
    report["semantic_sha256"] = _json_sha256(_semantic_payload(report))
    report["status"] = FRAME_TIMING_PROVIDER_STATUS
    report["live"] = False
    report["live_blockers"] = blockers
    validate_frame_timing_provider_report(root, report, validate_artifacts=False)
    return report


def render_frame_timing_include(report: Mapping[str, Any]) -> str:
    contract = report["contract"]
    base = contract["base_profile"]
    selected = contract["selected_profile"]
    cadence = contract["actual_cadence"]
    scanline = contract["scanline_budget"]
    error_ppm_x1000 = round(float(Fraction(
        cadence["relative_error"]["numerator"],
        cadence["relative_error"]["denominator"]) * 1_000_000_000))
    refresh = cadence["refresh_hz"]
    return (
        "; Generated by check_pyz80_frame_timing_provider.py. DO NOT EDIT.\n"
        f"; contract semantic SHA-256: {contract['semantic_sha256']}\n"
        "RTYPE_PY_TIMING_CONTRACT_VERSION       EQU 1\n"
        "RTYPE_PY_FRAME_RATE_MILLIHZ            EQU 55000\n"
        "RTYPE_PY_TSF_MUSIC_TICK_MILLIHZ        EQU 55000\n"
        f"RTYPE_PY_FT_SYSTEM_CLOCK_HZ            EQU {base['system_clock_hz']}\n"
        f"RTYPE_PY_FT_PCLK_DIVISOR               EQU {base['pclk_divisor']}\n"
        f"RTYPE_PY_FT_PIXEL_CLOCK_HZ             EQU {base['pixel_clock_hz']}\n"
        f"RTYPE_PY_FT_HSIZE                      EQU {base['horizontal_visible']}\n"
        f"RTYPE_PY_FT_VSIZE                      EQU {base['vertical_visible']}\n"
        f"RTYPE_PY_FT_HCYCLE                     EQU {base['registers']['FT_REG_HCYCLE']}\n"
        f"RTYPE_PY_FT_VOFFSET                    EQU {base['registers']['FT_REG_VOFFSET']}\n"
        f"RTYPE_PY_FT_VCYCLE                     EQU {selected['registers']['FT_REG_VCYCLE']}\n"
        f"RTYPE_PY_FT_VERTICAL_BLANK_LINES       EQU {selected['vertical_blank_lines']}\n"
        f"RTYPE_PY_FT_ADDED_BLANK_LINES          EQU {selected['added_vertical_blank_lines']}\n"
        f"RTYPE_PY_FT_SAFE_SCANLINE_CYCLES       EQU {scanline['practical_cycle_limit_floor']}\n"
        f"RTYPE_PY_FT_REFRESH_NUMERATOR          EQU {refresh['numerator']}\n"
        f"RTYPE_PY_FT_REFRESH_DENOMINATOR        EQU {refresh['denominator']}\n"
        f"RTYPE_PY_FT_REFRESH_ERROR_PPM_X1000    EQU {error_ppm_x1000}\n\n"
        "                ASSERT RTYPE_PY_TIMING_CONTRACT_VERSION = 1\n"
        "                ASSERT RTYPE_PY_FRAME_RATE_MILLIHZ = RTYPE_PY_TSF_MUSIC_TICK_MILLIHZ\n"
        "                ASSERT RTYPE_PY_FT_HSIZE = H6_VISIBLE\n"
        "                ASSERT RTYPE_PY_FT_VSIZE = V6_VISIBLE\n"
        "                ASSERT RTYPE_PY_FT_HCYCLE = H6_FPORCH + H6_SYNC + H6_BPORCH + H6_VISIBLE\n"
        "                ASSERT RTYPE_PY_FT_VOFFSET = V6_FPORCH + V6_SYNC + V6_BPORCH - 1\n"
        "                ASSERT RTYPE_PY_FT_VCYCLE > RTYPE_PY_FT_VOFFSET + RTYPE_PY_FT_VSIZE\n"
        "                ASSERT RTYPE_PY_FT_SAFE_SCANLINE_CYCLES = 1209\n")


def render_frame_timing_manifest(report: Mapping[str, Any]) -> str:
    value = {
        "format": FRAME_TIMING_CONTRACT_FORMAT,
        "contract": report["contract"],
        "generated_by": "pyz80_compiler.frame_timing_provider",
        "live": False,
    }
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def validate_frame_timing_provider_report(
        project_root: Path | str, report: Mapping[str, Any], *,
        validate_artifacts: bool = True) -> None:
    root = Path(project_root).resolve()
    if report.get("format") != FRAME_TIMING_PROVIDER_FORMAT:
        raise FrameTimingProviderError("PZFTP401", "report format mismatch")
    if (report.get("status") != FRAME_TIMING_PROVIDER_STATUS or
            report.get("live") is not False):
        raise FrameTimingProviderError("PZFTP402", "status/live mismatch")
    if report.get("semantic_sha256") != _json_sha256(_semantic_payload(report)):
        raise FrameTimingProviderError("PZFTP403", "report semantic hash mismatch")
    contract = report.get("contract")
    if not isinstance(contract, dict):
        raise FrameTimingProviderError("PZFTP404", "contract missing")
    contract_copy = dict(contract)
    contract_digest = contract_copy.pop("semantic_sha256", None)
    if (contract.get("format") != FRAME_TIMING_CONTRACT_FORMAT or
            contract_digest != _json_sha256(contract_copy)):
        raise FrameTimingProviderError("PZFTP405", "contract semantic hash mismatch")
    files = report.get("input_binding", {}).get("files")
    if not isinstance(files, list) or not files:
        raise FrameTimingProviderError("PZFTP406", "input file binding missing")
    for row in files:
        path = root / Path(str(row.get("path")))
        try:
            digest = _sha256(path.read_bytes())
        except OSError as exc:
            raise FrameTimingProviderError(
                "PZFTP407", f"bound input missing {path}: {exc}") from exc
        if digest != row.get("sha256"):
            raise FrameTimingProviderError(
                "PZFTP408", f"bound input changed: {row.get('path')}")
    adapter = report.get("input_binding", {}).get("active_target_adapters", {})
    adapter_path = root / Path(str(adapter.get("path")))
    try:
        adapter_data = adapter_path.read_bytes()
        adapter_report = json.loads(adapter_data.decode("utf-8"))
        validate_active_target_adapters_report(root, adapter_report)
    except (OSError, UnicodeError, json.JSONDecodeError,
            ActiveTargetAdaptersError) as exc:
        raise FrameTimingProviderError(
            "PZFTP409", f"bound adapter report rejected: {exc}") from exc
    families = [row for row in adapter_report["provider_catalog"]["families"]
                if row.get("family_id") == "frame-timing-55hz"]
    sites = [row for row in adapter_report["inventory"]["sites"]
             if "frame-timing-55hz" in row.get("provider_family_ids", [])]
    expected_adapter = {
        "path": str(adapter.get("path")),
        "file_sha256": _sha256(adapter_data),
        "semantic_sha256": adapter_report["semantic_sha256"],
        "family_id": "frame-timing-55hz",
        "family_status_at_generation": families[0]["status"] if len(families) == 1 else None,
        "family_semantic_sha256": families[0]["semantic_sha256"] if len(families) == 1 else None,
        "site_count": len(sites),
        "call_site_ids": sorted(str(row["call_site_id"]) for row in sites),
        "site_source_span_sha256": sorted(
            str(row["source_span_sha256"]) for row in sites),
    }
    if dict(adapter) != expected_adapter:
        raise FrameTimingProviderError("PZFTP410", "adapter family binding changed")

    base = contract.get("base_profile", {})
    selected = contract.get("selected_profile", {})
    cadence = contract.get("actual_cadence", {})
    if (base.get("system_clock_hz") != 64_000_000 or
            base.get("pclk_divisor") != 1 or
            base.get("pixel_clock_hz") != 64_000_000 or
            base.get("horizontal_visible") != 1024 or
            base.get("vertical_visible") != 768 or
            base.get("registers", {}).get("FT_REG_HCYCLE") != 1344 or
            selected.get("changed_registers") != ["FT_REG_VCYCLE"] or
            selected.get("registers", {}).get("FT_REG_VCYCLE") != 866 or
            selected.get("vertical_blank_lines") != 98 or
            selected.get("added_vertical_blank_lines") != 60):
        raise FrameTimingProviderError("PZFTP411", "timing register contract mismatch")
    exact_refresh = Fraction(64_000_000, 1344 * 866)
    refresh_row = cadence.get("refresh_hz", {})
    if (refresh_row.get("numerator") != exact_refresh.numerator or
            refresh_row.get("denominator") != exact_refresh.denominator or
            contract.get("scanline_budget", {}).get(
                "practical_cycle_limit_floor") != 1209):
        raise FrameTimingProviderError("PZFTP412", "frequency/budget proof mismatch")
    candidates = contract.get("selection_proof", {}).get(
        "integer_candidates_around_crossing")
    if (not isinstance(candidates, list) or
            [row.get("vcycle") for row in candidates] != [865, 866] or
            contract.get("selection_proof", {}).get("selected_vcycle") != 866):
        raise FrameTimingProviderError("PZFTP413", "closest-vcycle proof mismatch")
    swap = contract.get("dl_swap_cadence", {})
    if (swap.get("application_update_calls_per_loop") != 1 or
            swap.get("tsfm_update_calls_per_loop") != 1 or
            swap.get("render_calls_per_loop") != 1 or
            swap.get("dlswap_frame_request_sites_per_render") != 1 or
            swap.get("successful_render_submissions_per_loop_maximum") != 1 or
            swap.get("request_is_unconditional") is not False or
            swap.get("render_error_path_can_skip_swap_request") is not True or
            swap.get("static_one_tick_per_successfully_requested_frame") is not True or
            swap.get("measured_one_tick_per_physical_frame") is not False):
        raise FrameTimingProviderError("PZFTP414", "DLSWAP cadence claim mismatch")
    integration = report.get("integration", {})
    if (integration.get("backend_consumes_contract") is not False or
            integration.get("assembler_link_proof_present") is not False or
            integration.get("measured_ft812_timing_proof_present") is not False):
        raise FrameTimingProviderError("PZFTP415", "unsupported live proof claim")
    expected_blockers = [
        {"code": "PZFTP201", "count": 1,
         "detail": "generated include has no assembler/link/map proof"},
        {"code": "PZFTP202", "count": 1,
         "detail": "64MHz, VCYCLE and refresh have no on-device REG_CLOCK/scanout measurement"},
        {"code": "PZFTP203", "count": 1,
         "detail": "DLSWAP-to-logical-tick cadence has no emulator/hardware trace proof"},
        {"code": "PZFTP204", "count": 1,
         "detail": "active adapter/backend still reports frame-timing-55hz unconnected"},
    ]
    if report.get("live_blockers") != expected_blockers:
        raise FrameTimingProviderError("PZFTP416", "live blocker set mismatch")
    artifacts = report.get("generated_artifacts")
    if (not isinstance(artifacts, dict) or
            artifacts.get("include", {}).get("path") != DEFAULT_INCLUDE or
            artifacts.get("manifest", {}).get("path") != DEFAULT_MANIFEST or
            integration.get("include_path") != DEFAULT_INCLUDE or
            integration.get("manifest_path") != DEFAULT_MANIFEST or
            integration.get("generated_override_registers") !=
            ["FT_REG_VCYCLE"]):
        raise FrameTimingProviderError("PZFTP417", "artifact binding missing")
    expected_contents = {
        "include": render_frame_timing_include(report).encode("utf-8"),
        "manifest": render_frame_timing_manifest(report).encode("utf-8"),
    }
    for name, content in expected_contents.items():
        row = artifacts.get(name, {})
        if (row.get("sha256") != _sha256(content) or
                row.get("size") != len(content)):
            raise FrameTimingProviderError(
                "PZFTP418", f"generated {name} binding mismatch")
        if validate_artifacts:
            path = root / Path(str(row.get("path")))
            try:
                actual = path.read_bytes()
            except OSError as exc:
                raise FrameTimingProviderError(
                    "PZFTP419", f"generated artifact absent {path}: {exc}") from exc
            if actual != content:
                raise FrameTimingProviderError(
                    "PZFTP420", f"generated artifact stale: {row.get('path')}")
