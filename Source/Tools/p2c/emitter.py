"""Транслятор одной функции: объединение частей (выражения, вызовы, инструкции)."""
from __future__ import annotations

from .fn_base import EmitterBase
from .fn_builtins import BuiltinsMixin
from .fn_call import CallMixin
from .fn_containers import ContainerMixin
from .fn_expr import ExprMixin
from .fn_stmt import StmtMixin


class FunctionEmitter(StmtMixin, CallMixin, BuiltinsMixin, ContainerMixin, ExprMixin, EmitterBase):
    """Анализ (emit=False) или генерация C (emit=True) одной функции."""
