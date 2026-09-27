"""Типы и конечные диапазоны статического Python-подмножества."""

from __future__ import annotations

from dataclasses import dataclass

from .diagnostics import fail


@dataclass(frozen=True, order=True)
class ScalarType:
    """Скалярный тип IR; ``pyint`` легализуется после анализа диапазонов."""

    name: str
    bits: int | None
    signed: bool
    boolean: bool = False

    @property
    def minimum(self) -> int | None:
        if self.boolean:
            return 0
        if self.bits is None:
            return None
        return -(1 << (self.bits - 1)) if self.signed else 0

    @property
    def maximum(self) -> int | None:
        if self.boolean:
            return 1
        if self.bits is None:
            return None
        return ((1 << (self.bits - 1)) - 1
                if self.signed else (1 << self.bits) - 1)

    def accepts(self, minimum: int, maximum: int) -> bool:
        own_minimum = self.minimum
        own_maximum = self.maximum
        return (own_minimum is None or
                (minimum >= own_minimum and maximum <= own_maximum))


BOOL = ScalarType("bool", 8, False, True)
PYINT = ScalarType("pyint", None, True)
U8 = ScalarType("u8", 8, False)
I8 = ScalarType("i8", 8, True)
U16 = ScalarType("u16", 16, False)
I16 = ScalarType("i16", 16, True)
U32 = ScalarType("u32", 32, False)
I32 = ScalarType("i32", 32, True)
VOID = ScalarType("void", 0, False)

TYPE_BY_NAME = {
    item.name: item
    for item in (BOOL, PYINT, U8, I8, U16, I16, U32, I32, VOID)
}


def parse_type(name: str) -> ScalarType:
    try:
        return TYPE_BY_NAME[name]
    except KeyError:
        fail("PZ1001", f"неизвестный скалярный тип {name!r}")


@dataclass(frozen=True)
class Interval:
    """Замкнутый диапазон целого значения."""

    minimum: int
    maximum: int

    def __post_init__(self) -> None:
        if self.minimum > self.maximum:
            raise ValueError("пустой диапазон")

    def union(self, other: "Interval") -> "Interval":
        return Interval(min(self.minimum, other.minimum),
                        max(self.maximum, other.maximum))

    def add(self, other: "Interval") -> "Interval":
        return Interval(self.minimum + other.minimum,
                        self.maximum + other.maximum)

    def subtract(self, other: "Interval") -> "Interval":
        return Interval(self.minimum - other.maximum,
                        self.maximum - other.minimum)

    def multiply(self, other: "Interval") -> "Interval":
        products = (
            self.minimum * other.minimum,
            self.minimum * other.maximum,
            self.maximum * other.minimum,
            self.maximum * other.maximum,
        )
        return Interval(min(products), max(products))


def storage_type(interval: Interval) -> ScalarType:
    """Выбрать минимальный явный тип без изменения Python-значений."""
    for candidate in (U8, I8, U16, I16, U32, I32):
        if candidate.accepts(interval.minimum, interval.maximum):
            return candidate
    fail(
        "PZ1002",
        f"диапазон {interval.minimum}…{interval.maximum} шире 32 бит",
    )
