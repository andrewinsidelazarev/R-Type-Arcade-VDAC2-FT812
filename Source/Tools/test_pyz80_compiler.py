#!/usr/bin/env python3
"""Focused acceptance tests for the static Python -> IR -> Z80 pipeline."""
from __future__ import annotations

import ast
import copy
import hashlib
import itertools
import json
import re
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "Source" / "Tools"
PYTHON_ROOT = ROOT / "Source" / "Python"
sys.path.insert(0, str(TOOLS))

from pyz80_compiler import CompileError, Diagnostic, compile_manifest  # noqa: E402
from pyz80_compiler.analysis import analyze_function  # noqa: E402
from pyz80_compiler.frontend import LocatedFunction, lower_function  # noqa: E402
from pyz80_compiler.interpreter import execute  # noqa: E402
from pyz80_compiler.manifest import (  # noqa: E402
    CompilerManifest,
    FunctionSpec,
    ParameterSpec,
)
import pyz80_compiler.pipeline as pipeline  # noqa: E402
from pyz80_compiler.toolchain import ToolchainResult  # noqa: E402
from pyz80_compiler.types import U16  # noqa: E402


OUTPUT_NAMES = (
    "python_compiled_p00.bin",
    "rtype_python_compiled.asm",
    "rtype_python_compiled.map",
    "rtype_python_ir.json",
    "rtype_python_compiler.json",
)
GENERATED_C_NAME = "rtype_python_compiled.c"
SYMBOL_INCLUDE = "generated_python_compiled_symbols.inc"


def _function_spec(symbol: str, export: str, *, exhaustive: bool = True,
                   minimum: int = 0, maximum: int = 3) -> FunctionSpec:
    return FunctionSpec(
        symbol=symbol,
        export=export,
        parameters=(ParameterSpec("value", U16, minimum, maximum),),
        return_type=U16,
        exhaustive=exhaustive,
    )


