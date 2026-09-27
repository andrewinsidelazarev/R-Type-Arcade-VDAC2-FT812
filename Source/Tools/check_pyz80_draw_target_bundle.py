#!/usr/bin/env python3
"""Fail-closed linked certificate for the source-derived draw target bundle.

This certificate deliberately links the generated render-order container,
persistent draw-state provider, compact draw VM and six-byte FT812 chunker as
one SDCC image.  The FT812/HQT3 inputs are reduced to an exact, hash-bound
source slice containing only symbols reachable by the fast chunk path.  This
avoids reporting the sum of unrelated object-file sizes as if it were a link.

The link proves symbol uniqueness, resolution and concrete CODE/DATA sizes.
Assembly analysis proves stack bounds only for paths whose callees are known.
Application callbacks, provider installation and queue/page rotation remain
explicit blockers; this tool can never claim that the bundle is live-ready.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from pyz80_compiler.draw_state_backend import (
    build_draw_state_model,
    emit_draw_state_backend,
)
from pyz80_compiler.draw_vm_backend import emit_draw_vm_backend
from pyz80_compiler.manifest import CompilerManifest
from pyz80_compiler.render_order_backend import emit_render_order_backend
from pyz80_compiler.toolchain import locate_sdcc


FORMAT = "pyz80-draw-target-linked-bundle-certificate-v1"
STATUS = "LINKED_TARGET_BUNDLE_PROVED_LIVE_INTEGRATION_BLOCKED"
PINNED_ARGUMENTS = (
    "-mz80",
    "--std-c11",
    "--sdcccall", "1",
    "--fno-omit-frame-pointer",
    "--stack-auto",
    "--opt-code-speed",
    "--no-c-code-in-asm",
)
LINK_ARGUMENTS = (
    "-mz80",
    "--no-std-crt0",
    "--code-loc", "0x8000",
    "--data-loc", "0xC000",
    "-Wl-m",
)

CORE_FILES = (
    "Source/C/generated/rtype_python_render_order.c",
    "Source/C/generated/rtype_python_render_order.h",
    "Source/C/generated/rtype_python_render_order.json",
    "Source/C/generated/rtype_python_draw_state.c",
    "Source/C/generated/rtype_python_draw_state.h",
    "Source/C/generated/rtype_python_draw_state.json",
    "Source/C/generated/rtype_python_draw_vm.c",
    "Source/C/generated/rtype_python_draw_vm.h",
    "Source/C/generated/rtype_python_draw_vm.json",
    "Source/C/ft812/pyz80_draw_fast_chunker.c",
    "Source/C/ft812/pyz80_draw_fast_chunker.h",
    "Source/C/ft812/pyz80_ft812.c",
    "Source/C/ft812/pyz80_ft812.h",
    "Source/C/generated/rtype_python_hq_templates.c",
    "Source/C/generated/rtype_python_hq_templates.h",
    "Build/rtype_python_assets.json",
    "Build/rtype_python_draw_vm_stack_status.json",
    "Build/rtype_python_frame_budget_status.json",
    "run_python.cmd",
)

HQ_REQUIRED_SYMBOLS = (
    "PyZ80FT_HQTemplates",
    "PyZ80FT_HQTemplateHash",
    "PyZ80FT_HQBatchGeometry",
    "PyZ80FT_HQAppendMap",
    "PyZ80FT_HQAppendAddress",
    "PyZ80FT_HQAppendSize",
)
HQ_EXCLUDED_SYMBOLS = (
    "PyZ80FT_TypedResources",
    "PyZ80FT_HQTemplateCells",
    "PyZ80FT_HQBitmapStates",
)
EXPECTED_DIRECT_OBJECTS = (
    "rtype_python_render_order.rel",
    "rtype_python_draw_state.rel",
    "rtype_python_draw_vm.rel",
    "pyz80_draw_fast_chunker.rel",
    "ft812_fast_slice.rel",
    "hqt3_fast_slice.rel",
)
EXPECTED_RUNTIME_OBJECTS = (
    "__sdcc_call_iy.rel",
    "memcpy.rel",
)
EXPECTED_PUBLIC_SYMBOLS = (
    "_rtype_python_render_order_reset",
    "_rtype_python_render_order_slot_at",
    "_rtype_python_draw_state_reset",
    "_rtype_python_draw_state_load_object",
    "_rtype_python_draw_vm_produce",
    "_rtype_python_draw_vm_stream",
    "_PyZ80DrawFastChunk_Initialize",
    "_PyZ80DrawFastChunk_Emit",
    "_PyZ80DrawFastChunk_Finish",
    "_PyZ80DrawFastChunk_Run",
    "_PyZ80DrawFastChunk_SubmitFT812",
    "_PyZ80FT_FindHQTemplate",
    "_PyZ80FT_BuildSpriteBatchFast",
    "_PyZ80FT_BatchResolved",
)


class DrawTargetBundleError(RuntimeError):
    """A source, compiler, link, ABI or stack fact is no longer proved."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value: object) -> bytes:
    return (json.dumps(
        value, ensure_ascii=False, sort_keys=True, indent=2,
    ) + "\n").encode("utf-8")


def _atomic_json(path: Path, value: Mapping[str, object]) -> None:
    data = _json_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _read_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DrawTargetBundleError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise DrawTargetBundleError(f"JSON root is not an object: {path}")
    return value


def _file_record(root: Path, relative: str) -> dict[str, object]:
    try:
        data = (root / relative).read_bytes()
    except OSError as exc:
        raise DrawTargetBundleError(f"missing bundle input {relative}") from exc
    return {"path": relative, "bytes": len(data), "sha256": _sha256(data)}


def _exact_generated(
        root: Path, artifacts: object, directory: str,
        ) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for role, name, text in (
            ("header", artifacts.header_name, artifacts.header),
            ("source", artifacts.source_name, artifacts.source),
            ("manifest", artifacts.manifest_name, artifacts.manifest)):
        expected = text.encode("utf-8")
        relative = f"{directory}/{name}"
        actual = (root / relative).read_bytes()
        if actual != expected:
            raise DrawTargetBundleError(
                f"generated artifact is stale/non-reproducible: {relative}")
        result[role] = {
            "path": relative,
            "bytes": len(actual),
            "sha256": _sha256(actual),
        }
    return result


def _extract_c_array(text: str, symbol: str) -> tuple[int, int, str]:
    """Return one complete top-level generated array declaration."""
    matches = list(re.finditer(
        rf"(?m)^const\s+[A-Za-z_][A-Za-z0-9_]*\s*\r?\n"
        rf"{re.escape(symbol)}\s*\[[^\]]+\]\s*=\s*\{{",
        text))
    if len(matches) != 1:
        raise DrawTargetBundleError(
            f"HQT3 source has {len(matches)} declarations for {symbol}")
    start = matches[0].start()
    opening = text.find("{", matches[0].start(), matches[0].end())
    depth = 0
    cursor = opening
    while cursor < len(text):
        char = text[cursor]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                end = cursor + 1
                while end < len(text) and text[end] in " \t\r":
                    end += 1
                if end >= len(text) or text[end] != ";":
                    raise DrawTargetBundleError(
                        f"HQT3 declaration {symbol} has no terminal semicolon")
                end += 1
                while end < len(text) and text[end] in "\r\n":
                    end += 1
                return start, end, text[start:end]
        cursor += 1
    raise DrawTargetBundleError(f"HQT3 declaration {symbol} is unterminated")


