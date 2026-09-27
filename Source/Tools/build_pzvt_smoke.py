#!/usr/bin/env python3
"""Build a separate SPG that executes one active-Python PZVT function on Z80."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Source/Tools"))

from pyz80_compiler.whole_program_vm_backend import decode_compact_target_vm

CALLABLE_ID = "rtype_port.game::wave_power@158"
FIRST_IMAGE_PAGE = 0xC0
PAGE_BYTES = 0x4000


def run(command: list[str], *, cwd: Path = ROOT,
        environment: dict[str, str] | None = None) -> str:
    completed = subprocess.run(command, cwd=cwd, check=False, text=True,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT,
                               encoding="utf-8", errors="replace",
                               env=environment)
    if completed.returncode:
        raise RuntimeError("command failed:\n" + completed.stdout)
    return completed.stdout


def symbol(map_text: str, name: str) -> int:
    match = re.search(rf"^\s*{re.escape(name)}\s+([0-9A-Fa-f]{{4,8}})\b",
                      map_text, re.MULTILINE)
    if match is None:
        match = re.search(rf"^\s*([0-9A-Fa-f]{{4,8}})\s+{re.escape(name)}\b",
                          map_text, re.MULTILINE)
    if match is None:
        raise RuntimeError(f"missing linker symbol {name}")
    return int(match.group(1), 16)


def main() -> int:
    build = ROOT / "Build"
    graph = json.loads((build / "rtype_python_active_call_graph_status.json").read_text(
        encoding="utf-8"))
    status = json.loads((build / "rtype_python_whole_program_vm_status.json").read_text(
        encoding="utf-8"))
    checkpoint = json.loads((build / "rtype_python_translation_checkpoint.json").read_text(
        encoding="utf-8"))
    if checkpoint.get("coherent") is not True:
        raise RuntimeError("translator checkpoint is not coherent")
    image = (build / "rtype_python_whole_program_vm.bin").read_bytes()
    target = status["target_bytecode"]
    if len(image) != target["bytes"] or hashlib.sha256(image).hexdigest() != target["sha256"]:
        raise RuntimeError("PZVT does not match translator status")
    program = decode_compact_target_vm(
        image, expected_proof_semantic_sha256=status["artifact_semantic_sha256"])
    ids = graph["call_graph"]["proven_reachable_callable_ids"]
    function_id = ids.index(CALLABLE_ID)
    root_unit = int(program["functions"][function_id])
    reachable: set[int] = set()
    pending = [root_unit]
    while pending:
        unit_id = pending.pop()
        if unit_id in reachable:
            continue
        reachable.add(unit_id)
        for block in program["units"][unit_id]["blocks"]:
            for row in [*block["instructions"], block["terminator"]]:
                if isinstance(row.get("unit"), int):
                    pending.append(row["unit"])

    def required_depth(unit_id: int, visiting: frozenset[int] = frozenset()) -> int:
        if unit_id in visiting:
            raise RuntimeError("recursive unit closure in wave_power")
        children = []
        for block in program["units"][unit_id]["blocks"]:
            for row in [*block["instructions"], block["terminator"]]:
                if isinstance(row.get("unit"), int):
                    children.append(row["unit"])
        return 1 + max((required_depth(child, visiting | {unit_id})
                        for child in children), default=0)

    unit = program["units"][root_unit]
    max_depth = required_depth(root_unit)
    frame_slots = max(int(program["units"][item]["frame_slot_count"])
                      for item in reachable)

    adapter_ids: set[int] = set()
    lt_symbols: set[int] = set()
    for unit_id in reachable:
        for block in program["units"][unit_id]["blocks"]:
            for row in [*block["instructions"], block["terminator"]]:
                if isinstance(row.get("adapter_id"), int):
                    adapter_ids.add(row["adapter_id"])
                    for argument in row.get("arguments", []):
                        if (argument.get("kind") == "constant" and
                                program["constants"][argument["id"]] == "lt"):
                            lt_symbols.add(argument["id"])
    if len(adapter_ids) != 1 or len(lt_symbols) != 1:
        raise RuntimeError("wave_power adapter closure differs")

    proof = bytes.fromhex(status["artifact_semantic_sha256"])
    arena_bytes = max_depth * 18 + max_depth * frame_slots * 10 + 3 * 8
    generated_h = ROOT / "Source/C/python_vm/pyz80_target_smoke_generated.h"
    generated_h.write_text(
        "/* Generated from coherent PZVT checkpoint. */\n"
        f"#define PZVT_IMAGE_BYTES {len(image)}ul\n"
        f"#define PZVT_FIRST_PAGE 0x{FIRST_IMAGE_PAGE:02x}u\n"
        f"#define PZVT_WAVE_FUNCTION {function_id}u\n"
        f"#define PZVT_COMPARE_ADAPTER {next(iter(adapter_ids))}u\n"
        f"#define PZVT_LT_SYMBOL {next(iter(lt_symbols))}u\n"
        f"#define PZVT_WAVE_MAX_DEPTH {max_depth}u\n"
        f"#define PZVT_WAVE_FRAME_SLOTS {frame_slots}u\n"
        f"#define PZVT_SMOKE_ARENA_BYTES {arena_bytes}u\n"
        "#define PZVT_SMOKE_CHARGE 72ul\n"
        "#define PZVT_PROOF_SHA256_BYTES {" + ",".join(
            f"0x{byte:02x}" for byte in proof) + "}\n",
        encoding="utf-8", newline="\n")

    pages = (len(image) + PAGE_BYTES - 1) // PAGE_BYTES
    for index in range(pages):
        payload = image[index * PAGE_BYTES:(index + 1) * PAGE_BYTES]
        (build / f"pzvt_smoke_image_p{index:02d}.bin").write_bytes(payload)

    scratch = build / "PZVTSmoke"
    reuse_link = (os.environ.get("PZVT_SMOKE_REUSE") == "1" and
                  (scratch / "pzvt_smoke_code.bin").is_file() and
                  (scratch / "pzvt_smoke.map").is_file())
    if not reuse_link and scratch.exists():
        shutil.rmtree(scratch)
    scratch.mkdir(exist_ok=True)
    for name in ("pyz80_whole_program_vm.c", "pyz80_whole_program_vm.h",
                 "pyz80_target_smoke.c", "pyz80_target_smoke_generated.h"):
        shutil.copy2(ROOT / "Source/C/python_vm" / name, scratch / name)
    sdcc = Path("E:/zx/sdcc/bin/sdcc.exe")
    environment = os.environ.copy()
    environment["PATH"] = str(sdcc.parent) + os.pathsep + environment.get("PATH", "")
    if not reuse_link:
        for name in ("pyz80_whole_program_vm.c", "pyz80_target_smoke.c"):
            run([str(sdcc), "-mz80", "--std-c11", "--sdcccall", "1",
                 "--fno-omit-frame-pointer", "--stack-auto", "--opt-code-speed",
                 "--no-c-code-in-asm", "-DPYZ80_VM_TRUST_PACKAGED_IMAGE=1",
                 "-c", name], cwd=scratch,
                environment=environment)
        run([str(sdcc), "-mz80", "--no-std-crt0", "--sdcccall", "1",
             "--out-fmt-ihx", "--code-loc", "0x8000", "--data-loc", "0x3000",
             "-o", "pzvt_smoke.ihx", "pyz80_whole_program_vm.rel",
             "pyz80_target_smoke.rel"], cwd=scratch, environment=environment)
        makebin = sdcc.with_name("makebin.exe")
        run([str(makebin), "-s", "65536", "-o", "32768", "pzvt_smoke.ihx",
             "pzvt_smoke_code.bin"], cwd=scratch, environment=environment)
    code = (scratch / "pzvt_smoke_code.bin").read_bytes()
    if len(code) != 0x8000:
        raise RuntimeError(f"unexpected linked code size {len(code)}")
    (build / "pzvt_smoke_code_p00.bin").write_bytes(code[:PAGE_BYTES])
    (build / "pzvt_smoke_code_p01.bin").write_bytes(code[PAGE_BYTES:])
    map_text = (scratch / "pzvt_smoke.map").read_text(encoding="latin1")
    entry = symbol(map_text, "_PZVTSmoke_Run")
    (ROOT / "Source/ASM/generated_pzvt_smoke_symbols.inc").write_text(
        "; Generated from linked target C runtime.\n"
        f"PZVTSmoke_Run EQU #{entry:04X}\n"
        f"PZVT_SMOKE_FIRST_PAGE EQU #{FIRST_IMAGE_PAGE:02X}\n",
        encoding="utf-8", newline="\n")

    sjasm = ROOT.parent / "z80/tsconf_project/exe/sjasmplus/sjasmplus.exe"
    run([str(sjasm), "Source/ASM/pzvt_smoke.asm", "--syntax=ab",
         "--lst=Build/pzvt_smoke.lst", "--sym=Build/pzvt_smoke.sym"])
    ini_lines = [
        "Desc = PZVT active-Python Z80 smoke", "Start = 0x5000",
        "Stack = 0x3FFF", "Resident = 0x4F00", "Page3 = 0",
        "Clock = 2", "INT = 0", "Pager = 0x0", "Compression = 0", "",
        "Block = #5000, #05, Build/pzvt_smoke_boot.bin",
        "Block = #0000, #F0, Build/pzvt_smoke_code_p00.bin",
        "Block = #0000, #F1, Build/pzvt_smoke_code_p01.bin",
    ]
    ini_lines.extend(
        f"Block = #0000, #{FIRST_IMAGE_PAGE + index:02X}, Build/pzvt_smoke_image_p{index:02d}.bin"
        for index in range(pages))
    ini = ROOT / "Build/pzvt_smoke.ini"
    ini.write_text("\n".join(ini_lines) + "\n", encoding="utf-8", newline="\n")
    spgbld = ROOT.parent / "z80/tsconf_project/exe/spgbld/spgbld.exe"
    run([str(spgbld), "-b", str(ini), "Build/rtype_pzvt_smoke.spg"])
    output = build / "rtype_pzvt_smoke.spg"
    print(json.dumps({"spg": str(output), "bytes": output.stat().st_size,
                      "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                      "function_id": function_id, "max_depth": max_depth,
                      "frame_slots": frame_slots,
                      "pZVT_pages": pages, "c_entry": entry}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
