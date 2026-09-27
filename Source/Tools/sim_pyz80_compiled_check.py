#!/usr/bin/env python3
"""Exhaustive CPython/IR/Z80 check of compiler-produced machine code."""

from __future__ import annotations

import hashlib
import itertools
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "Source" / "Tools"
PYTHON_ROOT = ROOT / "Source" / "Python"
HMM2_TOOLS = (ROOT.parent / "HMM2" / "Pre-releases" /
              "v020-2026-07-16-adventure-ui-battle-ai-reference" /
              "Source" / "Tools")
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(HMM2_TOOLS))

from pyz80_compiler.frontend import lower_function  # noqa: E402
from pyz80_compiler.interpreter import execute  # noqa: E402
from pyz80_compiler.manifest import CompilerManifest  # noqa: E402
from tsconf_ft812_sim import RETURN_MARKER, TSConfFT812Machine  # noqa: E402


STACK_ORIGIN = 0x4E00
STACK_GUARD_START = 0x4D00
STACK_GUARD_END = 0x4DF0
STACK_SENTINEL = 0xA5


def _run(machine: TSConfFT812Machine, address: int, argument_sp: int,
         *, max_steps: int = 100_000) -> tuple[int, int]:
    entry_sp = (argument_sp - 2) & 0xFFFF
    machine.set_word(entry_sp, RETURN_MARKER)
    machine.reg.SP = entry_sp
    machine.reg.PC = address
    minimum_sp = entry_sp
    steps = 0
    while machine.reg.PC != RETURN_MARKER:
        if steps >= max_steps:
            raise AssertionError(
                f"Z80 timeout PC=${machine.reg.PC:04X} SP=${machine.reg.SP:04X}")
        machine.step()
        minimum_sp = min(minimum_sp, machine.reg.SP)
        steps += 1
    return steps, minimum_sp


def main() -> int:
    manifest = CompilerManifest.load(TOOLS / "rtype_python_compiler.json")
    spec = manifest.functions[0]
    ir, _ = lower_function(PYTHON_ROOT, spec)
    report = json.loads(
        (ROOT / "Build" / "rtype_python_compiler.json").read_text(encoding="utf-8"))
    function_report = next(
        item for item in report["functions"] if item["symbol"] == spec.symbol)
    binary = (ROOT / "Build" / "python_compiled_p00.bin").read_bytes()
    if len(binary) != manifest.target.bank_size:
        raise AssertionError("compiler bank имеет неверный размер")
    if hashlib.sha256(binary).hexdigest() != report["binary_sha256"]:
        raise AssertionError("compiler bank не совпал с отчётом")

    code_page = int(function_report["code_page"])
    address = int(function_report["address"])
    machine = TSConfFT812Machine(
        ROOT,
        load_spg=False,
        initial_pages=(0x00, 0x05, code_page, 0x04),
        default_start=f"0x{address:04X}",
        default_stack=f"0x{STACK_ORIGIN:04X}",
    )
    machine.mem.load_page_block(code_page, 0, binary)
    code_before = machine.mem.read_physical(code_page, 0, len(binary))
    original_pages = tuple(machine.mem.pages)

    maximum_stack = 0
    maximum_steps = 0
    cases = 0
    domains = [range(item.minimum, item.maximum + 1)
               for item in spec.parameters]
    for arguments in itertools.product(*domains):
        # ABI v1: right-to-left call, but first parameter is nearest to the
        # return address. Every scalar <= 16 bit occupies exactly two bytes.
        argument_sp = STACK_ORIGIN - 2 * len(arguments)
        for address_offset in range(STACK_GUARD_START, STACK_ORIGIN + 2):
            machine.set_byte(address_offset, STACK_SENTINEL)
        for index, value in enumerate(arguments):
            machine.set_word(argument_sp + index * 2, int(value) & 0xFFFF)

        machine.reg.IX = 0x1357
        machine.reg.IY = 0x2468
        expected = execute(ir, tuple(int(value) for value in arguments))
        steps, minimum_sp = _run(machine, address, argument_sp)
        actual = ((machine.reg.H << 8) | machine.reg.L) & 0xFFFF
        if actual != expected:
            raise AssertionError(
                f"{spec.symbol}{arguments}: IR={expected}, Z80={actual}")
        if machine.reg.SP != argument_sp:
            raise AssertionError(
                f"{spec.symbol}{arguments}: SP=${machine.reg.SP:04X}, "
                f"ожидался ${argument_sp:04X}")
        if machine.reg.IX != 0x1357 or machine.reg.IY != 0x2468:
            raise AssertionError(f"{spec.symbol}{arguments}: IX/IY повреждены")
        if tuple(machine.mem.pages) != original_pages:
            raise AssertionError(f"{spec.symbol}{arguments}: MMU pages изменены")
        guard = machine.get_memory(
            STACK_GUARD_START, STACK_GUARD_END - STACK_GUARD_START)
        if guard != bytes([STACK_SENTINEL]) * len(guard):
            raise AssertionError(f"{spec.symbol}{arguments}: stack guard повреждён")
        maximum_stack = max(maximum_stack, argument_sp - minimum_sp +
                            2 * len(arguments))
        maximum_steps = max(maximum_steps, steps)
        cases += 1

    if machine.mem.read_physical(code_page, 0, len(binary)) != code_before:
        raise AssertionError("сгенерированный код самомодифицировался")
    print(
        f"CPython == IR == Z80: {spec.symbol}, {cases} cases; "
        f"stack <= {maximum_stack} bytes including arguments, "
        f"steps <= {maximum_steps}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