def _extract_ft_fast_slice(text: str) -> tuple[str, list[dict[str, object]]]:
    prelude_end_token = "static uint8_t PyZ80FT_QueuePageValid"
    find_start_token = "uint16_t PyZ80FT_FindHQTemplate("
    find_end_token = "uint16_t PyZ80FT_ResolveBankKey("
    target_start_token = "#if defined(__SDCC)"
    target_end_token = "#else"
    points = {
        "prelude_end": text.find(prelude_end_token),
        "find_start": text.find(find_start_token),
        "find_end": text.find(find_end_token),
        "target_start": text.find(target_start_token),
    }
    if any(value < 0 for value in points.values()):
        raise DrawTargetBundleError(f"FT812 fast slice marker missing: {points}")
    target_end = text.find(target_end_token, points["target_start"])
    if target_end < 0:
        raise DrawTargetBundleError("FT812 target block has no #else marker")
    if not (
        points["prelude_end"] < points["find_start"] <
        points["find_end"] < points["target_start"] < target_end
    ):
        raise DrawTargetBundleError("FT812 fast slice marker order changed")
    spans = (
        ("shared_prelude", 0, points["prelude_end"]),
        ("hq_lookup", points["find_start"], points["find_end"]),
        ("target_fast_batch", points["target_start"], target_end),
    )
    pieces = [text[start:end].rstrip() for _, start, end in spans]
    source = "\n\n".join(pieces) + "\n\n#endif\n"
    required_tokens = (
        "PyZ80FT_SpriteBatchPrefix",
        "PyZ80FT_BatchResolved",
        "PyZ80FT_FindHQTemplate",
        "PyZ80FT_BuildSpriteBatchFast",
        "PyZ80FT_BuildSpriteBatchShared",
        "PyZ80FT_HQTemplateHash",
        "PyZ80FT_HQTemplates",
        "PyZ80FT_HQBatchGeometry",
        "PyZ80FT_HQAppendMap",
        "PyZ80FT_HQAppendAddress",
        "PyZ80FT_HQAppendSize",
    )
    missing = [token for token in required_tokens if token not in source]
    excluded = (
        "PyZ80FT_QueueInitialize(",
        "PyZ80FT_ResolveBankKey(",
        "PyZ80FT_QueuePushTemplate(",
        "PyZ80FT_QueueCommit(",
    )
    leaked = [token for token in excluded if token in source]
    if missing or leaked:
        raise DrawTargetBundleError(
            f"FT812 dependency slice mismatch: missing={missing}, leaked={leaked}")
    records = [{
        "role": role,
        "start_byte": len(text[:start].encode("utf-8")),
        "end_byte_exclusive": len(text[:end].encode("utf-8")),
        "bytes": len(text[start:end].encode("utf-8")),
        "sha256": _sha256(text[start:end].encode("utf-8")),
    } for role, start, end in spans]
    return source, records


def _extract_hq_fast_slice(text: str) -> tuple[str, list[dict[str, object]]]:
    spans = [_extract_c_array(text, symbol) for symbol in HQ_REQUIRED_SYMBOLS]
    if spans != sorted(spans, key=lambda item: item[0]):
        raise DrawTargetBundleError("HQT3 required declarations changed order")
    for symbol in HQ_EXCLUDED_SYMBOLS:
        _extract_c_array(text, symbol)
    source = (
        "/* Exact declaration slice of generated active-Python HQT3 data. */\n"
        '#include "rtype_python_hq_templates.h"\n\n' +
        "\n".join(item[2].rstrip() for item in spans) + "\n")
    records = []
    for symbol, (start, end, fragment) in zip(HQ_REQUIRED_SYMBOLS, spans):
        records.append({
            "symbol": symbol,
            "start_byte": len(text[:start].encode("utf-8")),
            "end_byte_exclusive": len(text[:end].encode("utf-8")),
            "bytes": len(fragment.encode("utf-8")),
            "sha256": _sha256(fragment.encode("utf-8")),
        })
    for symbol in HQ_EXCLUDED_SYMBOLS:
        if re.search(rf"(?m)^\s*{re.escape(symbol)}\s*\[", source):
            raise DrawTargetBundleError(
                f"unreachable HQT3 table leaked into slice: {symbol}")
    return source, records


def build_dependency_slices(root: Path) -> dict[str, object]:
    ft_path = root / "Source/C/ft812/pyz80_ft812.c"
    hq_path = root / "Source/C/generated/rtype_python_hq_templates.c"
    ft_text = ft_path.read_text(encoding="utf-8")
    hq_text = hq_path.read_text(encoding="utf-8")
    ft_source, ft_spans = _extract_ft_fast_slice(ft_text)
    hq_source, hq_spans = _extract_hq_fast_slice(hq_text)
    return {
        "ft_source": ft_source,
        "hq_source": hq_source,
        "report": {
            "algorithm": "exact-source-spans-v1",
            "ft812": {
                "source_path": "Source/C/ft812/pyz80_ft812.c",
                "source_sha256": _sha256(ft_path.read_bytes()),
                "slice_bytes": len(ft_source.encode("utf-8")),
                "slice_sha256": _sha256(ft_source.encode("utf-8")),
                "spans": ft_spans,
                "exports": [
                    "PyZ80FT_FindHQTemplate",
                    "PyZ80FT_BuildSpriteBatchFast",
                    "PyZ80FT_BuildSpriteBatch",
                    "PyZ80FT_BuildSpriteBatchShared",
                    "PyZ80FT_BatchResolved",
                ],
                "excluded_public_subsystems": [
                    "queue acquire/commit",
                    "direct descriptor/template push",
                    "bank-key resolver",
                    "portable host reference batch implementation",
                ],
            },
            "hqt3": {
                "source_path": (
                    "Source/C/generated/rtype_python_hq_templates.c"),
                "source_sha256": _sha256(hq_path.read_bytes()),
                "slice_bytes": len(hq_source.encode("utf-8")),
                "slice_sha256": _sha256(hq_source.encode("utf-8")),
                "included_symbols": list(HQ_REQUIRED_SYMBOLS),
                "excluded_symbols": list(HQ_EXCLUDED_SYMBOLS),
                "spans": hq_spans,
            },
        },
    }


def _run(
        command: list[str], directory: Path, environment: Mapping[str, str],
        timeout: int = 240,
        ) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command, cwd=directory, check=False, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        encoding="utf-8", errors="replace", timeout=timeout,
        env=environment)
    if completed.returncode != 0:
        raise DrawTargetBundleError(
            f"command failed ({completed.returncode}): " +
            " ".join(command) + "\n" + completed.stdout)
    return completed


def _area_map(text: str) -> dict[str, tuple[int, int]]:
    result: dict[str, tuple[int, int]] = {}
    for match in re.finditer(
            r"^(\S+)\s+([0-9A-Fa-f]{8})\s+([0-9A-Fa-f]{8})\s+=",
            text, re.MULTILINE):
        name = match.group(1)
        pair = (int(match.group(2), 16), int(match.group(3), 16))
        if name in result and result[name] != pair:
            raise DrawTargetBundleError(f"link map repeats area {name}")
        result[name] = pair
    return result


def _linked_files(text: str) -> tuple[list[str], list[str]]:
    direct: list[str] = []
    runtime: list[str] = []
    section = ""
    for line in text.splitlines():
        if line.startswith("Files Linked"):
            section = "direct"
            continue
        if line.startswith("Libraries Linked"):
            section = "runtime"
            continue
        if line.startswith("User Base Address"):
            section = ""
        direct_match = re.match(r"^(\S+\.rel)\s+\[", line)
        runtime_match = re.search(r"\[\s*(\S+\.rel)\s*\]", line)
        if direct_match and section == "direct":
            direct.append(Path(direct_match.group(1)).name)
        elif runtime_match and section == "runtime":
            runtime.append(Path(runtime_match.group(1)).name)
    return direct, runtime


def _map_definitions(text: str) -> dict[str, tuple[int, str]]:
    result: dict[str, tuple[int, str]] = {}
    for match in re.finditer(
            r"^\s+([0-9A-Fa-f]{8})\s+(\S+)\s+(\S+)\s*$",
            text, re.MULTILINE):
        address = int(match.group(1), 16)
        symbol = match.group(2)
        module = match.group(3)
        if symbol in result and result[symbol] != (address, module):
            raise DrawTargetBundleError(
                f"link map has conflicting definition for {symbol}")
        result[symbol] = (address, module)
    return result


def _sdnm_symbols(text: str) -> tuple[dict[str, str], set[str]]:
    defined: dict[str, str] = {}
    undefined: set[str] = set()
    for line in text.splitlines():
        match = re.match(
            r"^(?:[0-9A-Fa-f]{8}|\s{8})\s+([AUTRDB])\s+(\S+)\s*$", line)
        if not match:
            continue
        kind, symbol = match.group(1), match.group(2)
        if kind == "U":
            undefined.add(symbol)
        else:
            defined[symbol] = kind
    return defined, undefined


@dataclass(frozen=True)
class Instruction:
    source_line: int
    op: str
    args: str
    raw: str
    statement_index: int


@dataclass(frozen=True)
class FunctionAssembly:
    name: str
    instructions: tuple[Instruction, ...]
    labels: Mapping[str, int]
    jump_tables: Mapping[int, tuple[int, ...]]


