"""Стабильный внешний ABI скомпилированных Python-функций для Z80."""

from __future__ import annotations

from typing import Any

from .ir import FunctionIR
from .manifest import CallAdapterSpec
from .types import ScalarType


ABI_NAME = "pyz80-z80-stack-v1"
STACK_SLOT_BYTES = 2
ADAPTER_SOURCE_REGISTERS = ("D", "E")


def adapter_bridge_name(index: int) -> str:
    return f"RTypePyABI_Bridge_{index:03d}"


def adapter_source_registers(adapter: CallAdapterSpec) -> dict[str, str]:
    symbols: list[str] = []
    for argument in adapter.arguments:
        if argument.symbol not in symbols:
            symbols.append(argument.symbol)
    if len(symbols) > len(ADAPTER_SOURCE_REGISTERS):
        raise ValueError(
            f"adapter {adapter.entry} требует {len(symbols)} source registers; "
            f"доступно {len(ADAPTER_SOURCE_REGISTERS)}")
    return dict(zip(symbols, ADAPTER_SOURCE_REGISTERS, strict=False))


def parameter_c_type(value_type: ScalarType) -> str:
    """Тип публичного C-параметра, реализующий двухбайтовые ABI slots."""
    if value_type.bits is None or value_type.bits > 32:
        raise ValueError(f"тип {value_type.name} не поддержан ABI {ABI_NAME}")
    if value_type.bits <= 16:
        return "uint16_t"
    return "uint32_t"


def parameter_slot_count(value_type: ScalarType) -> int:
    if value_type.bits is None or value_type.bits <= 0:
        raise ValueError(f"тип {value_type.name} нельзя передать как параметр")
    return (value_type.bits + 15) // 16


def return_registers(value_type: ScalarType) -> tuple[str, ...]:
    # SDCC __sdcccall(0): 8 bit -> L, 16 bit -> HL, 32 bit -> DEHL.
    if value_type.bits is None:
        raise ValueError(f"тип {value_type.name} нельзя вернуть через ABI")
    if value_type.bits == 0:
        return ()
    if value_type.bits <= 8:
        return ("L",)
    if value_type.bits <= 16:
        return ("HL",)
    if value_type.bits <= 32:
        return ("DE", "HL")
    raise ValueError(f"тип {value_type.name} нельзя вернуть через ABI")


def function_abi(function: FunctionIR) -> dict[str, Any]:
    offset = 2  # адрес возврата лежит по SP+0 при входе в функцию
    parameters: list[dict[str, Any]] = []
    for parameter in function.parameters:
        slots = parameter_slot_count(parameter.type)
        parameters.append({
            "name": parameter.name,
            "type": parameter.type.name,
            "stack_offset": offset,
            "slot_bytes": slots * STACK_SLOT_BYTES,
            "encoding": "little-endian-twos-complement",
        })
        offset += slots * STACK_SLOT_BYTES
    return {
        "name": ABI_NAME,
        "argument_order": "right-to-left",
        "stack_cleanup": "caller",
        "stack_slot_bytes": STACK_SLOT_BYTES,
        "parameters": parameters,
        "return": {
            "type": function.return_type.name,
            "registers": list(return_registers(function.return_type)),
        },
        "callee_saved": ["IX"],
        "caller_saved": ["AF", "BC", "DE", "HL", "IY"],
        "alternate_registers": "unavailable",
        "stack_delta_on_return": 0,
    }
