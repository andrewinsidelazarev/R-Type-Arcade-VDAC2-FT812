"""Генерация узких resident adapters из декларативных target bindings."""

from __future__ import annotations

import re
from typing import Any

from .abi import (adapter_bridge_name, adapter_source_registers,
                  parameter_slot_count)
from .diagnostics import CompileError, Diagnostic
from .ir import FunctionIR
from .manifest import AdapterValueSpec, CompilerManifest


_SYMBOL = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")


def _validate_symbol(value: str, field: str) -> None:
    if not _SYMBOL.fullmatch(value):
        raise CompileError(Diagnostic(
            "PZ5101", f"недопустимый ASM symbol в {field}: {value!r}"))


def emit_call_adapters(
        manifest: CompilerManifest, functions: tuple[FunctionIR, ...]
) -> tuple[str, list[dict[str, Any]]]:
    by_export = {function.export: function for function in functions}
    lines = [
        "; Сгенерировано pyz80_compiler из call_adapters manifest.",
        "; Только ABI/MMU glue; игровая семантика находится в compiler bank.",
        "",
    ]
    report: list[dict[str, Any]] = []
    for adapter in manifest.call_adapters:
        _validate_symbol(adapter.entry, "entry")
        function = by_export[adapter.function]
        if len(adapter.arguments) != len(function.parameters):
            raise CompileError(Diagnostic(
                "PZ5103",
                f"adapter {adapter.entry}: {len(adapter.arguments)} arguments, "
                f"функция требует {len(function.parameters)}",
            ))
        for index, (value, parameter) in enumerate(
                zip(adapter.arguments, function.parameters, strict=True)):
            if value.kind == "masked_equals_bool" and not parameter.type.boolean:
                raise CompileError(Diagnostic(
                    "PZ5104",
                    f"adapter {adapter.entry}: argument {index} не bool",
                ))
            if parameter_slot_count(parameter.type) != 1:
                raise CompileError(Diagnostic(
                    "PZ5105",
                    f"adapter {adapter.entry}: многословный argument пока не поддержан",
                ))
        if adapter.result.kind != "memory_u8":
            raise CompileError(Diagnostic(
                "PZ5106", f"adapter {adapter.entry}: поддержан только memory_u8 result"))
        _validate_symbol(adapter.result.symbol, "result.symbol")
        try:
            source_registers = adapter_source_registers(adapter)
        except ValueError as exc:
            raise CompileError(Diagnostic("PZ5107", str(exc))) from exc

        lines.extend([
            f"; {function.symbol} -> {adapter.entry}",
            f"{adapter.entry}:",
            "                GetPage2",
            "                PUSH AF",
            "                PUSH IY",
        ])
        for symbol, register in source_registers.items():
            _validate_symbol(symbol, "argument.symbol")
            lines.extend([
                f"                LD   A, ({symbol})",
                f"                LD   {register}, A",
            ])
        lines.extend([
            "                LD   A, RTYPE_PY_CODE_BANK0_PAGE",
            "                SetPage2_A",
            f"                CALL {adapter_bridge_name(len(report))}",
            "                LD   D, A",
            "                POP  IY",
            "                POP  AF",
            "                SetPage2_A",
            "                LD   A, D",
        ])
        lines.extend([
            f"                LD   ({adapter.result.symbol}), A",
            "                RET",
            "",
        ])
        report.append({
            "entry": adapter.entry,
            "function": function.export,
            "bank_bridge": adapter_bridge_name(len(report)),
            "argument_slots": sum(parameter_slot_count(item.type)
                                  for item in function.parameters),
            "resident_stack_bytes": 6,
            "bank_bridge_stack_bytes": 2 * len(adapter.arguments) + 2,
            "page2_effect": "restored",
            "iy_effect": "restored",
        })
    return "\n".join(lines), report