@dataclass(frozen=True)
class MachineState:
    depth: int
    ix_depth: int | None = None
    ix_constant: int | None = None
    iy_depth: int | None = None
    iy_constant: int | None = None


@dataclass(frozen=True)
class Peak:
    depth: int
    witness: tuple[str, ...]


@dataclass(frozen=True)
class StackSummary:
    maximum_depth_from_entry_sp: int
    return_delta_bytes: int
    callback_entry_peaks: Mapping[str, Peak]
    maximum_witness: tuple[str, ...]
    explored_states: int


@dataclass(frozen=True)
class CallbackABI:
    name: str
    stack_argument_bytes: int


_CONDITIONS = frozenset(("nz", "z", "nc", "c", "po", "pe", "p", "m"))


def _split_op(line: str) -> tuple[str, str] | None:
    code = line.split(";", 1)[0].strip()
    if not code or code.startswith("."):
        return None
    match = re.match(r"([A-Za-z][A-Za-z0-9_.]*)\s*(.*)$", code)
    if match is None:
        return None
    args = re.sub(r"\s*,\s*", ",", match.group(2).strip().lower())
    return match.group(1).lower(), args


def _parse_function_block(
        lines: list[str], start: int, stop: int, name: str,
        ) -> FunctionAssembly:
    statements: list[tuple[str, int, str]] = []
    for line_index in range(start, stop):
        raw = lines[line_index]
        code = raw.split(";", 1)[0].strip()
        if not code:
            continue
        label_match = re.match(
            r"([_A-Za-z0-9.][\w.$]*):{1,2}\s*(.*)$", code)
        if label_match:
            statements.append(("label", line_index + 1, label_match.group(1)))
            code = label_match.group(2).strip()
            if not code:
                continue
        if code.startswith("."):
            statements.append(("directive", line_index + 1, code))
            continue
        parsed = _split_op(code)
        if parsed is None:
            raise DrawTargetBundleError(
                f"cannot parse assembly line {line_index + 1}: {raw}")
        statements.append((
            "instruction", line_index + 1,
            parsed[0] + (" " + parsed[1] if parsed[1] else ""),
        ))
    instructions: list[Instruction] = []
    statement_to_instruction: dict[int, int] = {}
    for statement_index, (kind, source_line, value) in enumerate(statements):
        if kind != "instruction":
            continue
        op, _, args = value.partition(" ")
        statement_to_instruction[statement_index] = len(instructions)
        instructions.append(Instruction(
            source_line, op, args, value, statement_index))

    def next_instruction(index: int) -> int | None:
        while index < len(statements):
            found = statement_to_instruction.get(index)
            if found is not None:
                return found
            index += 1
        return None

    labels: dict[str, int] = {}
    for index, (kind, source_line, value) in enumerate(statements):
        if kind != "label":
            continue
        target = next_instruction(index + 1)
        if target is not None:
            normalized = value.lower()
            if normalized in labels:
                raise DrawTargetBundleError(
                    f"duplicate local label {value} in {name}:{source_line}")
            labels[normalized] = target
    jump_tables: dict[int, tuple[int, ...]] = {}
    for index, instruction in enumerate(instructions):
        if instruction.op != "jp" or instruction.args != "(hl)":
            continue
        cursor = instruction.statement_index + 1
        table_labels: list[str] = []
        while cursor < len(statements):
            kind, _, value = statements[cursor]
            if kind == "instruction":
                break
            if kind == "directive" and value.lower().startswith(".dw"):
                table_labels.extend(
                    item.strip() for item in value[3:].strip().split(","))
            cursor += 1
        if table_labels:
            try:
                jump_tables[index] = tuple(
                    labels[item.lower()] for item in table_labels)
            except KeyError as exc:
                raise DrawTargetBundleError(
                    f"unresolved jump-table label in {name}: {exc}") from exc
    return FunctionAssembly(
        name, tuple(instructions), labels, jump_tables)


def parse_sdcc_functions(text: str) -> dict[str, FunctionAssembly]:
    lines = text.splitlines()
    markers = [
        index for index, line in enumerate(lines)
        if re.match(r"^; Function\s+", line)
    ]
    result: dict[str, FunctionAssembly] = {}
    for ordinal, marker in enumerate(markers):
        stop = markers[ordinal + 1] if ordinal + 1 < len(markers) else len(lines)
        entry = None
        for index in range(marker + 1, stop):
            match = re.match(r"\s*(_[A-Za-z0-9_]+):{1,2}\s*$", lines[index])
            if match:
                entry = (index, match.group(1))
                break
        if entry is None:
            raise DrawTargetBundleError(
                f"assembly function marker at line {marker + 1} has no entry")
        start, name = entry
        if name in result:
            raise DrawTargetBundleError(f"duplicate assembly function {name}")
        result[name] = _parse_function_block(lines, start, stop, name)
    return result


