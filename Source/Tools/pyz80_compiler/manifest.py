"""Машинно-читаемый контракт исходных функций и целевой платформы."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

from .diagnostics import Diagnostic, CompileError
from .types import ScalarType, parse_type


@dataclass(frozen=True)
class ParameterSpec:
    name: str
    type: ScalarType
    minimum: int
    maximum: int

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "ParameterSpec":
        value_type = parse_type(str(data["type"]))
        minimum = int(data["minimum"])
        maximum = int(data["maximum"])
        if minimum > maximum or not value_type.accepts(minimum, maximum):
            raise CompileError(Diagnostic(
                "PZ1101",
                f"диапазон параметра {data.get('name')!r} не помещается в "
                f"{value_type.name}",
            ))
        return cls(str(data["name"]), value_type, minimum, maximum)


@dataclass(frozen=True)
class FunctionSpec:
    symbol: str
    export: str
    parameters: tuple[ParameterSpec, ...]
    return_type: ScalarType
    exhaustive: bool

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "FunctionSpec":
        return cls(
            symbol=str(data["symbol"]),
            export=str(data["export"]),
            parameters=tuple(ParameterSpec.from_json(item)
                             for item in data.get("parameters", ())),
            return_type=parse_type(str(data["return"])),
            exhaustive=bool(data.get("exhaustive", False)),
        )


@dataclass(frozen=True)
class AdapterValueSpec:
    kind: str
    symbol: str
    mask: int | None = None
    equals: int | None = None

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "AdapterValueSpec":
        kind = str(data["kind"])
        if kind not in ("memory_u8", "masked_equals_bool"):
            raise CompileError(Diagnostic(
                "PZ1110", f"неподдержанный adapter value kind {kind!r}"))
        symbol = str(data["symbol"])
        mask = int(data["mask"]) if "mask" in data else None
        equals = int(data["equals"]) if "equals" in data else None
        if kind == "masked_equals_bool" and (mask is None or equals is None):
            raise CompileError(Diagnostic(
                "PZ1111", "masked_equals_bool требует mask и equals"))
        if mask is not None and not 0 <= mask <= 0xFF:
            raise CompileError(Diagnostic(
                "PZ1114", "adapter mask должен помещаться в байт"))
        if equals is not None and not 0 <= equals <= 0xFF:
            raise CompileError(Diagnostic(
                "PZ1115", "adapter equals должен помещаться в байт"))
        return cls(kind=kind, symbol=symbol, mask=mask, equals=equals)


@dataclass(frozen=True)
class CallAdapterSpec:
    entry: str
    function: str
    arguments: tuple[AdapterValueSpec, ...]
    result: AdapterValueSpec

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "CallAdapterSpec":
        return cls(
            entry=str(data["entry"]),
            function=str(data["function"]),
            arguments=tuple(AdapterValueSpec.from_json(item)
                            for item in data.get("arguments", ())),
            result=AdapterValueSpec.from_json(data["result"]),
        )


@dataclass(frozen=True)
class FT812TargetSpec:
    """Physical video mode and conservative FT812 resource budgets."""

    mode: str
    width: int
    height: int
    hcycle: int
    pclk: int
    safety_utilization: float
    ram_dl_word_limit: int
    cmd_fifo_bytes: int
    cmd_fifo_usable: int

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "FT812TargetSpec":
        integer_names = (
            "width",
            "height",
            "hcycle",
            "pclk",
            "ram_dl_word_limit",
            "cmd_fifo_bytes",
            "cmd_fifo_usable",
        )
        values: dict[str, int] = {}
        for name in integer_names:
            value = data.get(name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise CompileError(Diagnostic(
                    "PZ1120", f"target.ft812.{name} должен быть целым > 0"))
            values[name] = value

        utilization = data.get("safety_utilization")
        if (
            not isinstance(utilization, (int, float))
            or isinstance(utilization, bool)
            or not math.isfinite(float(utilization))
            or not 0 < float(utilization) <= 1
        ):
            raise CompileError(Diagnostic(
                "PZ1121",
                "target.ft812.safety_utilization должен быть в интервале (0, 1]",
            ))
        if values["ram_dl_word_limit"] > 2048:
            raise CompileError(Diagnostic(
                "PZ1122", "FT812 RAM_DL вмещает не более 2048 слов"))
        fifo_bytes = values["cmd_fifo_bytes"]
        if fifo_bytes > 4096 or fifo_bytes & (fifo_bytes - 1):
            raise CompileError(Diagnostic(
                "PZ1123",
                "FT812 RAM_CMD должен быть степенью двух не больше 4096 байт",
            ))
        fifo_usable = values["cmd_fifo_usable"]
        if fifo_usable > fifo_bytes - 4 or fifo_usable % 4:
            raise CompileError(Diagnostic(
                "PZ1124",
                "полезный RAM_CMD должен быть кратен 4 и оставлять одну "
                "4-байтную ячейку свободной",
            ))

        mode = str(data.get("mode", "")).strip()
        if not mode:
            raise CompileError(Diagnostic(
                "PZ1125", "target.ft812.mode не должен быть пустым"))
        return cls(
            mode=mode,
            safety_utilization=float(utilization),
            **values,
        )

    @property
    def line_cycles(self) -> int:
        """Theoretical physical limit for one scanline."""
        return self.hcycle * self.pclk

    @property
    def safe_line_cycles(self) -> int:
        """Accepted line limit after the configured practical margin."""
        utilization = Fraction(str(self.safety_utilization))
        return (
            self.line_cycles * utilization.numerator
            // utilization.denominator
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "width": self.width,
            "height": self.height,
            "hcycle": self.hcycle,
            "pclk": self.pclk,
            "line_cycles": self.line_cycles,
            "safety_utilization": self.safety_utilization,
            "safe_line_cycles": self.safe_line_cycles,
            "ram_dl_word_limit": self.ram_dl_word_limit,
            "cmd_fifo_bytes": self.cmd_fifo_bytes,
            "cmd_fifo_usable": self.cmd_fifo_usable,
        }


@dataclass(frozen=True)
class TargetSpec:
    cpu: str
    backend: str
    toolchain_kind: str
    toolchain_version: str
    toolchain_sha256: str
    origin: int
    bank_size: int
    code_pages: tuple[int, ...]
    stack_budget: int
    isr_reserve: int
    ft812: FT812TargetSpec | None = None

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "TargetSpec":
        pages = tuple(int(value) for value in data["code_pages"])
        if not pages or len(set(pages)) != len(pages):
            raise CompileError(Diagnostic(
                "PZ1102", "список code_pages пуст или содержит повторы"))
        if any(not 0 <= page <= 0xFF for page in pages):
            raise CompileError(Diagnostic(
                "PZ1103", "номер code page должен помещаться в байт"))
        return cls(
            cpu=str(data["cpu"]),
            backend=str(data["backend"]),
            toolchain_kind=str(data["toolchain"]["kind"]),
            toolchain_version=str(data["toolchain"]["version"]),
            toolchain_sha256=str(data["toolchain"]["sha256"]).upper(),
            origin=int(data["origin"]),
            bank_size=int(data["bank_size"]),
            code_pages=pages,
            stack_budget=int(data["stack_budget"]),
            isr_reserve=int(data.get("isr_reserve", 0)),
            ft812=(
                FT812TargetSpec.from_json(data["ft812"])
                if "ft812" in data else None
            ),
        )


@dataclass(frozen=True)
class CompilerManifest:
    format: str
    target: TargetSpec
    functions: tuple[FunctionSpec, ...]
    call_adapters: tuple[CallAdapterSpec, ...]

    @classmethod
    def load(cls, path: Path) -> "CompilerManifest":
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("format") != "pyz80-compiler-v1":
            raise CompileError(Diagnostic(
                "PZ1104", "неподдерживаемый формат compiler manifest"))
        functions = tuple(FunctionSpec.from_json(item)
                          for item in data.get("functions", ()))
        symbols = [item.symbol for item in functions]
        exports = [item.export for item in functions]
        if not functions or len(set(symbols)) != len(symbols):
            raise CompileError(Diagnostic(
                "PZ1105", "functions пуст или содержит повторные symbols"))
        if len(set(exports)) != len(exports):
            raise CompileError(Diagnostic(
                "PZ1106", "functions содержит повторные exports"))
        adapters = tuple(CallAdapterSpec.from_json(item)
                         for item in data.get("call_adapters", ()))
        entries = [item.entry for item in adapters]
        if len(set(entries)) != len(entries):
            raise CompileError(Diagnostic(
                "PZ1112", "call_adapters содержит повторные entries"))
        unknown = sorted({item.function for item in adapters} - set(exports))
        if unknown:
            raise CompileError(Diagnostic(
                "PZ1113", "call_adapters ссылается на неизвестные exports: "
                + ", ".join(unknown)))
        return cls(
            format=str(data["format"]),
            target=TargetSpec.from_json(data["target"]),
            functions=functions,
            call_adapters=adapters,
        )
