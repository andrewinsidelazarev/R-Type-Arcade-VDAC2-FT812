"""Атомарный frontend → IR → C → SDCC/Z80 pipeline."""

from __future__ import annotations

import ast
import copy
import hashlib
import itertools
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .abi import (ABI_NAME, STACK_SLOT_BYTES, adapter_bridge_name,
                  function_abi)
from .analysis import FunctionAnalysis, analyze_function
from .c_backend import emit_c
from .diagnostics import CompileError, Diagnostic
from .frontend import LocatedFunction, lower_function
from .interpreter import execute
from .ir import FunctionIR
from .manifest import CompilerManifest, FunctionSpec
from .toolchain import ToolchainResult, compile_c
from .z80_adapter import emit_call_adapters


@dataclass(frozen=True)
class FunctionResult:
    ir: FunctionIR
    analysis: FunctionAnalysis
    oracle_cases: int


@dataclass(frozen=True)
class CompilationResult:
    manifest: CompilerManifest
    functions: tuple[FunctionResult, ...]
    c_source: str
    toolchain: ToolchainResult
    report: dict[str, Any]


def _oracle(located: LocatedFunction) -> Callable[..., Any]:
    function = copy.deepcopy(located.node)
    function.decorator_list = []
    module = ast.Module(body=[function], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace: dict[str, Any] = dict(located.constants)
    namespace.update({"min": min, "max": max, "int": int, "bool": bool})
    exec(compile(module, str(located.relative_path), "exec"), namespace)
    return namespace[function.name]


def _verify_oracle(function: FunctionIR, located: LocatedFunction,
                   spec: FunctionSpec) -> int:
    if not spec.exhaustive:
        return 0
    domains = [range(item.minimum, item.maximum + 1)
               for item in spec.parameters]
    case_count = 1
    for domain in domains:
        case_count *= len(domain)
    if case_count > 2_000_000:
        raise CompileError(Diagnostic(
            "PZ6001", f"exhaustive domain {case_count} слишком велик"))
    oracle = _oracle(located)
    for arguments in itertools.product(*domains):
        expected = oracle(*arguments)
        actual = execute(function, tuple(int(value) for value in arguments))
        if actual != expected:
            raise CompileError(Diagnostic(
                "PZ6002",
                f"CPython/IR расходятся в {function.symbol}{arguments}: "
                f"Python={expected!r}, IR={actual!r}",
            ))
    return case_count


def _symbol_address(symbols: dict[str, int], export: str) -> int:
    candidates = (export, "_" + export)
    for candidate in candidates:
        if candidate in symbols:
            return symbols[candidate]
    raise CompileError(Diagnostic(
        "PZ6003", f"SDCC map не содержит export {export}"))


def _atomic_replace(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-pyz80")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def _atomic_text(path: Path, data: str) -> None:
    _atomic_replace(path, data.encode("utf-8"))


def compile_manifest(*, python_root: Path, manifest_path: Path,
                     output_directory: Path, asm_directory: Path,
                     c_directory: Path | None = None,
                     support_files: tuple[tuple[str, str], ...] = (),
                     support_exports: tuple[tuple[str, str], ...] = (),
                     ) -> CompilationResult:
    manifest = CompilerManifest.load(manifest_path)
    lowered: list[tuple[FunctionIR, LocatedFunction, FunctionSpec]] = []
    results: list[FunctionResult] = []
    for spec in manifest.functions:
        ir, located = lower_function(python_root, spec)
        analysis = analyze_function(
            ir,
            stack_budget=manifest.target.stack_budget,
            isr_reserve=manifest.target.isr_reserve,
        )
        oracle_cases = _verify_oracle(ir, located, spec)
        lowered.append((ir, located, spec))
        results.append(FunctionResult(ir, analysis, oracle_cases))

    functions = tuple(item[0] for item in lowered)
    c_source = emit_c(functions, manifest.call_adapters)
    adapter_source, adapter_report = emit_call_adapters(manifest, functions)
    temporary_root = Path(tempfile.mkdtemp(prefix="pyz80-", dir=output_directory))
    toolchain_directory = temporary_root / "sdcc"
    try:
        if support_files:
            toolchain = compile_c(
                c_source, manifest.target, toolchain_directory, support_files)
        else:
            toolchain = compile_c(c_source, manifest.target, toolchain_directory)
        function_exports = {
            function.export: _symbol_address(toolchain.symbols, function.export)
            for function in functions
        }
        bridge_exports = {
            adapter_bridge_name(index): _symbol_address(
                toolchain.symbols, adapter_bridge_name(index))
            for index, _ in enumerate(manifest.call_adapters)
        }
        support_addresses = {
            export: _symbol_address(toolchain.symbols, export)
            for export, _abi in support_exports
        }
        exports = {
            **function_exports,
            **bridge_exports,
            **support_addresses,
        }
        for item in adapter_report:
            item["address"] = bridge_exports[str(item["bank_bridge"])]
        code_page = manifest.target.code_pages[0]
        target_report: dict[str, Any] = {
            "cpu": manifest.target.cpu,
            "backend": manifest.target.backend,
            "origin": manifest.target.origin,
            "bank_size": manifest.target.bank_size,
            "code_page": code_page,
            "stack_budget": manifest.target.stack_budget,
            "isr_reserve": manifest.target.isr_reserve,
        }
        if manifest.target.ft812 is not None:
            target_report["ft812"] = manifest.target.ft812.to_json()
        report = {
            "format": "pyz80-compiler-report-v1",
            "architecture": "Python AST -> typed CFG IR -> C11 -> SDCC Z80",
            "manifest_sha256": hashlib.sha256(
                manifest_path.read_bytes()).hexdigest(),
            "target": target_report,
            "toolchain": {
                "kind": manifest.target.toolchain_kind,
                "version": toolchain.version,
                "executable_sha256": toolchain.executable_sha256,
                "arguments": list(toolchain.command),
            },
            "functions": [
                {
                    **item.ir.to_json(),
                    "address": function_exports[item.ir.export],
                    "code_page": code_page,
                    "analysis": item.analysis.to_json(),
                    "abi": function_abi(item.ir),
                    "oracle_cases": item.oracle_cases,
                    "status": "compiled_z80",
                }
                for item in results
            ],
            "call_adapters": adapter_report,
            "support_functions": [
                {
                    "export": export,
                    "address": support_addresses[export],
                    "code_page": code_page,
                    "abi": abi,
                    "status": "compiled_z80_support",
                }
                for export, abi in support_exports
            ],
            "binary_sha256": hashlib.sha256(toolchain.binary).hexdigest(),
            "binary_size": len(toolchain.binary),
        }
        symbols_lines = [
            "; Сгенерировано pyz80_compiler. Не редактировать.",
            f"RTYPE_PY_CODE_BANK0_PAGE EQU #{code_page:02X}",
            f"RTYPE_PY_ABI_STACK_SLOT_BYTES EQU {STACK_SLOT_BYTES}",
            f"; ABI: {ABI_NAME}",
            "",
        ]
        for export, address in sorted(exports.items()):
            symbols_lines.append(f"{export} EQU #{address:04X}")
        symbols_lines.append("")

        _atomic_replace(output_directory / "python_compiled_p00.bin",
                        toolchain.binary)
        if c_directory is not None:
            _atomic_text(c_directory / "rtype_python_compiled.c", c_source)
        _atomic_text(output_directory / "rtype_python_compiled.asm",
                     toolchain.assembly)
        _atomic_text(output_directory / "rtype_python_compiled.map",
                     toolchain.map_text)
        _atomic_text(output_directory / "rtype_python_ir.json",
                     json.dumps([function.to_json() for function in functions],
                                ensure_ascii=False, indent=2) + "\n")
        _atomic_text(output_directory / "rtype_python_compiler.json",
                     json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        _atomic_text(asm_directory / "generated_python_compiled_symbols.inc",
                     "\n".join(symbols_lines))
        _atomic_text(asm_directory / "generated_python_call_adapters.asm",
                     adapter_source)
    finally:
        shutil.rmtree(temporary_root, ignore_errors=True)
    return CompilationResult(
        manifest=manifest,
        functions=tuple(results),
        c_source=c_source,
        toolchain=toolchain,
        report=report,
    )