class AssemblyStackAnalyzer:
    def __init__(
            self, functions: Mapping[str, FunctionAssembly],
            external: Mapping[str, StackSummary],
            callbacks: Mapping[tuple[str, int], CallbackABI],
            ) -> None:
        self.functions = functions
        self.external = external
        self.callbacks = callbacks
        self.memo: dict[str, StackSummary] = {}
        self.active: set[str] = set()
        actual: set[tuple[str, int]] = set()
        for name, function in functions.items():
            ordinal = 0
            for instruction in function.instructions:
                if instruction.op == "call" and instruction.args == "___sdcc_call_iy":
                    actual.add((name, ordinal))
                    ordinal += 1
        unexpected = actual - set(callbacks)
        absent = set(callbacks) - actual
        if unexpected or absent:
            raise DrawTargetBundleError(
                "indirect callback inventory changed: "
                f"unexpected={sorted(unexpected)}, absent={sorted(absent)}")

    @staticmethod
    def _better(left: Peak, right: Peak) -> Peak:
        if right.depth > left.depth:
            return right
        if right.depth == left.depth and right.witness < left.witness:
            return right
        return left

    @staticmethod
    def _with_depth(state: MachineState, depth: int) -> MachineState:
        return MachineState(
            depth, state.ix_depth, state.ix_constant,
            state.iy_depth, state.iy_constant)

    def _plain_effect(
            self, function: str, instruction: Instruction,
            state: MachineState,
            ) -> MachineState:
        op, args = instruction.op, instruction.args
        depth = state.depth
        if op == "push":
            depth += 2
        elif op == "pop":
            depth -= 2
            if args == "ix":
                return MachineState(
                    depth, None, None, state.iy_depth, state.iy_constant)
            if args == "iy":
                return MachineState(
                    depth, state.ix_depth, state.ix_constant, None, None)
        elif op == "inc" and args == "sp":
            depth -= 1
        elif op == "dec" and args == "sp":
            depth += 1
        elif op == "ld":
            destination, comma, source = args.partition(",")
            if comma and destination in ("ix", "iy"):
                try:
                    constant = int(source.removeprefix("#"), 0)
                except ValueError:
                    constant = None
                if destination == "ix":
                    return MachineState(
                        depth, None, constant,
                        state.iy_depth, state.iy_constant)
                return MachineState(
                    depth, state.ix_depth, state.ix_constant,
                    None, constant)
            if destination == "sp":
                target = state.ix_depth if source == "ix" else (
                    state.iy_depth if source == "iy" else None)
                if target is None:
                    raise DrawTargetBundleError(
                        f"unsupported SP restore in {function}: {instruction.raw}")
                depth = target
        elif op == "add" and args in ("ix,sp", "iy,sp"):
            register = args[:2]
            constant = (state.ix_constant if register == "ix" else
                        state.iy_constant)
            if constant is None:
                raise DrawTargetBundleError(
                    f"non-affine frame setup in {function}: {instruction.raw}")
            target = depth - constant
            if register == "ix":
                return MachineState(
                    depth, target, None,
                    state.iy_depth, state.iy_constant)
            return MachineState(
                depth, state.ix_depth, state.ix_constant, target, None)
        elif re.search(r"\bsp\b", args):
            if not (
                    (op == "ex" and "(sp)" in args) or
                    (op == "add" and args.endswith(",sp"))):
                raise DrawTargetBundleError(
                    f"unsupported SP operation in {function}: {instruction.raw}")
        return self._with_depth(state, depth)

    def summary(self, name: str) -> StackSummary:
        if name not in self.external and name not in self.functions:
            external_matches = [
                candidate for candidate in self.external
                if candidate.lower() == name.lower()
            ]
            function_matches = [
                candidate for candidate in self.functions
                if candidate.lower() == name.lower()
            ]
            if len(external_matches) == 1:
                name = external_matches[0]
            elif len(function_matches) == 1:
                name = function_matches[0]
        if name in self.external:
            return self.external[name]
        cached = self.memo.get(name)
        if cached:
            return cached
        if name in self.active:
            raise DrawTargetBundleError(f"unproved call cycle at {name}")
        if name not in self.functions:
            raise DrawTargetBundleError(f"unresolved direct call {name}")
        self.active.add(name)
        try:
            summary = self._analyze(name)
            self.memo[name] = summary
            return summary
        finally:
            self.active.remove(name)

    def _analyze(self, name: str) -> StackSummary:
        function = self.functions[name]
        queue: deque[tuple[int, MachineState, tuple[str, ...]]] = deque([
            (0, MachineState(0), (f"{name}:entry",)),
        ])
        seen: set[tuple[int, MachineState]] = set()
        exits: set[int] = set()
        peak = Peak(0, (f"{name}:entry",))
        callback_peaks: dict[str, Peak] = {}
        indirect_ordinals: dict[int, int] = {}
        ordinal = 0
        for index, instruction in enumerate(function.instructions):
            if instruction.op == "call" and instruction.args == "___sdcc_call_iy":
                indirect_ordinals[index] = ordinal
                ordinal += 1
        while queue:
            index, state, witness = queue.popleft()
            key = (index, state)
            if key in seen:
                continue
            seen.add(key)
            if len(seen) > 30000 or state.depth < -32 or state.depth > 4096:
                raise DrawTargetBundleError(
                    f"unbounded/ambiguous stack in {name} at instruction {index}")
            instruction = function.instructions[index]
            location = f"{name}:asm:{instruction.source_line}:{instruction.raw}"
            peak = self._better(peak, Peak(state.depth, witness + (location,)))

            def enqueue(target: int, new_state: MachineState, suffix: str) -> None:
                if target < 0 or target >= len(function.instructions):
                    raise DrawTargetBundleError(
                        f"control flow escapes {name} at {instruction.source_line}")
                queue.append((
                    target, new_state,
                    (witness + (location + ":" + suffix,))[-80:],
                ))

            if instruction.op == "call":
                target = instruction.args
                if target == "___sdcc_call_iy":
                    abi = self.callbacks[(name, indirect_ordinals[index])]
                    event = Peak(
                        state.depth + 2,
                        witness + (location, abi.name),
                    )
                    callback_peaks[abi.name] = self._better(
                        callback_peaks.get(abi.name, Peak(-1, ())), event)
                    peak = self._better(peak, event)
                    enqueue(index + 1, self._with_depth(
                        state, state.depth - abi.stack_argument_bytes),
                        "callback-return")
                    continue
                if target == "___memcpy":
                    peak = self._better(peak, Peak(
                        state.depth + 2,
                        witness + (location, "___memcpy:entry"),
                    ))
                    enqueue(index + 1, self._with_depth(
                        state, state.depth - 2), "memcpy-return")
                    continue
                callee = self.summary(target)
                call_base = state.depth + 2
                peak = self._better(peak, Peak(
                    call_base + callee.maximum_depth_from_entry_sp,
                    witness + (location,) + callee.maximum_witness,
                ))
                for callback, child in callee.callback_entry_peaks.items():
                    event = Peak(
                        call_base + child.depth,
                        witness + (location,) + child.witness,
                    )
                    callback_peaks[callback] = self._better(
                        callback_peaks.get(callback, Peak(-1, ())), event)
                enqueue(index + 1, self._with_depth(
                    state, call_base + callee.return_delta_bytes),
                    "direct-return")
                continue
            if instruction.op in ("jp", "jr"):
                parts = [item.strip() for item in instruction.args.split(",", 1)]
                conditional = len(parts) == 2 and parts[0] in _CONDITIONS
                target_text = parts[1] if conditional else parts[0]
                if target_text == "(hl)":
                    targets = function.jump_tables.get(index)
                    if targets:
                        for target in targets:
                            enqueue(target, state, "jump-table")
                    elif instruction.op == "jp":
                        exits.add(state.depth)
                    else:
                        raise DrawTargetBundleError(
                            f"unresolved indirect JR in {name}")
                elif target_text in function.labels:
                    enqueue(function.labels[target_text], state, "branch")
                elif not conditional and any(
                        item.lower() == target_text.lower()
                        for item in tuple(self.functions) + tuple(self.external)):
                    callee = self.summary(target_text)
                    peak = self._better(peak, Peak(
                        state.depth + callee.maximum_depth_from_entry_sp,
                        witness + (location,) + callee.maximum_witness,
                    ))
                    for callback, child in callee.callback_entry_peaks.items():
                        event = Peak(state.depth + child.depth,
                                     witness + (location,) + child.witness)
                        callback_peaks[callback] = self._better(
                            callback_peaks.get(callback, Peak(-1, ())), event)
                    exits.add(state.depth + callee.return_delta_bytes)
                elif target_text.startswith("("):
                    raise DrawTargetBundleError(
                        f"unresolved indirect jump in {name}: {instruction.raw}")
                else:
                    raise DrawTargetBundleError(
                        f"unresolved branch in {name}: {instruction.raw}")
                if conditional:
                    enqueue(index + 1, state, "fallthrough")
                continue
            if instruction.op == "djnz":
                if instruction.args not in function.labels:
                    raise DrawTargetBundleError(
                        f"unresolved DJNZ in {name}: {instruction.raw}")
                enqueue(function.labels[instruction.args], state, "djnz-taken")
                enqueue(index + 1, state, "djnz-fallthrough")
                continue
            if instruction.op == "ret":
                condition = instruction.args.strip()
                if condition and condition not in _CONDITIONS:
                    raise DrawTargetBundleError(
                        f"unsupported RET in {name}: {instruction.raw}")
                exits.add(state.depth - 2)
                if condition:
                    enqueue(index + 1, state, "ret-not-taken")
                continue
            next_state = self._plain_effect(name, instruction, state)
            peak = self._better(peak, Peak(
                next_state.depth, witness + (location,)))
            if index + 1 >= len(function.instructions):
                raise DrawTargetBundleError(f"function {name} falls off body")
            enqueue(index + 1, next_state, "next")
        if len(exits) != 1:
            raise DrawTargetBundleError(
                f"{name} has inconsistent return deltas: {sorted(exits)}")
        return StackSummary(
            peak.depth, next(iter(exits)),
            dict(sorted(callback_peaks.items())), peak.witness[-80:], len(seen))


@dataclass(frozen=True)
class FastState:
    pc: int
    depth: int
    ix_depth: int | None
    ix_constant: int | None
    hl_depth: int | None
    hl_constant: int | None
    returns: tuple[tuple[int, int], ...]


