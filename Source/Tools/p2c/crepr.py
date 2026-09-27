"""C-представление форм анализа: имена типов, структуры кортежей и Optional."""
from __future__ import annotations

from .errors import TranslationError
from .ptypes import (
    ArrayT, BoolT, BottomT, BytesT, CInt, DequeT, DictT, ExtT, FnT, FontT, I32, ImageT, IntT, ListT,
    NoneT, ObjT, OptT, SetT, StrT, T, TargetT, TupleT, U8, ValT, VoidT, cint_for, is_pointer,
)


class CRepr:
    """Реестр производных C-типов (кортежи, Optional-значения) для генерации."""

    def __init__(self, compiler) -> None:
        self.compiler = compiler
        self.tuples: dict[T, str] = {}
        self.opts: dict[T, str] = {}
        self.order: list[tuple[str, T]] = []

    def cint(self, value: T) -> CInt:
        if isinstance(value, BoolT):
            return U8
        if isinstance(value, IntT):
            if value.lo > value.hi:
                return I32
            return cint_for(value.interval)
        raise TranslationError(f'ожидалось целое, есть {value}')

    def ctype(self, value: T) -> str:
        if isinstance(value, IntT):
            return self.cint(value).c()
        if isinstance(value, BoolT):
            return 'uint8_t'
        if isinstance(value, StrT):
            return 'const P2cStr *'
        if isinstance(value, ObjT):
            if value.cls == '*':
                return 'P2cObject *'
            return f'P2cC_{self.compiler.program.root(value.cls)} *'
        if isinstance(value, ValT):
            return 'P2cRect' if value.cls == 'Rect' else f'P2cV_{value.cls}'
        if isinstance(value, TupleT):
            return self.tuple_name(value)
        if isinstance(value, ListT):
            return 'P2cList *'
        if isinstance(value, ArrayT):
            return 'P2cArray *'
        if isinstance(value, DequeT):
            return 'P2cDeque *'
        if isinstance(value, DictT):
            return 'P2cDict *'
        if isinstance(value, SetT):
            return 'P2cSet *'
        if isinstance(value, BytesT):
            return 'P2cBuf *'
        if isinstance(value, OptT):
            inner = value.inner
            if is_pointer(inner) or isinstance(inner, FnT):
                return self.ctype(inner)
            return self.opt_name(value)
        if isinstance(value, FnT):
            return 'P2cFn'
        if isinstance(value, ImageT):
            return 'P2cImage'
        if isinstance(value, (TargetT, FontT, ExtT)):
            return 'P2cHandle'
        if isinstance(value, VoidT):
            return 'void'
        if isinstance(value, NoneT):
            return 'uint8_t'
        if isinstance(value, BottomT):
            raise TranslationError('тип значения не выведен (нет ни одного потока)')
        raise TranslationError(f'нет C-представления для {value}')

    def normalized(self, value: T) -> T:
        """Форма, по которой различаются C-структуры (ширина целых — по C-типу)."""
        if isinstance(value, IntT):
            cint = self.cint(value)
            return IntT(cint.minimum, cint.maximum)
        if isinstance(value, TupleT):
            return TupleT(tuple(self.normalized(item) for item in value.items))
        if isinstance(value, OptT):
            return OptT(self.normalized(value.inner))
        if isinstance(value, (ListT, ArrayT, DequeT, SetT)):
            return type(value)(self.normalized(value.elem))
        if isinstance(value, DictT):
            return DictT(self.normalized(value.k), self.normalized(value.v))
        if isinstance(value, FnT):
            return FnT((), BottomT())
        return value

    def tuple_name(self, value: TupleT) -> str:
        key = self.normalized(value)
        if key not in self.tuples:
            for item in key.items:
                self.ctype(item)
            name = f'P2cT{len(self.tuples) + 1}'
            self.tuples[key] = name
            self.order.append((name, key))
        return self.tuples[key]

    def opt_name(self, value: OptT) -> str:
        key = self.normalized(value)
        if key not in self.opts:
            self.ctype(key.inner)
            name = f'P2cN{len(self.opts) + 1}'
            self.opts[key] = name
            self.order.append((name, key))
        return self.opts[key]

    def typedefs(self) -> list[str]:
        """Объявления структур кортежей и Optional в порядке зависимостей."""
        lines = []
        for name, value in self.order:
            if isinstance(value, TupleT):
                members = ' '.join(f'{self.ctype(item)} v{index};' for index, item in enumerate(value.items))
                lines.append(f'typedef struct {{ {members} }} {name};')
            else:
                lines.append(f'typedef struct {{ uint8_t has; {self.ctype(value.inner)} v; }} {name};')
        return lines
