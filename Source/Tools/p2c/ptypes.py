"""Решётка типов анализа и целочисленные C-типы.

Значение анализа описывает форму значения Python (целое с интервалом, строка,
объект класса, контейнер, кортеж, Optional, вызываемое) и уточняется до
неподвижной точки объединением всех потоков значений в ячейку (параметр,
локальная переменная, поле, элемент контейнера, результат функции).
"""
from __future__ import annotations

from dataclasses import dataclass

from .intervals import INT32_MAX, INT32_MIN, Interval


# --- целочисленные C-типы ----------------------------------------------------

@dataclass(frozen=True)
class CInt:
    bits: int
    signed: bool

    def c(self) -> str:
        return f'{"" if self.signed else "u"}int{self.bits}_t'

    def key(self) -> str:
        return f'{"i" if self.signed else "u"}{self.bits}'

    @property
    def minimum(self) -> int:
        return -(1 << (self.bits - 1)) if self.signed else 0

    @property
    def maximum(self) -> int:
        return (1 << (self.bits - 1)) - 1 if self.signed else (1 << self.bits) - 1

    def holds(self, value: int) -> bool:
        return self.minimum <= value <= self.maximum

    def interval(self) -> Interval:
        return Interval(self.minimum, self.maximum)


U8 = CInt(8, False)
I8 = CInt(8, True)
U16 = CInt(16, False)
I16 = CInt(16, True)
I32 = CInt(32, True)
CINTS = (U8, I8, U16, I16, I32)


def cint_for(interval: Interval | None) -> CInt:
    """Самый узкий C-тип, вмещающий интервал (неизвестный — int32)."""
    if interval is None:
        return I32
    for candidate in CINTS:
        if candidate.holds(interval.lo) and candidate.holds(interval.hi):
            return candidate
    return I32


# --- значения анализа ----------------------------------------------------------

class T:
    """Базовый класс формы значения."""

    def key(self) -> str:
        raise NotImplementedError


@dataclass(frozen=True)
class BottomT(T):
    """Ещё нет ни одного потока значения."""

    def key(self) -> str:
        return 'bottom'


@dataclass(frozen=True)
class IntT(T):
    lo: int
    hi: int

    @property
    def interval(self) -> Interval:
        return Interval(self.lo, self.hi)

    def key(self) -> str:
        return cint_for(self.interval).key()

    @staticmethod
    def of(interval: Interval) -> 'IntT':
        return IntT(interval.lo, interval.hi)


INT_TOP = IntT(INT32_MIN, INT32_MAX)


@dataclass(frozen=True)
class BoolT(T):
    """bool; value — известное значение всех потоков (распространение констант)."""

    value: bool | None = None

    def key(self) -> str:
        return 'bool'


@dataclass(frozen=True)
class NoneT(T):
    def key(self) -> str:
        return 'none'


@dataclass(frozen=True)
class StrT(T):
    """Строка; max_len — наибольшая длина в байтах по всем потокам (65535 — неизвестна). C-тип от длины
    не зависит; длина ограничивает интервал len() и счётчика enumerate."""

    max_len: int = 65535

    def key(self) -> str:
        return 'str'


@dataclass(frozen=True)
class ObjT(T):
    """Экземпляр класса пакета или его подкласса (ссылка)."""

    cls: str

    def key(self) -> str:
        return f'o{self.cls}'


@dataclass(frozen=True)
class ValT(T):
    """Неизменяемый dataclass или pygame.Rect: структура по значению."""

    cls: str

    def key(self) -> str:
        return f'v{self.cls}'


@dataclass(frozen=True)
class TupleT(T):
    items: tuple

    def key(self) -> str:
        return 't' + str(len(self.items)) + '_' + '_'.join(item.key() for item in self.items) + '_e'


@dataclass(frozen=True)
class ListT(T):
    elem: T

    def key(self) -> str:
        return f'l_{self.elem.key()}'


@dataclass(frozen=True)
class ArrayT(T):
    """Неизменяемый кортеж переменной длины tuple[T, ...]."""

    elem: T

    def key(self) -> str:
        return f'a_{self.elem.key()}'


@dataclass(frozen=True)
class DequeT(T):
    elem: T

    def key(self) -> str:
        return f'q_{self.elem.key()}'


@dataclass(frozen=True)
class DictT(T):
    k: T
    v: T

    def key(self) -> str:
        return f'd_{self.k.key()}_{self.v.key()}_e'


@dataclass(frozen=True)
class SetT(T):
    elem: T

    def key(self) -> str:
        return f's_{self.elem.key()}'


@dataclass(frozen=True)
class BytesT(T):
    mutable: bool

    def key(self) -> str:
        return 'buf'


@dataclass(frozen=True)
class OptT(T):
    inner: T

    def key(self) -> str:
        return f'n_{self.inner.key()}'


@dataclass(frozen=True)
class FnT(T):
    """Вызываемое значение; ids — номера возможных целей по потокам значений."""

    params: tuple
    ret: T
    ids: frozenset = frozenset()

    def key(self) -> str:
        return 'f' + str(len(self.params))


@dataclass(frozen=True)
class ImageT(T):
    def key(self) -> str:
        return 'img'


@dataclass(frozen=True)
class TargetT(T):
    def key(self) -> str:
        return 'target'


@dataclass(frozen=True)
class FontT(T):
    def key(self) -> str:
        return 'font'


@dataclass(frozen=True)
class ExtT(T):
    """Объект платформы (звук): методы — вызовы адаптера."""

    name: str

    def key(self) -> str:
        return f'x{self.name}'


@dataclass(frozen=True)
class VoidT(T):
    def key(self) -> str:
        return 'void'


BOTTOM = BottomT()
BOOL = BoolT()
NONE = NoneT()
STR = StrT()
IMAGE = ImageT()
TARGET = TargetT()
FONT = FontT()
VOID = VoidT()


def is_bottom(value: T) -> bool:
    return isinstance(value, BottomT)


def contains_bottom(value: T) -> bool:
    if isinstance(value, BottomT):
        return True
    if isinstance(value, (ListT, ArrayT, DequeT, SetT)):
        return contains_bottom(value.elem)
    if isinstance(value, DictT):
        return contains_bottom(value.k) or contains_bottom(value.v)
    if isinstance(value, TupleT):
        return any(contains_bottom(item) for item in value.items)
    if isinstance(value, OptT):
        return contains_bottom(value.inner)
    if isinstance(value, FnT):
        return any(contains_bottom(item) for item in value.params) or contains_bottom(value.ret)
    return False


def is_pointer(value: T) -> bool:
    """Представление — указатель (None кодируется NULL)."""
    return isinstance(value, (ObjT, ListT, ArrayT, DequeT, DictT, SetT, BytesT, StrT))


def is_int_like(value: T) -> bool:
    return isinstance(value, (IntT, BoolT))


def optional_inner(value: T) -> T:
    return value.inner if isinstance(value, OptT) else value


def has_references(value: T) -> bool:
    """Содержит ли значение ссылки на объекты кучи (нужна разметка сборщика)."""
    if is_pointer(value):
        return True
    if isinstance(value, TupleT):
        return any(has_references(item) for item in value.items)
    if isinstance(value, OptT):
        return has_references(value.inner)
    if isinstance(value, FnT):
        return True
    return False