def analyze_fast_batch_stack(
        assembly: str, find_summary: StackSummary,
        ) -> StackSummary:
    """Analyze the naked shared fast-batch assembly, including local calls."""
    lines = assembly.splitlines()
    try:
        start = next(index for index, line in enumerate(lines)
                     if line.strip() in (
                         "_PyZ80FT_BuildSpriteBatchFast:",
                         "_PyZ80FT_BuildSpriteBatchFast::"))
    except StopIteration as exc:
        raise DrawTargetBundleError("fast-batch assembly entry is missing") from exc
    stop = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].strip().startswith(".area"):
            stop = index
            break
    function = _parse_function_block(
        lines, start, stop, "_PyZ80FT_BuildSpriteBatchFast")
    if "_pyz80ft_buildspritebatchshared" not in function.labels:
        raise DrawTargetBundleError("fast-batch shared assembly label is missing")
    queue: deque[tuple[FastState, tuple[str, ...]]] = deque([
        (FastState(0, 0, None, None, None, None, ()),
         ("_PyZ80FT_BuildSpriteBatchFast:entry",)),
    ])
    seen: set[FastState] = set()
    exits: set[int] = set()
    peak = Peak(0, ("_PyZ80FT_BuildSpriteBatchFast:entry",))
    while queue:
        state, witness = queue.popleft()
        if state in seen:
            continue
        seen.add(state)
        if len(seen) > 50000 or state.depth < -32 or state.depth > 4096:
            raise DrawTargetBundleError("fast-batch local-call stack is unbounded")
        instruction = function.instructions[state.pc]
        location = (
            "_PyZ80FT_BuildSpriteBatchFast:asm:"
            f"{instruction.source_line}:{instruction.raw}")
        peak = AssemblyStackAnalyzer._better(
            peak, Peak(state.depth, witness + (location,)))

        def enqueue(
                pc: int, depth: int = state.depth,
                ix_depth: int | None = state.ix_depth,
                ix_constant: int | None = state.ix_constant,
                hl_depth: int | None = state.hl_depth,
                hl_constant: int | None = state.hl_constant,
                returns: tuple[tuple[int, int], ...] = state.returns,
                suffix: str = "next",
                ) -> None:
            if pc < 0 or pc >= len(function.instructions):
                raise DrawTargetBundleError("fast-batch control flow escaped")
            queue.append((
                FastState(pc, depth, ix_depth, ix_constant,
                          hl_depth, hl_constant, returns),
                (witness + (location + ":" + suffix,))[-100:],
            ))

        op, args = instruction.op, instruction.args
        if op == "push":
            enqueue(state.pc + 1, depth=state.depth + 2)
            peak = AssemblyStackAnalyzer._better(
                peak, Peak(state.depth + 2, witness + (location,)))
            continue
        if op == "pop":
            enqueue(
                state.pc + 1, depth=state.depth - 2,
                ix_depth=None if args == "ix" else state.ix_depth,
                hl_depth=None if args == "hl" else state.hl_depth,
                hl_constant=None if args == "hl" else state.hl_constant)
            continue
        if op == "ld":
            destination, comma, source = args.partition(",")
            if comma and destination == "ix":
                try:
                    constant = int(source.removeprefix("#"), 0)
                except ValueError:
                    constant = None
                enqueue(state.pc + 1, ix_depth=None, ix_constant=constant)
                continue
            if comma and destination == "hl":
                try:
                    constant = int(source.removeprefix("#"), 0)
                except ValueError:
                    constant = None
                enqueue(state.pc + 1, hl_depth=None, hl_constant=constant)
                continue
            if destination == "sp":
                if source == "ix" and state.ix_depth is not None:
                    new_depth = state.ix_depth
                elif source == "hl" and state.hl_depth is not None:
                    new_depth = state.hl_depth
                else:
                    raise DrawTargetBundleError(
                        f"unproved fast-batch SP write: {instruction.raw}")
                kept = tuple(
                    item for item in state.returns if item[1] <= new_depth)
                enqueue(state.pc + 1, depth=new_depth, returns=kept)
                continue
            if destination in ("h", "l") or destination == "hl":
                enqueue(state.pc + 1, hl_depth=None, hl_constant=None)
                continue
        if op == "add" and args == "ix,sp":
            if state.ix_constant is None:
                raise DrawTargetBundleError("fast-batch IX frame is non-affine")
            enqueue(
                state.pc + 1, ix_depth=state.depth - state.ix_constant,
                ix_constant=None)
            continue
        if op == "add" and args == "hl,sp":
            if state.hl_constant is None:
                raise DrawTargetBundleError("fast-batch HL allocation is non-affine")
            enqueue(
                state.pc + 1,
                hl_depth=state.depth - state.hl_constant,
                hl_constant=None)
            continue
        if op in ("jp", "jr"):
            parts = [item.strip() for item in args.split(",", 1)]
            conditional = len(parts) == 2 and parts[0] in _CONDITIONS
            target = parts[1] if conditional else parts[0]
            if target.startswith("("):
                raise DrawTargetBundleError(
                    f"unexpected indirect fast-batch jump: {instruction.raw}")
            if target not in function.labels:
                raise DrawTargetBundleError(
                    f"unresolved fast-batch branch {target}")
            enqueue(function.labels[target], suffix="branch")
            if conditional:
                enqueue(state.pc + 1, suffix="fallthrough")
            continue
        if op == "djnz":
            if args not in function.labels:
                raise DrawTargetBundleError(f"unresolved fast DJNZ {args}")
            enqueue(function.labels[args], suffix="djnz-taken")
            enqueue(state.pc + 1, suffix="djnz-fallthrough")
            continue
        if op == "call":
            if args == "_pyz80ft_findhqtemplate":
                base = state.depth + 2
                peak = AssemblyStackAnalyzer._better(peak, Peak(
                    base + find_summary.maximum_depth_from_entry_sp,
                    witness + (location,) + find_summary.maximum_witness,
                ))
                enqueue(
                    state.pc + 1,
                    depth=base + find_summary.return_delta_bytes,
                    suffix="hq-lookup-return")
                continue
            if args not in function.labels:
                raise DrawTargetBundleError(
                    f"unresolved fast-batch local call {args}")
            base = state.depth
            enqueue(
                function.labels[args], depth=base + 2,
                returns=state.returns + ((state.pc + 1, base + 2),),
                suffix="local-call")
            continue
        if op == "ret":
            condition = args.strip()
            if condition and condition not in _CONDITIONS:
                raise DrawTargetBundleError(
                    f"unsupported fast-batch RET {instruction.raw}")
            if state.returns:
                return_pc, _ = state.returns[-1]
                enqueue(
                    return_pc, depth=state.depth - 2,
                    returns=state.returns[:-1], suffix="local-return")
            else:
                exits.add(state.depth - 2)
            if condition:
                enqueue(state.pc + 1, suffix="ret-not-taken")
            continue
        if op == "inc" and args == "sp":
            enqueue(state.pc + 1, depth=state.depth - 1)
            continue
        if op == "dec" and args == "sp":
            enqueue(state.pc + 1, depth=state.depth + 1)
            continue
        if re.search(r"\bsp\b", args) and not (op == "ex" and "(sp)" in args):
            raise DrawTargetBundleError(
                f"unsupported fast-batch SP operation {instruction.raw}")
        # Any other write to HL invalidates the allocation value.  The stack
        # itself is unaffected; after the prologue no later instruction uses
        # HL to write SP.
        writes_hl = (
            (op in ("add", "adc", "sbc") and args.startswith("hl,")) or
            (op in ("inc", "dec") and args == "hl") or
            (op == "ex" and args in ("de,hl", "hl,de")))
        enqueue(
            state.pc + 1,
            hl_depth=None if writes_hl else state.hl_depth,
            hl_constant=None if writes_hl else state.hl_constant)
    if exits != {-2}:
        raise DrawTargetBundleError(
            f"fast-batch return delta changed: {sorted(exits)}")
    return StackSummary(
        peak.depth, -2, {}, peak.witness[-100:], len(seen))


def _summary_from_vm_report(report: Mapping[str, object]) -> StackSummary:
    try:
        row = report["functions"]["rtype_python_draw_vm_stream"]  # type: ignore[index]
        maximum = int(row["maximum_depth_from_function_entry_sp"])
        delta = int(row["return_delta_bytes"])
        callbacks = row["callback_entry_depths_from_function_entry_sp"]
    except (KeyError, TypeError, ValueError) as exc:
        raise DrawTargetBundleError("draw VM stack report schema changed") from exc
    if not isinstance(callbacks, dict):
        raise DrawTargetBundleError("draw VM callback stack rows are invalid")
    expected = {
        "emit_record", "load_object", "resolve_bank_key",
        "resolve_resource_type",
    }
    if set(callbacks) != expected or maximum <= 0 or delta != -6:
        raise DrawTargetBundleError("draw VM stream stack contract changed")
    return StackSummary(
        maximum, delta,
        {"vm." + name: Peak(int(value), ("_rtype_python_draw_vm_stream", name))
         for name, value in sorted(callbacks.items())},
        ("_rtype_python_draw_vm_stream:pinned-certificate",), 0)


def _summary_row(summary: StackSummary) -> dict[str, object]:
    return {
        "maximum_depth_from_function_entry_sp": (
            summary.maximum_depth_from_entry_sp),
        "return_delta_bytes": summary.return_delta_bytes,
        "callback_entry_depths_from_function_entry_sp": {
            name: peak.depth for name, peak in
            sorted(summary.callback_entry_peaks.items())
        },
        "explored_abstract_states": summary.explored_states,
        "maximum_witness": list(summary.maximum_witness),
    }


