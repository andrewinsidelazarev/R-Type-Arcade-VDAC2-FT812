#!/usr/bin/env python3
"""Pinned Z80 microbenchmark for the target-neutral fast draw bridge.

This deliberately does not build an SPG or touch the live renderer.  It links
the bridge with the real generated HQT3 lookup and measures isolated calls in
the same instruction-level Z80 simulator used by the FT812 queue proofs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Mapping

from pyz80_compiler.manifest import CompilerManifest
from pyz80_compiler.toolchain import locate_sdcc


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Build" / "PythonDeps"))
sys.path.insert(0, str(
    ROOT.parent / "HMM2" / "Pre-releases" /
    "v020-2026-07-16-adventure-ui-battle-ai-reference" /
    "Source" / "Tools"))

from tsconf_ft812_sim import TSConfFT812Machine  # noqa: E402


FORMAT = "pyz80-draw-fast-chunker-z80-timing-v1"
STATUS = "TARGET_NEUTRAL_MICROBENCH_PASS_LIVE_BLOCKED"
CPU_HZ = 14_000_000
PINNED_COMPILE_ARGUMENTS = (
    "-mz80",
    "--std-c11",
    "--sdcccall", "1",
    "--fno-omit-frame-pointer",
    "--stack-auto",
    "--opt-code-speed",
    "--no-c-code-in-asm",
    "-c",
)
PINNED_LINK_ARGUMENTS = (
    "-mz80",
    "--no-std-crt0",
    "--code-loc", "0x2000",
    "--data-loc", "0xB000",
)


BENCH_SOURCE = r'''#include <stdint.h>
#include "pyz80_draw_fast_chunker.h"

static PyZ80FtTemplateDrawRecord bench_buffer[128];
static PyZ80DrawFastChunkState bench_state;
static rtype_python_draw_vm_record bench_record;

static uint8_t bench_submit(void *context,
        const volatile PyZ80FtTemplateDrawRecord *records,
        uint16_t count, uint16_t first_record_index)
{
    (void)context;
    (void)records;
    (void)count;
    (void)first_record_index;
    return 1u;
}

rtype_python_draw_vm_status rtype_python_draw_vm_stream(
        const rtype_python_draw_vm_input *input,
        rtype_python_draw_vm_record_emitter emit_record,
        void *emit_context, uint16_t *output_count)
{
    (void)input;
    (void)emit_record;
    (void)emit_context;
    (void)output_count;
    return RTYPE_PYTHON_DRAW_VM_INVALID_INPUT;
}

uint8_t PyZ80DrawFastBench_Reset(void) PYZ80_CALL0
{
    bench_record.bank_key = 0x0109u;
    bench_record.descriptor = 0x38F6u;
    bench_record.anchor_x = -320;
    bench_record.anchor_y = -144;
    return PyZ80DrawFastChunk_Initialize(
        &bench_state, bench_buffer, 128u, bench_submit, 0);
}

uint8_t PyZ80DrawFastBench_Emit(void) PYZ80_CALL0
{
    return PyZ80DrawFastChunk_Emit(&bench_state, &bench_record);
}

uint8_t PyZ80DrawFastBench_Finish(void) PYZ80_CALL0
{
    return PyZ80DrawFastChunk_Finish(&bench_state);
}

uint8_t PyZ80DrawFastBench_Noop(void) PYZ80_CALL0
{
    return 1u;
}

uint8_t PyZ80DrawFastBench_Lookup(void) PYZ80_CALL0
{
    return PyZ80FT_FindHQTemplate(0x0109u, 0x38F6u) == 0u;
}
'''


class FastBridgeTimingError(RuntimeError):
    pass


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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


def _parse_ihx(path: Path) -> list[tuple[int, bytes]]:
    upper = 0
    blocks: list[tuple[int, bytes]] = []
    for line in path.read_text(encoding="ascii").splitlines():
        if not line.startswith(":"):
            continue
        raw = bytes.fromhex(line[1:])
        count = raw[0]
        address = (raw[1] << 8) | raw[2]
        record_type = raw[3]
        payload = raw[4:4 + count]
        if record_type == 0:
            blocks.append((upper + address, payload))
        elif record_type == 4:
            upper = int.from_bytes(payload, "big") << 16
        elif record_type == 1:
            break
    return blocks


def _map_symbols(text: str) -> dict[str, int]:
    result: dict[str, int] = {}
    pattern = re.compile(
        r"^\s*([0-9A-Fa-f]{8})\s+_"
        r"(PyZ80DrawFastBench_(?:Reset|Emit|Finish|Noop|Lookup))\s+",
        re.MULTILINE)
    for match in pattern.finditer(text):
        result[match.group(2)] = int(match.group(1), 16)
    expected = {
        "PyZ80DrawFastBench_Reset",
        "PyZ80DrawFastBench_Emit",
        "PyZ80DrawFastBench_Finish",
        "PyZ80DrawFastBench_Noop",
        "PyZ80DrawFastBench_Lookup",
    }
    if set(result) != expected:
        raise FastBridgeTimingError(
            "linked map lacks benchmark symbols: " +
            ", ".join(sorted(expected - set(result))))
    return result


def _map_area(text: str, name: str) -> tuple[int, int]:
    match = re.search(
        rf"^{re.escape(name)}\s+([0-9A-Fa-f]{{8}})\s+"
        rf"([0-9A-Fa-f]{{8}})\s+=",
        text, re.MULTILINE)
    if match is None:
        raise FastBridgeTimingError(f"linked map lacks {name} area")
    return int(match.group(1), 16), int(match.group(2), 16)


def _milliseconds(tstates: int) -> float:
    return round(tstates * 1000.0 / CPU_HZ, 6)


def measure(root: Path) -> dict[str, object]:
    root = root.resolve()
    source_paths = (
        "Source/C/ft812/pyz80_draw_fast_chunker.c",
        "Source/C/ft812/pyz80_draw_fast_chunker.h",
        "Source/C/ft812/pyz80_ft812.c",
        "Source/C/ft812/pyz80_ft812.h",
        "Source/C/generated/rtype_python_draw_vm.h",
        "Source/C/generated/rtype_python_hq_templates.c",
        "Source/C/generated/rtype_python_hq_templates.h",
    )
    source_hashes = {
        relative: _sha256((root / relative).read_bytes())
        for relative in source_paths
    }
    compiler_manifest = CompilerManifest.load(
        root / "Source" / "Tools" / "rtype_python_compiler.json")
    sdcc = locate_sdcc(compiler_manifest.target).resolve()
    environment = os.environ.copy()
    environment["PATH"] = (
        str(sdcc.parent) + os.pathsep + environment.get("PATH", ""))

    with tempfile.TemporaryDirectory(
            prefix="pyz80-fast-bridge-bench-") as temp:
        directory = Path(temp)
        for relative in source_paths:
            source = root / relative
            (directory / source.name).write_bytes(source.read_bytes())
        (directory / "fast_bridge_bench.c").write_text(
            BENCH_SOURCE, encoding="utf-8", newline="\n")
        objects: list[str] = []
        for source_name in (
                "pyz80_draw_fast_chunker.c", "pyz80_ft812.c",
                "rtype_python_hq_templates.c", "fast_bridge_bench.c"):
            completed = subprocess.run(
                [str(sdcc), *PINNED_COMPILE_ARGUMENTS, source_name],
                cwd=directory, check=False, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding="utf-8", errors="replace", timeout=180,
                env=environment)
            if completed.returncode != 0:
                raise FastBridgeTimingError(
                    f"pinned SDCC failed for {source_name} "
                    f"({completed.returncode}):\n{completed.stdout}")
            objects.append(source_name.replace(".c", ".rel"))
        output_name = "fast_bridge_bench.ihx"
        linked = subprocess.run(
            [str(sdcc), *PINNED_LINK_ARGUMENTS,
             "-o", output_name, *objects],
            cwd=directory, check=False, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            encoding="utf-8", errors="replace", timeout=180,
            env=environment)
        if linked.returncode != 0:
            raise FastBridgeTimingError(
                f"pinned SDCC link failed ({linked.returncode}):\n"
                f"{linked.stdout}")
        ihx_path = directory / output_name
        map_path = directory / "fast_bridge_bench.map"
        ihx_bytes = ihx_path.read_bytes()
        map_text = map_path.read_text(encoding="latin1")
        map_bytes = map_path.read_bytes()
        symbols = _map_symbols(map_text)
        code_start, code_bytes = _map_area(map_text, "_CODE")
        data_start, data_bytes = _map_area(map_text, "_DATA")

        machine = TSConfFT812Machine(
            root, load_spg=False, default_start="0x2000",
            default_stack="0xFF00")
        for address, payload in _parse_ihx(ihx_path):
            if address + len(payload) > 0x10000:
                raise FastBridgeTimingError("benchmark IHX exceeds Z80 space")
            machine.mem.write_block_linear(address, payload)

        preservation = {"sp": True, "ix": True, "iy": True}

        def call(name: str) -> tuple[int, int, int]:
            original_sp = machine.reg.SP
            original_ix = machine.reg.IX
            original_iy = machine.reg.IY
            before = machine.tstates
            steps = machine.call(symbols[name], max_steps=2_000_000)
            clocks = machine.tstates - before
            preservation["sp"] &= machine.reg.SP == original_sp
            preservation["ix"] &= machine.reg.IX == original_ix
            preservation["iy"] &= machine.reg.IY == original_iy
            if machine.reg.SP != original_sp:
                raise FastBridgeTimingError(
                    f"{name} did not preserve SP: "
                    f"SP {original_sp:04X}->{machine.reg.SP:04X}, "
                    f"IX {original_ix:04X}->{machine.reg.IX:04X}, "
                    f"IY {original_iy:04X}->{machine.reg.IY:04X}")
            return machine.reg.L, steps, clocks

        noop_result, noop_steps, noop_tstates = call(
            "PyZ80DrawFastBench_Noop")
        lookup_result, lookup_steps, lookup_tstates = call(
            "PyZ80DrawFastBench_Lookup")
        reset_result, reset_steps, reset_tstates = call(
            "PyZ80DrawFastBench_Reset")
        emit_samples: list[int] = []
        emit_steps: list[int] = []
        for index in range(128):
            result, steps, clocks = call("PyZ80DrawFastBench_Emit")
            if result != 1:
                raise FastBridgeTimingError(
                    f"benchmark emit {index} failed with {result}")
            emit_samples.append(clocks)
            emit_steps.append(steps)
        boundary_result, boundary_steps, boundary_tstates = call(
            "PyZ80DrawFastBench_Emit")
        finish_result, finish_steps, finish_tstates = call(
            "PyZ80DrawFastBench_Finish")

    if (noop_result != 1 or lookup_result != 1 or reset_result != 1 or
            boundary_result != 1 or finish_result != 1 or
            len(set(emit_samples)) != 1):
        raise FastBridgeTimingError(
            "benchmark result/steady-state timing invariant failed")
    steady_raw = emit_samples[0]
    steady_net = steady_raw - noop_tstates
    lookup_net = lookup_tstates - noop_tstates
    boundary_net = boundary_tstates - noop_tstates
    finish_net = finish_tstates - noop_tstates
    if min(steady_net, lookup_net, boundary_net, finish_net) <= 0:
        raise FastBridgeTimingError("invalid net benchmark timing")
    chunk32_net = 32 * steady_net + finish_net

    return {
        "format": FORMAT,
        "status": STATUS,
        "source_hashes": source_hashes,
        "benchmark_source_sha256": _sha256(BENCH_SOURCE.encode("utf-8")),
        "compiler": {
            "path": sdcc.as_posix(),
            "sha256": _sha256(sdcc.read_bytes()),
            "compile_arguments": list(PINNED_COMPILE_ARGUMENTS),
            "link_arguments": list(PINNED_LINK_ARGUMENTS),
        },
        "linked_image": {
            "ihx_sha256": _sha256(ihx_bytes),
            "ihx_bytes": len(ihx_bytes),
            "map_sha256": _sha256(map_bytes),
            "code_start_hex": f"0x{code_start:04X}",
            "code_bytes": code_bytes,
            "data_start_hex": f"0x{data_start:04X}",
            "data_bytes": data_bytes,
            "symbols": {
                name: f"0x{address:04X}"
                for name, address in sorted(symbols.items())
            },
        },
        "measurement": {
            "cpu_hz": CPU_HZ,
            "simulator": "TSConfFT812Machine instruction tstates",
            "valid_identity": {
                "bank_key": "0x0109",
                "descriptor": "0x38F6",
                "expected_template_index": 0,
                "anchor_x": -320,
                "anchor_y": -144,
            },
            "wrapper_baseline": {
                "steps": noop_steps,
                "tstates": noop_tstates,
            },
            "generated_lookup_hit": {
                "steps": lookup_steps,
                "raw_wrapper_tstates": lookup_tstates,
                "net_tstates": lookup_net,
                "milliseconds_at_14mhz": _milliseconds(lookup_net),
            },
            "initialize": {
                "steps": reset_steps,
                "raw_wrapper_tstates": reset_tstates,
                "net_tstates": reset_tstates - noop_tstates,
            },
            "steady_nonflush_record": {
                "sample_count": len(emit_samples),
                "all_samples_equal": True,
                "steps": emit_steps[0],
                "raw_wrapper_tstates": steady_raw,
                "net_tstates": steady_net,
                "milliseconds_at_14mhz": _milliseconds(steady_net),
            },
            "capacity_boundary_flush_then_record": {
                "steps": boundary_steps,
                "raw_wrapper_tstates": boundary_tstates,
                "net_tstates": boundary_net,
                "increment_over_steady_tstates": boundary_net - steady_net,
            },
            "final_one_record_submit": {
                "steps": finish_steps,
                "raw_wrapper_tstates": finish_tstates,
                "net_tstates": finish_net,
            },
            "modeled_32_record_chunk_before_fast_batch": {
                "net_tstates": chunk32_net,
                "net_tstates_per_record": round(chunk32_net / 32.0, 4),
                "milliseconds_at_14mhz": _milliseconds(chunk32_net),
                "includes": (
                    "32 generated lookup hits, 32 six-byte copies and one "
                    "successful target-neutral submit callback"),
                "excludes": "PyZ80FT_BuildSpriteBatchFast body",
            },
        },
        "register_and_stack_checks": {
            "sp_preserved": preservation["sp"],
            "ix_preserved": preservation["ix"],
            "iy_preserved": preservation["iy"],
            "iy_policy": (
                "pinned SDCC uses IY as a scratch/frame register here; the "
                "future live call adapter must preserve any resident-runtime "
                "IY contract explicitly"),
        },
        "live": False,
        "live_blockers": [
            "microbenchmark uses a target-neutral submit callback, not queue rotation",
            "object provider and source-derived render-order container are not linked",
            "physical slot3 record residency is not certified",
            "complete frame stack/link/tstate certificate is not available",
            "live adapter IY preservation is not implemented",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", type=Path,
        default=Path("Build/rtype_python_draw_fast_chunker_timing.json"))
    arguments = parser.parse_args()
    try:
        result = measure(ROOT)
        output = arguments.output
        if not output.is_absolute():
            output = ROOT / output
        _atomic_json(output, result)
    except (FastBridgeTimingError, OSError, ValueError) as exc:
        print(f"FAIL: {exc}")
        return 1
    steady = result["measurement"]["steady_nonflush_record"]["net_tstates"]
    chunk32 = result["measurement"][
        "modeled_32_record_chunk_before_fast_batch"]["net_tstates"]
    print(
        f"Fast bridge timing: steady={steady} tstates/record, "
        f"chunk32={chunk32} tstates before fast batch; live remains blocked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
