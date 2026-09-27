"""Аннотации Python -> формы анализа (целые без интервала, интервал дают потоки)."""
from __future__ import annotations

import ast

from .errors import TranslationError
from .intervals import INT32_MAX, INT32_MIN
from .ptypes import (
    BOOL, BOTTOM, FONT, IMAGE, NONE, STR, TARGET, VOID, ArrayT, BytesT, DequeT, DictT, FnT,
    IntT, ListT, ObjT, OptT, SetT, T, TupleT, ValT,
)

INT_EMPTY = IntT(INT32_MAX, INT32_MIN)
WIDTHS = {'U8': IntT(0, 255), 'I8': IntT(-128, 127), 'U16': IntT(0, 65535),
          'I16': IntT(-32768, 32767), 'I32': IntT(INT32_MIN, INT32_MAX)}


def parse_annotation(compiler, node: ast.expr, module: str, filename: str) -> T:
    """Форма значения по аннотации; None — аннотация не задаёт форму однозначно."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return parse_annotation(compiler, ast.parse(node.value, mode='eval').body, module, filename)
    if isinstance(node, ast.Constant) and node.value is None:
        return NONE
    text = ast.unparse(node)
    if text == 'int':
        return INT_EMPTY
    if text in WIDTHS:
        return WIDTHS[text]
    if text == 'bool':
        return BOOL
    if text == 'str':
        return STR
    if text == 'bytes':
        return BytesT(False)
    if text == 'bytearray':
        return BytesT(True)
    if text == 'bytes | bytearray':
        return BytesT(False)
    if text == 'pygame.Surface':
        return IMAGE
    if text == 'pygame.Rect':
        return ValT('Rect')
    if text in ('pygame.font.Font',):
        return FONT
    if text == 'object':
        return ObjT('*')
    program = compiler.program
    if isinstance(node, ast.Name) and node.id in program.classes:
        info = program.classes[node.id]
        return ValT(info.name) if info.frozen else ObjT(info.name)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        left = parse_annotation(compiler, node.left, module, filename)
        right = parse_annotation(compiler, node.right, module, filename)
        if left == NONE:
            return right if isinstance(right, OptT) else OptT(right)
        if right == NONE:
            return left if isinstance(left, OptT) else OptT(left)
        # Объединение контейнеров разного вида форму не задаёт: её дают потоки.
        return BOTTOM
    if isinstance(node, ast.Subscript):
        container = ast.unparse(node.value)
        argument = node.slice
        if container in ('list', 'Sequence', 'Iterable'):
            element = parse_annotation(compiler, argument, module, filename)
            return ListT(element) if container == 'list' else BOTTOM
        if container == 'deque':
            return DequeT(parse_annotation(compiler, argument, module, filename))
        if container in ('set', 'frozenset'):
            return SetT(parse_annotation(compiler, argument, module, filename))
        if container == 'dict':
            if not isinstance(argument, ast.Tuple) or len(argument.elts) != 2:
                raise TranslationError(f'аннотация «{text}» не поддержана', node, filename)
            return DictT(parse_annotation(compiler, argument.elts[0], module, filename),
                         parse_annotation(compiler, argument.elts[1], module, filename))
        if container == 'tuple':
            if (isinstance(argument, ast.Tuple) and len(argument.elts) == 2 and
                    isinstance(argument.elts[1], ast.Constant) and argument.elts[1].value is Ellipsis):
                return ArrayT(parse_annotation(compiler, argument.elts[0], module, filename))
            items = argument.elts if isinstance(argument, ast.Tuple) else [argument]
            return TupleT(tuple(parse_annotation(compiler, item, module, filename) for item in items))
        if container == 'Callable':
            if not isinstance(argument, ast.Tuple) or len(argument.elts) != 2:
                raise TranslationError(f'аннотация «{text}» не поддержана', node, filename)
            params, result = argument.elts
            if not isinstance(params, ast.List):
                raise TranslationError(f'аннотация «{text}» не поддержана', node, filename)
            returns = parse_annotation(compiler, result, module, filename)
            return FnT(tuple(parse_annotation(compiler, item, module, filename) for item in params.elts),
                       VOID if returns == NONE else returns)
    raise TranslationError(f'аннотация «{text}» не поддержана', node, filename)