def _compile_and_link(
        root: Path, sdcc: Path, slices: Mapping[str, object],
        ) -> dict[str, object]:
    environment = os.environ.copy()
    environment["PATH"] = (
        str(sdcc.parent) + os.pathsep + environment.get("PATH", ""))
    with tempfile.TemporaryDirectory(prefix="pyz80-draw-target-bundle-") as temp:
        directory = Path(temp)
        copy_paths = (
            "Source/C/generated/rtype_python_render_order.c",
            "Source/C/generated/rtype_python_render_order.h",
            "Source/C/generated/rtype_python_draw_state.c",
            "Source/C/generated/rtype_python_draw_state.h",
            "Source/C/generated/rtype_python_draw_vm.c",
            "Source/C/generated/rtype_python_draw_vm.h",
            "Source/C/ft812/pyz80_draw_fast_chunker.c",
            "Source/C/ft812/pyz80_draw_fast_chunker.h",
            "Source/C/ft812/pyz80_ft812.h",
            "Source/C/generated/rtype_python_hq_templates.h",
        )
        for relative in copy_paths:
            source = root / relative
            (directory / source.name).write_bytes(source.read_bytes())
        ft_name = "ft812_fast_slice.c"
        hq_name = "hqt3_fast_slice.c"
        (directory / ft_name).write_text(
            str(slices["ft_source"]), encoding="utf-8", newline="\n")
        (directory / hq_name).write_text(
            str(slices["hq_source"]), encoding="utf-8", newline="\n")
        sources = (
            "rtype_python_render_order.c",
            "rtype_python_draw_state.c",
            "rtype_python_draw_vm.c",
            "pyz80_draw_fast_chunker.c",
            ft_name,
            hq_name,
        )
        compile_logs: dict[str, str] = {}
        for source in sources:
            completed = _run(
                [str(sdcc), *PINNED_ARGUMENTS, "-c", source],
                directory, environment)
            compile_logs[source] = completed.stdout
        rels = tuple(Path(source).with_suffix(".rel").name for source in sources)
        link = _run(
            [str(sdcc), *LINK_ARGUMENTS, *rels, "-o", "bundle.ihx"],
            directory, environment)
        map_bytes = (directory / "bundle.map").read_bytes()
        map_text = map_bytes.decode("latin1")
        ihx_bytes = (directory / "bundle.ihx").read_bytes()
        noi_bytes = (directory / "bundle.noi").read_bytes()
        areas = _area_map(map_text)
        if "_CODE" not in areas or "_DATA" not in areas:
            raise DrawTargetBundleError("linked map lacks _CODE/_DATA")
        direct, runtime = _linked_files(map_text)
        if tuple(direct) != EXPECTED_DIRECT_OBJECTS:
            raise DrawTargetBundleError(
                f"direct linked object inventory changed: {direct}")
        if tuple(sorted(runtime)) != tuple(sorted(EXPECTED_RUNTIME_OBJECTS)):
            raise DrawTargetBundleError(
                f"runtime linked object inventory changed: {runtime}")
        definitions = _map_definitions(map_text)
        resolved_public: dict[str, tuple[int, str]] = {}
        missing_public: list[str] = []
        for symbol in EXPECTED_PUBLIC_SYMBOLS:
            if symbol in definitions:
                resolved_public[symbol] = definitions[symbol]
                continue
            # ASxxxx's human-readable map column is 32 characters wide even
            # though the .rel symbol remains complete.  Accept exactly one
            # displayed prefix and cross-check full names below with sdnm.
            candidates = [
                value for name, value in definitions.items()
                if len(name) == 32 and symbol.startswith(name)
            ]
            if len(candidates) == 1:
                resolved_public[symbol] = candidates[0]
            else:
                missing_public.append(symbol)
        if missing_public:
            raise DrawTargetBundleError(
                f"linked map lacks expected public symbols: {missing_public}")
        sdnm = sdcc.parent / "sdnm.exe"
        if not sdnm.is_file():
            raise DrawTargetBundleError("pinned toolchain has no sdnm.exe")
        object_symbols: dict[str, object] = {}
        owners: dict[str, list[str]] = defaultdict(list)
        all_undefined: set[str] = set()
        all_defined: set[str] = set()
        for rel in rels:
            completed = _run([str(sdnm), rel], directory, environment)
            defined, undefined = _sdnm_symbols(completed.stdout)
            for symbol in defined:
                owners[symbol].append(rel)
            all_defined.update(defined)
            all_undefined.update(undefined)
            object_symbols[rel] = {
                "defined": sorted(defined),
                "undefined": sorted(undefined),
            }
        duplicates = {
            symbol: modules for symbol, modules in sorted(owners.items())
            if len(modules) > 1 and symbol != ".__.ABS."
        }
        runtime_defs = {
            "___sdcc_call_iy", "___memcpy", "_memcpy",
        }
        unresolved = sorted(
            all_undefined - all_defined - runtime_defs)
        if duplicates:
            raise DrawTargetBundleError(
                f"duplicate object definitions: {duplicates}")
        if unresolved:
            raise DrawTargetBundleError(
                f"unresolved direct object references: {unresolved}")
        truncated_owners: dict[str, set[str]] = defaultdict(set)
        for symbol in all_defined:
            truncated_owners[symbol[:32]].add(symbol)
        truncated_collisions = {
            prefix: sorted(names)
            for prefix, names in sorted(truncated_owners.items())
            if len(names) > 1
        }
        if truncated_collisions:
            raise DrawTargetBundleError(
                "32-character ASxxxx symbol-prefix collision: "
                f"{truncated_collisions}")

        assembly = {
            Path(source).stem: (directory / Path(source).with_suffix(".asm").name)
            .read_bytes()
            for source in sources
        }
        vm_stack = _read_json(
            root / "Build/rtype_python_draw_vm_stack_status.json")
        vm_summary = _summary_from_vm_report(vm_stack)
        functions: dict[str, FunctionAssembly] = {}
        for stem in (
                "rtype_python_render_order",
                "rtype_python_draw_state",
                "pyz80_draw_fast_chunker",
                "ft812_fast_slice"):
            parsed = parse_sdcc_functions(assembly[stem].decode("latin1"))
            overlap = set(functions) & set(parsed)
            if overlap:
                raise DrawTargetBundleError(
                    f"assembly function definitions conflict: {sorted(overlap)}")
            functions.update(parsed)
        callbacks = {
            ("_PyZ80DrawFastChunk_FlushBuffered", 0):
                CallbackABI("chunk_submit", 4),
            ("_PyZ80DrawFastChunk_SubmitFT812", 0):
                CallbackABI("target_provider", 4),
        }
        preliminary_external = {
            "_rtype_python_draw_vm_stream": vm_summary,
        }
        preliminary = AssemblyStackAnalyzer(
            functions, preliminary_external, callbacks)
        find_summary = preliminary.summary("_PyZ80FT_FindHQTemplate")
        fast_summary = analyze_fast_batch_stack(
            assembly["ft812_fast_slice"].decode("latin1"),
            find_summary)
        analyzer = AssemblyStackAnalyzer(
            functions,
            {
                "_rtype_python_draw_vm_stream": vm_summary,
                "_PyZ80FT_BuildSpriteBatchFast": fast_summary,
            },
            callbacks)
        named_summaries = {
            "render_order_slot_at": analyzer.summary(
                "_rtype_python_render_order_slot_at"),
            "draw_state_load_object": analyzer.summary(
                "_rtype_python_draw_state_load_object"),
            "fast_chunk_emit": analyzer.summary(
                "_PyZ80DrawFastChunk_Emit"),
            "fast_chunk_submit_ft812": analyzer.summary(
                "_PyZ80DrawFastChunk_SubmitFT812"),
            "fast_batch": fast_summary,
            "fast_chunk_run": analyzer.summary(
                "_PyZ80DrawFastChunk_Run"),
        }

        code_origin, code_bytes = areas["_CODE"]
        data_origin, data_bytes = areas["_DATA"]
        code_end = code_origin + code_bytes
        data_end = data_origin + data_bytes
        bank_size = 0x4000
        code_banks = math.ceil(code_bytes / bank_size)
        object_records = {}
        for rel in rels:
            data = (directory / rel).read_bytes()
            object_records[rel] = {
                "bytes": len(data), "sha256": _sha256(data),
                **object_symbols[rel],  # type: ignore[arg-type]
            }
        return {
            "compile_logs": compile_logs,
            "link_stdout": link.stdout,
            "link_map": {
                "bytes": len(map_bytes), "sha256": _sha256(map_bytes),
            },
            "ihx": {"bytes": len(ihx_bytes), "sha256": _sha256(ihx_bytes)},
            "noi": {"bytes": len(noi_bytes), "sha256": _sha256(noi_bytes)},
            "objects": object_records,
            "direct_objects": direct,
            "runtime_objects": runtime,
            "defined_symbol_count": len(definitions),
            "public_symbols": {
                symbol: {
                    "address_hex": f"0x{resolved_public[symbol][0]:04X}",
                    "module": resolved_public[symbol][1],
                }
                for symbol in EXPECTED_PUBLIC_SYMBOLS
            },
            "code": {
                "origin_hex": f"0x{code_origin:04X}",
                "end_exclusive_hex": f"0x{code_end:04X}",
                "bytes": code_bytes,
                "bank_bytes": bank_size,
                "banks_required": code_banks,
                "fits_one_bank": code_bytes <= bank_size,
                "single_bank_overflow_bytes": max(0, code_bytes - bank_size),
            },
            "data": {
                "origin_hex": f"0x{data_origin:04X}",
                "end_exclusive_hex": f"0x{data_end:04X}",
                "bytes": data_bytes,
                "expected_private_fast_cache_bytes": 1280,
            },
            "placement": {
                "code_data_overlap": (
                    code_origin < data_end and data_origin < code_end),
                "cross_bank_link_adapter_proved": False,
            },
            "stack": {
                "vm_report": {
                    "path": "Build/rtype_python_draw_vm_stack_status.json",
                    "sha256": _sha256((
                        root / "Build/rtype_python_draw_vm_stack_status.json"
                    ).read_bytes()),
                    "status": vm_stack.get("status"),
                },
                "known_function_bounds": {
                    name: _summary_row(summary)
                    for name, summary in sorted(named_summaries.items())
                },
            },
        }


