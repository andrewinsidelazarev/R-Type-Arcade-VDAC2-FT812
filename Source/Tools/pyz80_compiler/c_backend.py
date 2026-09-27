"""Детерминированный C11 backend для SDCC/Z80."""

from __future__ import annotations

from .abi import (adapter_bridge_name, adapter_source_registers,
                  parameter_c_type)
from .ir import FunctionIR, Instruction
from .manifest import CallAdapterSpec
from .types import parse_type


C_TYPE = {
    "bool": "uint8_t",
    "u8": "uint8_t",
    "i8": "int8_t",
    "u16": "uint16_t",
    "i16": "int16_t",
    "u32": "uint32_t",
    "i32": "int32_t",
}


def _name(value: str) -> str:
    return "pyz80_v" + value[1:] if value.startswith("%") else value


def _storage_name(instruction: Instruction) -> str:
    name = str(instruction.attributes.get("storage_type",
                                          instruction.type.name if instruction.type else "u16"))
    return C_TYPE[name]


def _cast(value: str, signed: bool) -> str:
    return f"({'int16_t' if signed else 'uint16_t'})({_name(value)})"


def _instruction_lines(instruction: Instruction) -> list[str]:
    op = instruction.op
    args = instruction.arguments
    destination = _name(instruction.destination) if instruction.destination else ""
    if op == "const":
        return [f"    {destination} = ({_storage_name(instruction)})({int(args[0])});"]
    if op == "load_local":
        return [f"    {destination} = {_name(str(args[0]))};"]
    if op == "store_local":
        return [f"    {_name(str(args[0]))} = {_name(str(args[1]))};"]
    if op == "unary":
        operators = {"pos": "+", "neg": "-", "invert": "~", "not": "!"}
        return [f"    {destination} = {operators[str(args[0])]}{_name(str(args[1]))};"]
    if op == "binary":
        operators = {
            "add": "+", "sub": "-", "mul": "*", "floordiv": "/",
            "mod": "%", "lshift": "<<", "rshift": ">>",
            "bitand": "&", "bitor": "|", "bitxor": "^",
        }
        return [
            f"    {destination} = {_name(str(args[1]))} "
            f"{operators[str(args[0])]} {_name(str(args[2]))};"
        ]
    if op == "compare":
        operators = {"eq": "==", "ne": "!=", "lt": "<", "le": "<=",
                     "gt": ">", "ge": ">="}
        signed = bool(instruction.attributes.get("signed", False))
        return [
            f"    {destination} = (uint8_t)("
            f"{_cast(str(args[1]), signed)} {operators[str(args[0])]} "
            f"{_cast(str(args[2]), signed)});"
        ]
    if op == "select":
        return [
            f"    {destination} = {_name(str(args[0]))} ? "
            f"{_name(str(args[1]))} : {_name(str(args[2]))};"
        ]
    if op == "intrinsic":
        signed = bool(instruction.attributes.get("signed", False))
        operator = "<=" if args[0] == "min" else ">="
        left = _cast(str(args[1]), signed)
        right = _cast(str(args[2]), signed)
        return [
            f"    {destination} = ({left} {operator} {right}) ? "
            f"{_name(str(args[1]))} : {_name(str(args[2]))};"
        ]
    raise ValueError(f"неизвестная IR-инструкция {op}")


def _emit_bank_bridge(
        adapter: CallAdapterSpec, function: FunctionIR, index: int
) -> list[str]:
    try:
        source_registers = adapter_source_registers(adapter)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    lines = [
        f"void {adapter_bridge_name(index)}(void) __naked",
        "{",
        "    __asm",
    ]
    for argument_index in range(len(adapter.arguments) - 1, -1, -1):
        value = adapter.arguments[argument_index]
        register = source_registers[value.symbol].lower()
        if value.kind == "memory_u8":
            lines.extend([
                f"        ld l, {register}",
                "        ld h, #0x00",
            ])
        else:
            assert value.mask is not None and value.equals is not None
            label = f"8{index:02d}{argument_index:02d}$"
            lines.extend([
                "        ld hl, #0x0000",
                f"        ld a, {register}",
                f"        and a, #0x{value.mask:02x}",
                f"        cp a, #0x{value.equals:02x}",
                f"        jr nz, {label}",
                "        inc l",
                f"{label}:",
            ])
        lines.append("        push hl")
    lines.append(f"        call _{function.export}")
    lines.extend("        pop bc" for _ in adapter.arguments)
    lines.extend([
        "        ld a, l",
        "        ret",
        "    __endasm;",
        "}",
        "",
    ])
    return lines


def emit_c(functions: tuple[FunctionIR, ...],
           adapters: tuple[CallAdapterSpec, ...] = ()) -> str:
    lines = [
        "/* Сгенерировано Python AST -> typed IR -> C11. Не редактировать. */",
        "#include <stdint.h>",
        "#if !defined(__SDCC) || (__SDCCCALL != 1)",
        '#error "pyz80_compiler requires SDCC module ABI version 1"',
        "#endif",
        "",
    ]
    for function in functions:
        parameters = ", ".join(
            f"{parameter_c_type(item.type)} pyz80_arg_{item.name}"
            for item in function.parameters
        ) or "void"
        lines.append(
            f"{C_TYPE[function.return_type.name]} {function.export}({parameters}) "
            "__sdcccall(0)")
        lines.append("{")
        parameter_names = {item.name for item in function.parameters}
        for item in function.parameters:
            lines.append(
                f"    {C_TYPE[item.type.name]} {item.name} = "
                f"({C_TYPE[item.type.name]})pyz80_arg_{item.name};")
        for name, value_type in sorted(function.local_types.items()):
            if name not in parameter_names:
                lines.append(f"    {C_TYPE[value_type.name]} {name};")
        declarations: list[tuple[int, str, str]] = []
        for name, value_type in function.temporary_types.items():
            index = int(name[1:])
            instruction = next(
                item for block in function.blocks.values()
                for item in block.instructions if item.destination == name)
            storage = str(instruction.attributes.get("storage_type", value_type.name))
            if storage == "pyint":
                storage = "i16"
            declarations.append((index, C_TYPE[storage], _name(name)))
        for _, c_type, name in sorted(declarations):
            lines.append(f"    {c_type} {name};")
        lines.append("")
        for block_name, block in function.blocks.items():
            lines.append(f"pyz80_{function.export}_{block_name}:")
            for instruction in block.instructions:
                lines.extend(_instruction_lines(instruction))
            term = block.terminator
            assert term is not None
            if term.op == "return":
                lines.append(f"    return {_name(str(term.arguments[0]))};")
            elif term.op == "jump":
                lines.append(
                    f"    goto pyz80_{function.export}_{term.targets[0]};")
            elif term.op == "branch":
                lines.append(
                    f"    if ({_name(str(term.arguments[0]))}) goto "
                    f"pyz80_{function.export}_{term.targets[0]};")
                lines.append(
                    f"    goto pyz80_{function.export}_{term.targets[1]};")
            else:
                raise ValueError(f"неизвестный terminator {term.op}")
        lines.extend(["}", ""])
    by_export = {function.export: function for function in functions}
    for index, adapter in enumerate(adapters):
        lines.extend(_emit_bank_bridge(
            adapter, by_export[adapter.function], index))
    return "\n".join(lines)
