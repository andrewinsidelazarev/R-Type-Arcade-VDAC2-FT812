"""Модель C-типов транслятора."""
from __future__ import annotations

from dataclasses import dataclass


class TranslationError(Exception):
    """Конструкция вне поддержанного подмножества или противоречие типов."""

    def __init__(self, message: str, node: object | None = None,
                 filename: str | None = None) -> None:
        line = getattr(node, 'lineno', None)
        where = f'{filename or "?"}:{line}' if line is not None else (filename or '')
        super().__init__(f'{where}: {message}' if where else message)


@dataclass(frozen=True)
class CType:
    """Базовый тип значения."""

    def c(self) -> str:
        raise NotImplementedError

    def key(self) -> str:
        """Имя для производных C-идентификаторов."""
        raise NotImplementedError


@dataclass(frozen=True)
class IntType(CType):
    bits: int = 32
    signed: bool = True

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


I32 = IntType(32, True)
I16 = IntType(16, True)
U16 = IntType(16, False)
I8 = IntType(8, True)
U8 = IntType(8, False)

WIDTH_ALIASES = {'U8': U8, 'I8': I8, 'U16': U16, 'I16': I16, 'I32': I32}


def narrowest_int(values) -> IntType:
    """Самый узкий тип, вмещающий все значения неизменяемого набора."""
    low = min(values, default=0)
    high = max(values, default=0)
    for candidate in (U8, I8, U16, I16, I32):
        if candidate.holds(low) and candidate.holds(high):
            return candidate
    raise TranslationError(f'значения {low}…{high} не помещаются в int32')


@dataclass(frozen=True)
class BoolType(CType):
    def c(self) -> str:
        return 'uint8_t'

    def key(self) -> str:
        return 'bool'


@dataclass(frozen=True)
class OptionalIntType(CType):
    """`int | None`: значение и отдельный признак присутствия."""

    def c(self) -> str:
        return 'Py2cOptI32'

    def key(self) -> str:
        return 'opti32'


@dataclass(frozen=True)
class ClassType(CType):
    name: str

    def c(self) -> str:
        return f'{self.name} *'

    def key(self) -> str:
        return self.name


@dataclass(frozen=True)
class BufferType(CType):
    """bytes/bytearray: страничный буфер байтов."""

    mutable: bool

    def c(self) -> str:
        return 'Py2cBuffer *'

    def key(self) -> str:
        return 'buf'


@dataclass(frozen=True)
class ImageType(CType):
    """pygame.Surface в игровых данных: номер ресурса изображения."""

    def c(self) -> str:
        return 'uint16_t'

    def key(self) -> str:
        return 'img'


@dataclass(frozen=True)
class TargetType(CType):
    """Цель отрисовки: вызовы уходят в аппаратный адаптер."""

    def c(self) -> str:
        return 'void *'

    def key(self) -> str:
        return 'target'


@dataclass(frozen=True)
class ArrayType(CType):
    """tuple/list однородных элементов фиксированной или ограниченной длины."""

    element: CType
    mutable: bool = False

    def struct_name(self) -> str:
        return f'Py2cArray_{self.element.key()}'

    def c(self) -> str:
        return f'{self.struct_name()} *'

    def key(self) -> str:
        return f'arr_{self.element.key()}'

    def element_c(self) -> str:
        if isinstance(self.element, ClassType):
            return f'{self.element.name} *'
        return self.element.c()


@dataclass(frozen=True)
class TupleType(CType):
    """Небольшой разнородный кортеж локального значения или результата."""

    elements: tuple[CType, ...]

    def c(self) -> str:
        return f'Py2cTuple_{self.key()}'

    def key(self) -> str:
        return 't_' + '_'.join(element.key() for element in self.elements)


@dataclass(frozen=True)
class VoidType(CType):
    def c(self) -> str:
        return 'void'

    def key(self) -> str:
        return 'void'


BOOL = BoolType()
OPT_INT = OptionalIntType()
IMAGE = ImageType()
TARGET = TargetType()
VOID = VoidType()


def is_int_like(value_type: CType) -> bool:
    return isinstance(value_type, (IntType, BoolType))


def unify(left: CType, right: CType, node: object = None) -> CType:
    """Общий тип двух присваиваний одной переменной."""
    if left == right:
        return left
    if is_int_like(left) and is_int_like(right):
        if isinstance(left, BoolType) and isinstance(right, BoolType):
            return BOOL
        return I32
    if isinstance(left, ArrayType) and isinstance(right, ArrayType):
        if left.element == right.element:
            return ArrayType(left.element, left.mutable or right.mutable)
    raise TranslationError(f'несовместимые типы {left} и {right}', node)