def _compose_stack(result: Mapping[str, object], stack_budget: int) -> dict[str, object]:
    try:
        rows = result["stack"]["known_function_bounds"]  # type: ignore[index]
        run = rows["fast_chunk_run"]
        emit = rows["fast_chunk_emit"]
        loader = rows["draw_state_load_object"]
        submit = rows["fast_chunk_submit_ft812"]
        callbacks = run["callback_entry_depths_from_function_entry_sp"]
        emit_callbacks = emit["callback_entry_depths_from_function_entry_sp"]
        submit_callbacks = submit["callback_entry_depths_from_function_entry_sp"]
        run_internal = int(run["maximum_depth_from_function_entry_sp"])
        emit_internal = int(emit["maximum_depth_from_function_entry_sp"])
        loader_internal = int(loader["maximum_depth_from_function_entry_sp"])
        submit_internal = int(submit["maximum_depth_from_function_entry_sp"])
        vm_emit = int(callbacks["vm.emit_record"])
        vm_loader = int(callbacks["vm.load_object"])
        vm_bank = int(callbacks["vm.resolve_bank_key"])
        vm_resource = int(callbacks["vm.resolve_resource_type"])
        chunk_submit = int(emit_callbacks["chunk_submit"])
        target_provider = int(submit_callbacks["target_provider"])
    except (KeyError, TypeError, ValueError) as exc:
        raise DrawTargetBundleError("cannot compose known stack paths") from exc
    emit_path = vm_emit + emit_internal
    loader_candidate_path = vm_loader + loader_internal
    submit_candidate_entry = vm_emit + chunk_submit
    submit_candidate_path = submit_candidate_entry + submit_internal
    provider_candidate_entry = submit_candidate_entry + target_provider
    known_candidate = max(
        run_internal, emit_path, loader_candidate_path, submit_candidate_path)
    return {
        "stack_unit": "bytes",
        "root": "PyZ80DrawFastChunk_Run",
        "root_internal_through_vm_without_external_callback_bodies_bytes": (
            run_internal),
        "fixed_emitter_body_composed_bytes": emit_path,
        "sidecar_loader_candidate_composed_bytes": loader_candidate_path,
        "ft812_submit_candidate_composed_bytes": submit_candidate_path,
        "target_provider_entry_candidate_bytes": provider_candidate_entry,
        "resolve_bank_key_entry_bytes": vm_bank,
        "resolve_resource_type_entry_bytes": vm_resource,
        "maximum_known_candidate_bytes": known_candidate,
        "target_stack_budget_bytes": stack_budget,
        "known_candidate_headroom_bytes": stack_budget - known_candidate,
        "complete_bound_bytes": None,
        "complete_bound_certified": False,
        "binding_semantics": {
            "emitter": (
                "fixed by PyZ80DrawFastChunk_Run to PyZ80DrawFastChunk_Emit"),
            "loader": (
                "rtype_python_draw_state_load_object is linked and measured "
                "but installation into input.load_object is not proved"),
            "submit": (
                "PyZ80DrawFastChunk_SubmitFT812 is linked and measured but "
                "installation into state.submit is not proved"),
        },
        "missing_bounds": [
            {
                "code": "PZTB_STACK_RESOURCE_RESOLVER",
                "boundary": "rtype_python_draw_vm_resource_type_resolver",
                "entry_bytes_from_root": vm_resource,
            },
            {
                "code": "PZTB_STACK_BANK_RESOLVER",
                "boundary": "rtype_python_draw_vm_bank_key_resolver",
                "entry_bytes_from_root": vm_bank,
            },
            {
                "code": "PZTB_STACK_OBJECT_PROVIDER_BINDING",
                "boundary": "rtype_python_draw_vm_object_loader",
                "candidate": "rtype_python_draw_state_load_object",
                "candidate_composed_bytes": loader_candidate_path,
            },
            {
                "code": "PZTB_STACK_CHUNK_SUBMIT_BINDING",
                "boundary": "PyZ80DrawFastChunkSubmit",
                "candidate": "PyZ80DrawFastChunk_SubmitFT812",
                "candidate_composed_bytes": submit_candidate_path,
            },
            {
                "code": "PZTB_STACK_TARGET_PROVIDER",
                "boundary": "PyZ80DrawFastTargetProvider",
                "entry_bytes_from_root_if_candidate_submit_is_bound": (
                    provider_candidate_entry),
            },
            {
                "code": "PZTB_STACK_INTERRUPT_COMPOSITION",
                "boundary": "ISR/preemption high-water",
                "entry_bytes_from_root": None,
            },
        ],
    }


