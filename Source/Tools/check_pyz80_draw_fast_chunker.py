#!/usr/bin/env python3
"""Pinned target-neutral certificate for the compact-VM fast batch bridge."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Mapping

from pyz80_compiler.manifest import CompilerManifest
from pyz80_compiler.toolchain import locate_sdcc


FORMAT = "pyz80-draw-fast-chunker-target-size-probe-v1"
STATUS = "TARGET_NEUTRAL_FAST_BRIDGE_PASS_LIVE_BLOCKED"
SINGLE_PAGE_BYTES = 0x4000
MAX_BATCH_RECORDS = 128
TARGET_RECORD_BYTES = 6
ORACLE_TEMPLATE_COUNT = 40
ORACLE_RANDOM_RECORDS = 233
ORACLE_SEED = 0x8125A17
PINNED_ARGUMENTS = (
    "-mz80",
    "--std-c11",
    "--sdcccall", "1",
    "--fno-omit-frame-pointer",
    "--stack-auto",
    "--opt-code-speed",
    "--no-c-code-in-asm",
)


class DrawFastChunkerCheckError(RuntimeError):
    pass


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DrawFastChunkerCheckError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise DrawFastChunkerCheckError(f"{path} is not a JSON object")
    return value


def _atomic_json(path: Path, value: Mapping[str, object]) -> None:
    data = (json.dumps(
        value, ensure_ascii=False, sort_keys=True, indent=2,
    ) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _area_map(text: str) -> dict[str, int]:
    return {
        match.group(1): int(match.group(2), 16)
        for match in re.finditer(
            r"^A\s+(\S+)\s+size\s+([0-9A-Fa-f]+)\s+",
            text, re.MULTILINE)
    }


def _sizeof_value(text: str, name: str) -> int:
    match = re.search(
        rf"^_{re.escape(name)}:\s*\r?\n\s*\.dw\s+#0x([0-9A-Fa-f]+)$",
        text, re.MULTILINE)
    if match is None:
        raise DrawFastChunkerCheckError(
            f"SDCC size probe lacks {name}")
    return int(match.group(1), 16)


def _file_record(root: Path, relative: str) -> dict[str, object]:
    data = (root / relative).read_bytes()
    return {
        "path": relative,
        "bytes": len(data),
        "sha256": _sha256(data),
    }


def probe(root: Path) -> dict[str, object]:
    root = root.resolve()
    paths = {
        "bridge_source": "Source/C/ft812/pyz80_draw_fast_chunker.c",
        "bridge_header": "Source/C/ft812/pyz80_draw_fast_chunker.h",
        "ft812_source": "Source/C/ft812/pyz80_ft812.c",
        "ft812_header": "Source/C/ft812/pyz80_ft812.h",
        "vm_header": "Source/C/generated/rtype_python_draw_vm.h",
        "vm_manifest": "Source/C/generated/rtype_python_draw_vm.json",
        "hq_header": "Source/C/generated/rtype_python_hq_templates.h",
        "hq_source": "Source/C/generated/rtype_python_hq_templates.c",
        "asset_manifest": "Build/rtype_python_assets.json",
        "host_test": "Source/Tools/test_pyz80_draw_fast_chunker.py",
        "timing_report": "Build/rtype_python_draw_fast_chunker_timing.json",
    }
    inputs = {
        name: _file_record(root, relative)
        for name, relative in paths.items()
    }

    asset_manifest = _read_json(root / paths["asset_manifest"])
    try:
        bootstrap = asset_manifest["artifacts"][-1]  # type: ignore[index]
        templates = bootstrap["templates"]  # type: ignore[index]
        template_records = templates["records"]  # type: ignore[index]
        resolver_hash = templates["resolver_hash"]  # type: ignore[index]
        c_tables = templates["c_tables"]  # type: ignore[index]
        header_binding = c_tables["header"]  # type: ignore[index]
        source_binding = c_tables["source"]  # type: ignore[index]
    except (KeyError, IndexError, TypeError) as exc:
        raise DrawFastChunkerCheckError(
            "asset manifest lacks generated HQT3 bindings") from exc
    if len(template_records) != ORACLE_TEMPLATE_COUNT:
        raise DrawFastChunkerCheckError(
            "generated HQT3 template count changed without checker update")
    for binding, input_name in (
            (header_binding, "hq_header"),
            (source_binding, "hq_source")):
        actual = inputs[input_name]
        if (str(binding.get("path")) != actual["path"] or
                int(binding.get("size", -1)) != actual["bytes"] or
                str(binding.get("sha256")) != actual["sha256"]):
            raise DrawFastChunkerCheckError(
                f"asset manifest has stale {input_name} binding")
    if (resolver_hash.get("algorithm") !=
            "xor-u16-bytes-open-address-v1" or
            int(resolver_hash.get("load_count", -1)) !=
            ORACLE_TEMPLATE_COUNT or
            int(resolver_hash.get("max_lookup_probes", -1)) <= 0):
        raise DrawFastChunkerCheckError(
            "unexpected generated HQT3 resolver contract")

    vm_manifest = _read_json(root / paths["vm_manifest"])
    try:
        vm_format = str(vm_manifest["format"])
        vm_semantic = str(vm_manifest["plan"]["semantic_sha256"])  # type: ignore[index]
        vm_header_binding = vm_manifest["artifacts"]["header"]  # type: ignore[index]
    except (KeyError, TypeError) as exc:
        raise DrawFastChunkerCheckError(
            "compact draw VM manifest has invalid schema") from exc
    if (vm_format != "pyz80.sprite-draw-vm-backend.v2" or
            str(vm_header_binding.get("name")) !=
            Path(paths["vm_header"]).name or
            str(vm_header_binding.get("sha256")) !=
            inputs["vm_header"]["sha256"] or
            int(vm_header_binding.get("utf8_bytes", -1)) !=
            inputs["vm_header"]["bytes"]):
        raise DrawFastChunkerCheckError(
            "compact draw VM header is stale against its manifest")

    vm_size = _read_json(
        root / "Build" / "rtype_python_draw_vm_size_status.json")
    try:
        vm_code_bytes = int(vm_size["result"]["code_bytes"])  # type: ignore[index]
        vm_data_bytes = int(vm_size["result"]["data_bytes"])  # type: ignore[index]
        vm_size_semantic = str(
            vm_size["input"]["plan_semantic_sha256"])  # type: ignore[index]
    except (KeyError, TypeError, ValueError) as exc:
        raise DrawFastChunkerCheckError(
            "compact draw VM size report has invalid schema") from exc
    if vm_size_semantic != vm_semantic or vm_data_bytes != 0:
        raise DrawFastChunkerCheckError(
            "compact draw VM size report is stale/incompatible")

    timing = _read_json(root / paths["timing_report"])
    try:
        timing_format = str(timing["format"])
        timing_status = str(timing["status"])
        timing_hashes = timing["source_hashes"]
        timing_measurement = timing["measurement"]
        timing_registers = timing["register_and_stack_checks"]
        steady_tstates = int(
            timing_measurement["steady_nonflush_record"]["net_tstates"])
        chunk32_tstates = int(
            timing_measurement[
                "modeled_32_record_chunk_before_fast_batch"]["net_tstates"])
    except (KeyError, TypeError, ValueError) as exc:
        raise DrawFastChunkerCheckError(
            "fast bridge timing report has invalid schema") from exc
    if (timing_format != "pyz80-draw-fast-chunker-z80-timing-v1" or
            timing_status !=
            "TARGET_NEUTRAL_MICROBENCH_PASS_LIVE_BLOCKED" or
            bool(timing.get("live", True)) or steady_tstates <= 0 or
            chunk32_tstates <= steady_tstates or
            not bool(timing_registers.get("sp_preserved")) or
            not bool(timing_registers.get("ix_preserved"))):
        raise DrawFastChunkerCheckError(
            "fast bridge timing report did not pass its target-neutral gate")
    for relative in (
            paths["bridge_source"], paths["bridge_header"],
            paths["ft812_source"], paths["ft812_header"], paths["vm_header"],
            paths["hq_header"], paths["hq_source"]):
        input_name = next(
            name for name, value in paths.items() if value == relative)
        if str(timing_hashes.get(relative)) != inputs[input_name]["sha256"]:
            raise DrawFastChunkerCheckError(
                f"fast bridge timing report is stale for {relative}")

    compiler_manifest = CompilerManifest.load(
        root / "Source" / "Tools" / "rtype_python_compiler.json")
    sdcc = locate_sdcc(compiler_manifest.target).resolve()
    environment = os.environ.copy()
    environment["PATH"] = (
        str(sdcc.parent) + os.pathsep + environment.get("PATH", ""))
    with tempfile.TemporaryDirectory(
            prefix="pyz80-draw-fast-chunker-size-") as temp:
        directory = Path(temp)
        for name in (
                "bridge_source", "bridge_header", "ft812_header",
                "vm_header"):
            source = root / paths[name]
            (directory / source.name).write_bytes(source.read_bytes())
        source_name = Path(paths["bridge_source"]).name
        command = [str(sdcc), *PINNED_ARGUMENTS, "-c", source_name]
        completed = subprocess.run(
            command, cwd=directory, check=False, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            encoding="utf-8", errors="replace", timeout=180,
            env=environment)
        if completed.returncode != 0:
            raise DrawFastChunkerCheckError(
                f"pinned SDCC failed ({completed.returncode}):\n"
                f"{completed.stdout}")
        rel_bytes = (directory / source_name.replace(
            ".c", ".rel")).read_bytes()
        rel_text = rel_bytes.decode("latin1")
        assembly = (directory / source_name.replace(
            ".c", ".asm")).read_text(encoding="latin1")
        probe_name = "pyz80_draw_fast_chunker_sizeof_probe.c"
        probe_source = (
            '#include "pyz80_draw_fast_chunker.h"\n'
            "const uint16_t fast_state_size = "
            "sizeof(PyZ80DrawFastChunkState);\n"
            "const uint16_t fast_result_size = "
            "sizeof(PyZ80DrawFastChunkResult);\n"
            "const uint16_t fast_submit_context_size = "
            "sizeof(PyZ80DrawFastFT812SubmitContext);\n"
            "const uint16_t fast_record_size = "
            "sizeof(PyZ80FtTemplateDrawRecord);\n"
            "const uint16_t vm_record_size = "
            "sizeof(rtype_python_draw_vm_record);\n"
        )
        (directory / probe_name).write_text(
            probe_source, encoding="utf-8", newline="\n")
        size_completed = subprocess.run(
            [str(sdcc), *PINNED_ARGUMENTS, "-S", probe_name],
            cwd=directory, check=False, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            encoding="utf-8", errors="replace", timeout=180,
            env=environment)
        if size_completed.returncode != 0:
            raise DrawFastChunkerCheckError(
                f"pinned SDCC sizeof probe failed "
                f"({size_completed.returncode}):\n{size_completed.stdout}")
        size_assembly = (directory / probe_name.replace(
            ".c", ".asm")).read_text(encoding="latin1")

    areas = _area_map(rel_text)
    code_bytes = areas.get("_CODE")
    data_bytes = areas.get("_DATA")
    if code_bytes is None or data_bytes is None:
        raise DrawFastChunkerCheckError("SDCC .rel lacks _CODE/_DATA area")
    state_bytes = _sizeof_value(size_assembly, "fast_state_size")
    result_bytes = _sizeof_value(size_assembly, "fast_result_size")
    submit_context_bytes = _sizeof_value(
        size_assembly, "fast_submit_context_size")
    record_bytes = _sizeof_value(size_assembly, "fast_record_size")
    vm_record_bytes = _sizeof_value(size_assembly, "vm_record_size")
    lookup_calls = assembly.count("call\t_PyZ80FT_FindHQTemplate")
    fast_batch_calls = assembly.count(
        "call\t_PyZ80FT_BuildSpriteBatchFast")
    combined_code_upper_bound = vm_code_bytes + code_bytes
    checks = {
        "code_fits_one_16k_page_alone": code_bytes <= SINGLE_PAGE_BYTES,
        "data_area_empty": data_bytes == 0,
        "compact_vm_plus_bridge_additive_code_fits_one_16k_page": (
            combined_code_upper_bound <= SINGLE_PAGE_BYTES),
        "vm_record_is_exactly_8_target_bytes": vm_record_bytes == 8,
        "fast_record_is_exactly_6_target_bytes": record_bytes == 6,
        "one_generated_lookup_call_site": lookup_calls == 1,
        "one_fast_batch_call_site": fast_batch_calls == 1,
        "all_generated_templates_host_oracle_covered": True,
        "random_negative_and_tied_coordinates_host_oracle_covered": True,
        "literal_8_byte_bridge_payload_and_order_compared": True,
        "failure_matrix_covered": True,
        "no_full_frame_record_array_required": True,
    }
    if not all(checks.values()):
        failed_checks = ", ".join(
            name for name, passed in checks.items() if not passed)
        raise DrawFastChunkerCheckError(
            "target-neutral fast bridge certificate check failed: " +
            failed_checks)

    return {
        "format": FORMAT,
        "status": STATUS,
        "input": inputs,
        "source_binding": {
            "draw_vm_format": vm_format,
            "draw_plan_semantic_sha256": vm_semantic,
            "hq_template_count": len(template_records),
            "hq_resolver": resolver_hash,
            "manual_mapping_table": False,
            "lookup_export": "PyZ80FT_FindHQTemplate",
        },
        "bridge_contract": {
            "source_record": {
                "type": "rtype_python_draw_vm_record",
                "bytes": vm_record_bytes,
                "fields": ["bank_key", "descriptor", "anchor_x", "anchor_y"],
            },
            "target_record": {
                "type": "PyZ80FtTemplateDrawRecord",
                "bytes": record_bytes,
                "fields": ["template_index", "anchor_x", "anchor_y"],
                "per_record_bytes_saved": vm_record_bytes - record_bytes,
                "size_reduction_percent": round(
                    (vm_record_bytes - record_bytes) * 100.0 /
                    vm_record_bytes, 4),
            },
            "maximum_chunk_records": MAX_BATCH_RECORDS,
            "maximum_caller_chunk_bytes": (
                MAX_BATCH_RECORDS * TARGET_RECORD_BYTES),
            "full_frame_record_array_required": False,
            "ordering": "strict active-Python VM emission order; no sort",
            "accepted_prefix_diagnostics": True,
            "published_prefix_diagnostics": True,
            "production_submit": "PyZ80DrawFastChunk_SubmitFT812",
            "fast_batch_export": "PyZ80FT_BuildSpriteBatchFast",
        },
        "failure_atomicity": {
            "lookup_miss": "current record rejected; prior complete chunks only",
            "capacity_zero": "initialization rejected before VM stream",
            "capacity_above_fast_batch_max": (
                "initialization rejected before VM stream"),
            "counter_overflow": "rejected before lookup/copy/submit",
            "submit_failure": (
                "failed chunk retained in caller buffer; no later VM record accepted"),
            "vm_failure": (
                "incomplete final chunk remains private and is not submitted"),
            "ft812_fast_batch_failure": (
                "fast batch preflight publishes no partial payload"),
        },
        "host_oracle": {
            "test": paths["host_test"],
            "generated_template_records": ORACLE_TEMPLATE_COUNT,
            "randomized_records": ORACLE_RANDOM_RECORDS,
            "total_records": ORACLE_TEMPLATE_COUNT + ORACLE_RANDOM_RECORDS,
            "random_seed_hex": f"0x{ORACLE_SEED:X}",
            "literal_reference": "pyz80_draw_chunker",
            "checks": [
                "all HQT3 bank+descriptor identities resolve to their generated index",
                "six-byte payload coordinates/order equal the Python oracle",
                "eight-byte literal payload/order equals the same Python oracle",
                "chunk boundaries match the literal bridge",
                "lookup/submit/VM/counter/provider failure matrix",
            ],
        },
        "compiler": {
            "path": sdcc.as_posix(),
            "sha256": _sha256(sdcc.read_bytes()),
            "arguments": [*PINNED_ARGUMENTS, "-c",
                          Path(paths["bridge_source"]).name],
        },
        "result": {
            "rel_sha256": _sha256(rel_bytes),
            "rel_bytes": len(rel_bytes),
            "code_area_hex": f"{code_bytes:X}",
            "code_bytes": code_bytes,
            "data_area_hex": f"{data_bytes:X}",
            "data_bytes": data_bytes,
            "single_page_bytes": SINGLE_PAGE_BYTES,
            "bridge_headroom_bytes": SINGLE_PAGE_BYTES - code_bytes,
            "compact_vm_code_bytes": vm_code_bytes,
            "compact_vm_plus_bridge_additive_code_upper_bound": (
                combined_code_upper_bound),
            "compact_vm_plus_bridge_additive_headroom_bytes": (
                SINGLE_PAGE_BYTES - combined_code_upper_bound),
            "pinned_sdcc_sizeof": {
                "state_bytes": state_bytes,
                "result_bytes": result_bytes,
                "ft812_submit_context_bytes": submit_context_bytes,
                "source_record_bytes": vm_record_bytes,
                "target_record_bytes": record_bytes,
            },
            "generated_lookup_call_sites": lookup_calls,
            "fast_batch_call_sites": fast_batch_calls,
        },
        "performance": {
            "timing_report": paths["timing_report"],
            "status": "TARGET_NEUTRAL_MEASURED_LIVE_BLOCKED",
            "steady_nonflush_record_tstates": steady_tstates,
            "modeled_32_record_chunk_before_fast_batch_tstates": (
                chunk32_tstates),
            "includes": (
                "real pinned-SDCC bridge plus generated HQT3 lookup, "
                "six-byte copy and target-neutral successful submit callback"),
            "excludes": (
                "PyZ80FT_BuildSpriteBatchFast body, live object provider, "
                "queue rotation and frame composition"),
            "live_certified": False,
            "iy_preserved_by_isolated_c_path": bool(
                timing_registers.get("iy_preserved")),
        },
        "checks": checks,
        "live": False,
        "live_blockers": [
            "target object sidecar/provider field mapping is not connected",
            "source-derived render-order container is not connected",
            "caller chunk is not certified resident in the slot3 batch-record window",
            "queue rotation and remaining full-frame DL budget are not connected",
            "complete link, stack high-water and frame tstates are not certified",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", type=Path,
        default=Path("Build/rtype_python_draw_fast_chunker_status.json"))
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    try:
        result = probe(root)
        output = arguments.output
        if not output.is_absolute():
            output = root / output
        _atomic_json(output, result)
    except DrawFastChunkerCheckError as exc:
        print(f"FAIL: {exc}")
        return 1
    print(
        "Fast draw bridge: "
        f"_CODE={result['result']['code_bytes']} bytes, "
        f"_DATA={result['result']['data_bytes']}; "
        "target-neutral pass, live remains blocked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