def _write_manifest(path: Path, *, symbol: str, export: str,
                    exhaustive: bool = True, minimum: int = 0,
                    maximum: int = 3, ft812: bool = False) -> None:
    payload = {
        "format": "pyz80-compiler-v1",
        "target": {
            "cpu": "z80",
            "backend": "sdcc-c",
            "toolchain": {
                "kind": "sdcc",
                "version": "test-toolchain-1",
                "sha256": "A" * 64,
            },
            "origin": 0x8000,
            "bank_size": 0x4000,
            "code_pages": [0xF0],
            "stack_budget": 992,
            "isr_reserve": 32,
        },
        "functions": [{
            "symbol": symbol,
            "export": export,
            "parameters": [{
                "name": "value",
                "type": "u16",
                "minimum": minimum,
                "maximum": maximum,
            }],
            "return": "u16",
            "exhaustive": exhaustive,
        }],
    }
    if ft812:
        payload["target"]["ft812"] = {
            "mode": "TEST_1024_768",
            "width": 1024,
            "height": 768,
            "hcycle": 1344,
            "pclk": 1,
            "safety_utilization": 0.90,
            "ram_dl_word_limit": 2048,
            "cmd_fifo_bytes": 4096,
            "cmd_fifo_usable": 4092,
        }
    path.write_text(
        json.dumps(payload, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _cpython_function(located: LocatedFunction):
    """Execute only the selected function AST using CPython semantics."""
    function = copy.deepcopy(located.node)
    function.decorator_list = []
    module = ast.Module(body=[function], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = dict(located.constants)
    namespace.update({"min": min, "max": max, "int": int, "bool": bool})
    exec(compile(module, str(located.relative_path), "exec"), namespace)
    return namespace[function.name]


def _fake_compile_c(
        source: str, target, directory: Path,
        support_files: tuple[tuple[str, str], ...] = (),
        ) -> ToolchainResult:
    """Deterministic replacement for the external SDCC boundary."""
    directory.mkdir(parents=True, exist_ok=False)
    linked_source = source + "\n" + "\n".join(
        contents for name, contents in support_files if name.endswith(".c"))
    exports = re.findall(
        r"^(?:u?int(?:8|16|32)_t)\s+([A-Za-z_][A-Za-z0-9_]*)\(",
        linked_source,
        flags=re.MULTILINE,
    )
    exports = list(dict.fromkeys(exports))
    symbols = {
        "_" + name: target.origin + index * 0x20
        for index, name in enumerate(exports)
    }
    digest = hashlib.sha256(linked_source.encode("utf-8")).digest()
    binary = (digest * ((target.bank_size + len(digest) - 1) // len(digest)))[
        :target.bank_size
    ]
    map_text = "\n".join(
        f"{address:08X} {name}" for name, address in sorted(symbols.items())
    ) + "\n"
    return ToolchainResult(
        binary=binary,
        assembly="; deterministic test toolchain\n" + linked_source,
        map_text=map_text,
        symbols=symbols,
        command=("sdcc", "<SOURCE>/compiled.c", "-o", "<OUTPUT>/compiled.ihx"),
        version=target.toolchain_version,
        executable_sha256=target.toolchain_sha256,
    )


def _tree_snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class PyZ80CompilerTests(unittest.TestCase):
    def test_project_manifest_uses_practical_ft812_line_margin(self) -> None:
        manifest = CompilerManifest.load(
            TOOLS / "rtype_python_compiler.json")
        ft812 = manifest.target.ft812
        self.assertIsNotNone(ft812)
        assert ft812 is not None
        self.assertEqual(ft812.mode, "VM_1024_768_59Hz")
        self.assertEqual(ft812.line_cycles, 1344)
        self.assertEqual(ft812.safe_line_cycles, 1209)
        self.assertEqual(ft812.ram_dl_word_limit, 2048)
        self.assertEqual(ft812.cmd_fifo_bytes, 4096)
        self.assertEqual(ft812.cmd_fifo_usable, 4092)

    def test_ft812_target_budget_is_typed_and_emitted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            python_root = work / "python"
            python_root.mkdir()
            (python_root / "valid.py").write_text(
                "def identity(value):\n    return value\n",
                encoding="utf-8",
                newline="\n",
            )
            manifest_path = work / "manifest.json"
            _write_manifest(
                manifest_path,
                symbol="valid.identity",
                export="Compiled_Identity",
                ft812=True,
            )
            output = work / "output"
            asm = work / "asm"
            output.mkdir()
            asm.mkdir()

            manifest = CompilerManifest.load(manifest_path)
            ft812 = manifest.target.ft812
            self.assertIsNotNone(ft812)
            assert ft812 is not None
            self.assertEqual(ft812.line_cycles, 1344)
            self.assertEqual(ft812.safe_line_cycles, 1209)

            with mock.patch.object(pipeline, "compile_c", _fake_compile_c):
                result = compile_manifest(
                    python_root=python_root,
                    manifest_path=manifest_path,
                    output_directory=output,
                    asm_directory=asm,
                )

            reported = result.report["target"]["ft812"]
            self.assertEqual(reported["line_cycles"], 1344)
            self.assertEqual(reported["safe_line_cycles"], 1209)
            self.assertEqual(reported["ram_dl_word_limit"], 2048)
            self.assertEqual(reported["cmd_fifo_usable"], 4092)

    def test_ft812_target_rejects_fifo_without_reserved_word(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manifest_path = Path(temporary) / "manifest.json"
            _write_manifest(
                manifest_path,
                symbol="valid.identity",
                export="Compiled_Identity",
                ft812=True,
            )
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            payload["target"]["ft812"]["cmd_fifo_usable"] = 4096
            manifest_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaises(CompileError) as raised:
                CompilerManifest.load(manifest_path)
            self.assertEqual(raised.exception.diagnostic.code, "PZ1124")

    def test_module_is_parsed_as_ast_without_importing_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            python_root = work / "python"
            python_root.mkdir()
            marker = work / "MODULE_WAS_IMPORTED"
            (python_root / "trap.py").write_text(
                textwrap.dedent(f"""\
                    from pathlib import Path
                    Path({str(marker)!r}).write_text("imported", encoding="utf-8")
                    raise RuntimeError("compiler imported source module")

                    def identity(value):
                        return value
                """),
                encoding="utf-8",
                newline="\n",
            )
            manifest_path = work / "manifest.json"
            _write_manifest(
                manifest_path,
                symbol="trap.identity",
                export="Compiled_Identity",
            )
            output = work / "output"
            asm = work / "asm"
            c_output = work / "c"
            output.mkdir()
            asm.mkdir()
            c_output.mkdir()

            with mock.patch.object(pipeline, "compile_c", _fake_compile_c):
                result = compile_manifest(
                    python_root=python_root,
                    manifest_path=manifest_path,
                    output_directory=output,
                    asm_directory=asm,
                    c_directory=c_output,
                )

            self.assertFalse(marker.exists())
            self.assertEqual(
                (c_output / GENERATED_C_NAME).read_text(encoding="utf-8"),
                result.c_source,
            )
            self.assertFalse((output / GENERATED_C_NAME).exists())
            self.assertEqual(result.functions[0].oracle_cases, 4)
            self.assertEqual(result.functions[0].ir.blocks[
                result.functions[0].ir.entry].instructions[0].op, "load_local")

    def test_advance_pitch_exhaustive_cpython_equals_ir(self) -> None:
        manifest = CompilerManifest.load(
            TOOLS / "rtype_python_compiler.json")
        spec = next(
            item for item in manifest.functions
            if item.symbol == "rtype_port.game.advance_pitch"
        )
        function, located = lower_function(PYTHON_ROOT, spec)
        analysis = analyze_function(
            function,
            stack_budget=manifest.target.stack_budget,
            isr_reserve=manifest.target.isr_reserve,
        )
        oracle = _cpython_function(located)

        cases = 0
        domains = [range(item.minimum, item.maximum + 1)
                   for item in spec.parameters]
        for arguments in itertools.product(*domains):
            expected = oracle(*arguments)
            actual = execute(function, tuple(int(value) for value in arguments))
            with self.subTest(arguments=arguments):
                self.assertEqual(actual, expected)
            cases += 1

        self.assertEqual(cases, 160)
        self.assertEqual(
            (analysis.return_interval.minimum, analysis.return_interval.maximum),
            (0, 39),
        )

    def test_support_c_exports_are_emitted_for_resident_asm(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            python_root = work / "python"
            python_root.mkdir()
            (python_root / "valid.py").write_text(
                "def identity(value):\n    return value\n",
                encoding="utf-8",
                newline="\n",
            )
            manifest_path = work / "manifest.json"
            _write_manifest(
                manifest_path,
                symbol="valid.identity",
                export="Compiled_Identity",
            )
            output = work / "output"
            asm = work / "asm"
            c_output = work / "c"
            output.mkdir()
            asm.mkdir()
            c_output.mkdir()

            with mock.patch.object(pipeline, "compile_c", _fake_compile_c):
                result = compile_manifest(
                    python_root=python_root,
                    manifest_path=manifest_path,
                    output_directory=output,
                    asm_directory=asm,
                    c_directory=c_output,
                    support_files=((
                        "support.c",
                        "#include <stdint.h>\n"
                        "uint8_t SupportPing(void) { return 1u; }\n",
                    ),),
                    support_exports=(("SupportPing", "sdcccall(0)"),),
                )

            support = result.report["support_functions"]
            self.assertEqual(len(support), 1)
            self.assertEqual(support[0]["export"], "SupportPing")
            self.assertEqual(support[0]["abi"], "sdcccall(0)")
            include = (asm / SYMBOL_INCLUDE).read_text(encoding="utf-8")
            self.assertRegex(include, r"(?m)^SupportPing EQU #[0-9A-F]{4}$")

    def test_unsupported_ast_reports_stable_relative_source_span(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            python_root = Path(temporary)
            (python_root / "bad.py").write_text(
                "def convert(value):\n    return str(value)\n",
                encoding="utf-8",
                newline="\n",
            )
            spec = _function_spec(
                "bad.convert", "Compiled_Convert", exhaustive=False)

            with self.assertRaises(CompileError) as raised:
                lower_function(python_root, spec)

            diagnostic = raised.exception.diagnostic
            self.assertEqual(diagnostic.code, "PZ2004")
            self.assertEqual(
                diagnostic.message,
                "неподдержанный AST Call: разрешены только чистые min/max "
                "с двумя аргументами",
            )
            self.assertIsNotNone(diagnostic.span)
            assert diagnostic.span is not None
            self.assertEqual(
                (diagnostic.span.path, diagnostic.span.line,
                 diagnostic.span.column, diagnostic.span.end_line,
                 diagnostic.span.end_column),
                ("bad.py", 2, 11, 2, 21),
            )
            self.assertEqual(
                diagnostic.render(),
                "bad.py:2:12: PZ2004: неподдержанный AST Call: разрешены "
                "только чистые min/max с двумя аргументами",
            )

    def test_toolchain_failure_leaves_all_outputs_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            python_root = work / "python"
            python_root.mkdir()
            (python_root / "valid.py").write_text(
                "def identity(value):\n    return value\n",
                encoding="utf-8",
                newline="\n",
            )
            manifest_path = work / "manifest.json"
            _write_manifest(
                manifest_path,
                symbol="valid.identity",
                export="Compiled_Identity",
            )
            output = work / "output"
            asm = work / "asm"
            c_output = work / "c"
            output.mkdir()
            asm.mkdir()
            c_output.mkdir()
            for index, name in enumerate(OUTPUT_NAMES):
                (output / name).write_bytes(f"sentinel-output-{index}".encode())
            (c_output / GENERATED_C_NAME).write_bytes(b"sentinel-c-source")
            (asm / SYMBOL_INCLUDE).write_bytes(b"sentinel-symbols")
            (work / "unrelated.bin").write_bytes(b"untouched")
            before = _tree_snapshot(work)

            def fail_toolchain(_source, _target, directory):
                directory.mkdir(parents=True, exist_ok=False)
                (directory / "partial-object.rel").write_bytes(b"partial")
                raise CompileError(Diagnostic(
                    "PZ5999", "injected toolchain failure"))

            with mock.patch.object(
                    pipeline, "compile_c", side_effect=fail_toolchain):
                with self.assertRaises(CompileError) as raised:
                    compile_manifest(
                        python_root=python_root,
                        manifest_path=manifest_path,
                        output_directory=output,
                        asm_directory=asm,
                        c_directory=c_output,
                    )

            self.assertEqual(raised.exception.diagnostic.code, "PZ5999")
            self.assertEqual(_tree_snapshot(work), before)

    def test_outputs_are_identical_under_different_absolute_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            common = Path(temporary)
            snapshots: list[dict[str, bytes]] = []
            absolute_roots: list[Path] = []
            source = textwrap.dedent("""\
                LIMIT = 3

                def clamp(value):
                    return min(LIMIT, value)
            """)
            for root_name in ("first-absolute-root", "second-absolute-root"):
                root = common / root_name
                absolute_roots.append(root)
                python_root = root / "python"
                module_dir = python_root / "package"
                module_dir.mkdir(parents=True)
                (module_dir / "logic.py").write_text(
                    source, encoding="utf-8", newline="\n")
                manifest_path = root / "manifest.json"
                _write_manifest(
                    manifest_path,
                    symbol="package.logic.clamp",
                    export="Compiled_Clamp",
                    minimum=0,
                    maximum=10,
                )
                output = root / "output"
                asm = root / "asm"
                c_output = root / "c"
                output.mkdir()
                asm.mkdir()
                c_output.mkdir()

                with mock.patch.object(pipeline, "compile_c", _fake_compile_c):
                    compile_manifest(
                        python_root=python_root,
                        manifest_path=manifest_path,
                        output_directory=output,
                        asm_directory=asm,
                        c_directory=c_output,
                    )

                generated = {
                    "output/" + name: (output / name).read_bytes()
                    for name in OUTPUT_NAMES
                }
                generated["asm/" + SYMBOL_INCLUDE] = (
                    asm / SYMBOL_INCLUDE).read_bytes()
                generated["c/" + GENERATED_C_NAME] = (
                    c_output / GENERATED_C_NAME).read_bytes()
                snapshots.append(generated)

                serialized = b"\n".join(generated.values()).decode(
                    "utf-8", errors="ignore")
                self.assertNotIn(str(root), serialized)
                self.assertNotIn(str(root).replace("\\", "/"), serialized)

            self.assertEqual(snapshots[0], snapshots[1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