def probe(project_root: Path | str) -> dict[str, object]:
    root = Path(project_root).resolve()
    model = build_draw_state_model(root)
    state_artifacts = emit_draw_state_backend(root)
    vm_artifacts = emit_draw_vm_backend(model.plan)
    order_artifacts = emit_render_order_backend(root)
    generated = {
        "render_order": _exact_generated(
            root, order_artifacts, "Source/C/generated"),
        "draw_state": _exact_generated(
            root, state_artifacts, "Source/C/generated"),
        "draw_vm": _exact_generated(
            root, vm_artifacts, "Source/C/generated"),
    }
    if not (
        model.source_sha256 == model.plan.source_sha256 and
        model.draw_vm_source_sha256 == generated["draw_vm"]["source"]["sha256"] and
        model.render_order_source_sha256 ==
            generated["render_order"]["source"]["sha256"]
    ):
        raise DrawTargetBundleError("generated backend active-source bindings disagree")
    launcher = (root / "run_python.cmd").read_bytes()
    if b"-m rtype_port.app" not in launcher:
        raise DrawTargetBundleError(
            "run_python.cmd no longer launches rtype_port.app")
    if _sha256(launcher) != model.launcher_sha256:
        raise DrawTargetBundleError("draw-state model launcher hash is stale")

    inputs = {relative: _file_record(root, relative) for relative in CORE_FILES}
    asset_manifest = _read_json(root / "Build/rtype_python_assets.json")
    try:
        bootstrap = asset_manifest["artifacts"][-1]  # type: ignore[index]
        tables = bootstrap["templates"]["c_tables"]  # type: ignore[index]
        header_binding = tables["header"]
        source_binding = tables["source"]
    except (KeyError, IndexError, TypeError) as exc:
        raise DrawTargetBundleError("asset manifest lacks HQT3 C bindings") from exc
    for binding, relative in (
            (header_binding, "Source/C/generated/rtype_python_hq_templates.h"),
            (source_binding, "Source/C/generated/rtype_python_hq_templates.c")):
        record = inputs[relative]
        if (
            binding.get("path") != relative or
            int(binding.get("size", -1)) != record["bytes"] or
            binding.get("sha256") != record["sha256"]
        ):
            raise DrawTargetBundleError(
                f"asset manifest HQT3 binding is stale: {relative}")

    frame_budget_path = root / "Build/rtype_python_frame_budget_status.json"
    frame_budget = _read_json(frame_budget_path)
    try:
        frame_missing_contracts = frame_budget["blockers"][  # type: ignore[index]
            "missing_fragment_contracts"]
    except (KeyError, TypeError) as exc:
        raise DrawTargetBundleError(
            "frame budget status lacks v4 publication blockers") from exc
    atomic_blocker = (
        "complete prepublication preflight and atomic frame commit")
    if (
        frame_budget.get("format") !=
            "pyz80-ft812-frame-fragment-budget-status-v2" or
        frame_budget.get("contract_format_required") !=
            "pyz80-ft812-frame-fragment-budget-v4" or
        frame_budget.get("status") !=
            "BLOCKED_MISSING_TRANSLATOR_CERTIFICATE" or
        frame_budget.get("full_frame_proved") is not False or
        not isinstance(frame_missing_contracts, list) or
        atomic_blocker not in frame_missing_contracts
    ):
        raise DrawTargetBundleError(
            "frame budget status no longer proves the expected v4 fail-closed state")
    chunker_text = (
        root / "Source/C/ft812/pyz80_draw_fast_chunker.c"
    ).read_text(encoding="utf-8")
    chunker_header = (
        root / "Source/C/ft812/pyz80_draw_fast_chunker.h"
    ).read_text(encoding="utf-8")
    prefix_publication_tokens = (
        "state->published_records = (uint16_t)(",
        "state->published_records + state->count",
        "only result.published_records may already be visible as complete batches",
    )
    if (
        prefix_publication_tokens[0] not in chunker_text or
        prefix_publication_tokens[1] not in chunker_text or
        prefix_publication_tokens[2] not in chunker_header
    ):
        raise DrawTargetBundleError(
            "chunk-prefix publication behavior changed without bundle audit")

    slices = build_dependency_slices(root)
    compiler_manifest_path = root / "Source/Tools/rtype_python_compiler.json"
    compiler_manifest = CompilerManifest.load(compiler_manifest_path)
    sdcc = locate_sdcc(compiler_manifest.target).resolve()
    compiler_bytes = sdcc.read_bytes()
    if compiler_manifest.target.toolchain_sha256.lower() != _sha256(compiler_bytes):
        raise DrawTargetBundleError("located SDCC does not match pinned manifest hash")
    linked = _compile_and_link(root, sdcc, slices)
    stack_budget = int(compiler_manifest.target.stack_budget)
    stack = _compose_stack(linked, stack_budget)
    code = linked["code"]
    data = linked["data"]
    placement = linked["placement"]
    checks = {
        "active_launcher_is_rtype_port_app": True,
        "active_python_backends_regenerated_byte_exact": True,
        "active_source_and_semantic_hashes_cross_bound": True,
        "hqt3_asset_manifest_binding_exact": True,
        "ft812_dependency_slice_exact_source_spans": True,
        "hqt3_dependency_slice_only_reachable_tables": True,
        "all_bundle_objects_compiled_together_with_pinned_sdcc": True,
        "actual_link_completed": True,
        "direct_symbol_references_resolved": True,
        "duplicate_global_symbols_absent": True,
        "headers_and_cross_object_abis_compile_together": True,
        "linked_code_and_data_measured_from_map": True,
        "known_stack_paths_assembly_proved": True,
        "frame_budget_v4_status_hash_bound": True,
        "complete_lookup_count_append_preflight_before_first_ready": False,
        "atomic_complete_frame_commit": False,
        "complete_external_callback_stack_bound": False,
        "single_16k_code_bank_fit": bool(code["fits_one_bank"]),
        "code_data_ranges_do_not_overlap": not bool(
            placement["code_data_overlap"]),
        "cross_bank_link_adapter_proved": False,
        "live_provider_and_queue_binding_proved": False,
    }
    blockers = [
        {
            "code": "PZTB001",
            "detail": (
                f"linked CODE is {code['bytes']} bytes and requires "
                f"{code['banks_required']} 16K banks; cross-bank calls and "
                "placement are not implemented/certified"),
        },
        {
            "code": "PZTB002",
            "detail": (
                "the target link at CODE=0x8000 and DATA=0xC000 overlaps; "
                "the private 1280-byte page-F0 cache needs explicit mapping"),
        } if placement["code_data_overlap"] else {
            "code": "PZTB002",
            "detail": (
                "the private 1280-byte page-F0 cache has no live MMU/mapping "
                "certificate"),
        },
        {
            "code": "PZTB003",
            "detail": (
                "VM resource-type and bank-key resolver implementations and "
                "stack bounds are external"),
        },
        {
            "code": "PZTB004",
            "detail": (
                "sidecar loader and FT812 submit candidates are linked, but "
                "their function-pointer installation is not proved"),
        },
        {
            "code": "PZTB005",
            "detail": (
                "target provider, queue rotation, page ownership and remaining "
                "full-frame DL budget bounds are external"),
        },
        {
            "code": "PZTB006",
            "detail": (
                "ISR/preemption stack composition and complete frame tstates "
                "are not certified"),
        },
        {
            "code": "PZTB007",
            "detail": (
                f"{len(model.mutation_sites)} source-derived draw-state "
                "mutation sites are generated but not live-hooked"),
        },
        {
            "code": "PZTB008",
            "detail": (
                "frame-budget v4 requires complete record-count, template-"
                "lookup and CMD_APPEND budget preflight before the first queue "
                "READY plus one atomic whole-frame commit; the current bridge "
                "publishes successful chunk prefixes before VM completion"),
        },
    ]
    return {
        "format": FORMAT,
        "status": STATUS,
        "active_source": {
            "launcher": "run_python.cmd",
            "entrypoint": "rtype_port.app",
            "launcher_sha256": model.launcher_sha256,
            "enemy_module": model.plan.source_path,
            "enemy_module_sha256": model.source_sha256,
            "draw_plan_semantic_sha256": model.plan.semantic_sha256,
            "draw_state_semantic_sha256": model.semantic_sha256,
        },
        "input": {
            "files": inputs,
            "generated": generated,
        },
        "dependency_slice": slices["report"],
        "frame_publication_contract": {
            "status_path": "Build/rtype_python_frame_budget_status.json",
            "status_sha256": _sha256(frame_budget_path.read_bytes()),
            "required_contract_format": (
                "pyz80-ft812-frame-fragment-budget-v4"),
            "budget_status": frame_budget.get("status"),
            "full_frame_proved": False,
            "required": {
                "complete_record_count_preflight": True,
                "complete_template_lookup_preflight": True,
                "complete_append_budget_preflight": True,
                "no_queue_fragment_ready_before_preflight": True,
                "atomic_complete_frame_commit": True,
            },
            "current_bridge": {
                "successful_chunk_prefixes_may_publish_before_vm_completion": True,
                "compatible_with_v4_atomic_whole_frame_commit": False,
            },
        },
        "compiler": {
            "path": sdcc.as_posix(),
            "bytes": len(compiler_bytes),
            "sha256": _sha256(compiler_bytes),
            "manifest_path": "Source/Tools/rtype_python_compiler.json",
            "manifest_sha256": _sha256(compiler_manifest_path.read_bytes()),
            "compile_arguments": list(PINNED_ARGUMENTS),
            "link_arguments": list(LINK_ARGUMENTS),
        },
        "link": {
            key: value for key, value in linked.items()
            if key not in ("compile_logs", "link_stdout", "stack")
        },
        "stack": {
            **stack,
            "evidence": linked["stack"],
            "analysis_method": (
                "pinned-SDCC assembly CFG abstract interpretation; VM "
                "recursion imported only from its exact hash-bound certificate"),
            "unknown_call_policy": "fail",
            "unsupported_sp_write_policy": "fail",
        },
        "checks": checks,
        "live": False,
        "live_blockers": blockers,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", type=Path,
        default=Path("Build/rtype_python_draw_target_bundle_status.json"))
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    output = arguments.output
    if not output.is_absolute():
        output = root / output
    try:
        result = probe(root)
        _atomic_json(output, result)
    except (DrawTargetBundleError, OSError, ValueError) as exc:
        print(f"FAIL: {exc}")
        return 1
    print(
        "Draw target bundle: linked CODE="
        f"{result['link']['code']['bytes']} bytes, DATA="
        f"{result['link']['data']['bytes']} bytes, known stack<="
        f"{result['stack']['maximum_known_candidate_bytes']} bytes; "
        "live remains blocked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
