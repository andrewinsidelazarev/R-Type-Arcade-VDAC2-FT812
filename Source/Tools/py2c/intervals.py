"""Интервалы целых значений для выбора разрядности C-типов.

Все значения транслируемого подмножества укладываются в int32 (это проверяет
хост-сборка с контролем переполнения), поэтому интервалы ограничены int32.
"""
from __future__ import annotations

from dataclasses import dataclass

from .ctypes_model import I8, I16, I32, U8, U16, IntType

INT32_MIN = -(1 << 31)
INT32_MAX = (1 << 31) - 1


@dataclass(frozen=True)
class Interval:
    lo: int
    hi: int

    @staticmethod
    def of(value: int) -> 'Interval':
        return Interval(value, value).clamp()

    def clamp(self) -> 'Interval':
        return Interval(max(INT32_MIN, min(self.lo, INT32_MAX)),
                        max(INT32_MIN, min(self.hi, INT32_MAX)))

    def union(self, other: 'Interval | None') -> 'Interval':
        if other is None:
            return self
        return Interval(min(self.lo, other.lo), max(self.hi, other.hi))

    def intersect(self, other: 'Interval') -> 'Interval | None':
        lo, hi = max(self.lo, other.lo), min(self.hi, other.hi)
        return Interval(lo, hi) if lo <= hi else None

    def within(self, lo: int, hi: int) -> bool:
        return lo <= self.lo and self.hi <= hi

    @property
    def nonnegative(self) -> bool:
        return self.lo >= 0

    @property
    def is_top(self) -> bool:
        return self.lo <= INT32_MIN and self.hi >= INT32_MAX


TOP = Interval(INT32_MIN, INT32_MAX)
BOOL_RANGE = Interval(0, 1)


def union_all(items) -> Interval | None:
    result = None
    for item in items:
        if item is None:
            continue
        result = item if result is None else result.union(item)
    return result


HI_STEPS = (0, 1, 127, 255, 32767, 65535, INT32_MAX)
LO_STEPS = (0, -1, -128, -32768, INT32_MIN)


def widen_threshold(interval: Interval) -> Interval:
    """Расширение растущего интервала до ступеней границ C-типов.

    Накопитель с маской остаётся в пределах маски (её учитывает `binary`),
    а неограниченный счётчик за несколько проходов доходит до int32.
    """
    hi = next(step for step in HI_STEPS if step >= interval.hi) if interval.hi <= INT32_MAX else INT32_MAX
    lo = next(step for step in LO_STEPS if step <= interval.lo) if interval.lo >= INT32_MIN else INT32_MIN
    return Interval(lo, hi)


def type_for(interval: Interval | None) -> IntType:
    """Самый узкий C-тип, вмещающий интервал."""
    if interval is None:
        return I32
    for candidate in (U8, I8, U16, I16):
        if candidate.holds(interval.lo) and candidate.holds(interval.hi):
            return candidate
    return I32


def _bit_ceiling(value: int) -> int:
    return (1 << max(0, value.bit_length())) - 1


def binary(op: str, a: Interval, b: Interval, right_constant: int | None = None) -> Interval:
    """Интервал результата двуместной операции Python над целыми."""
    if op == 'Add':
        return Interval(a.lo + b.lo, a.hi + b.hi).clamp()
    if op == 'Sub':
        return Interval(a.lo - b.hi, a.hi - b.lo).clamp()
    if op == 'Mult':
        products = (a.lo * b.lo, a.lo * b.hi, a.hi * b.lo, a.hi * b.hi)
        return Interval(min(products), max(products)).clamp()
    if op == 'FloorDiv':
        if b.lo > 0:
            values = (a.lo // b.lo, a.lo // b.hi, a.hi // b.lo, a.hi // b.hi)
            return Interval(min(values), max(values)).clamp()
        return TOP
    if op == 'Mod':
        if b.lo > 0:
            if a.lo >= 0 and a.hi < b.lo:
                return a
            return Interval(0, b.hi - 1)
        return TOP
    if op == 'BitAnd':
        if a.nonnegative and b.nonnegative:
            return Interval(0, min(a.hi, b.hi))
        if b.nonnegative:
            return Interval(0, b.hi)
        if a.nonnegative:
            return Interval(0, a.hi)
        return TOP
    if op in ('BitOr', 'BitXor'):
        if a.nonnegative and b.nonnegative:
            return Interval(0, _bit_ceiling(max(a.hi, b.hi)))
        return TOP
    if op == 'LShift':
        if right_constant is not None and 0 <= right_constant < 32:
            return Interval(a.lo << right_constant, a.hi << right_constant).clamp()
        return TOP
    if op == 'RShift':
        if right_constant is not None and right_constant >= 0:
            shift = min(right_constant, 31)
            return Interval(a.lo >> shift, a.hi >> shift)
        if b.nonnegative:
            return Interval(min(a.lo, 0), max(a.hi, 0)) if a.lo < 0 else Interval(0, a.hi)
        return TOP
    return TOP


def refine_compare(op: str, value: Interval, other: Interval) -> Interval | None:
    """Уточнение интервала левого операнда при истинном сравнении `value op other`."""
    if op == 'Lt':
        return value.intersect(Interval(INT32_MIN, other.hi - 1))
    if op == 'LtE':
        return value.intersect(Interval(INT32_MIN, other.hi))
    if op == 'Gt':
        return value.intersect(Interval(other.lo + 1, INT32_MAX))
    if op == 'GtE':
        return value.intersect(Interval(other.lo, INT32_MAX))
    if op == 'Eq':
        return value.intersect(other)
    return value


NEGATED = {'Lt': 'GtE', 'LtE': 'Gt', 'Gt': 'LtE', 'GtE': 'Lt', 'Eq': 'NotEq', 'NotEq': 'Eq'}
SWAPPED = {'Lt': 'Gt', 'LtE': 'GtE', 'Gt': 'Lt', 'GtE': 'LtE', 'Eq': 'Eq', 'NotEq': 'NotEq'}
