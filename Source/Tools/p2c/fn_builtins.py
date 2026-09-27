"""Встроенные функции Python, методы контейнеров, struct, pygame, итерация."""
from __future__ import annotations

import ast
import math
import struct as struct_module

from .compiler import INT_EMPTY, describe, int_empty
from .fn_base import NO_CONST, Unknown, Value, cname
from .intervals import BOOL_RANGE, INT32_MAX, TOP, Interval
from .ptypes import (
    BOOL, BOTTOM, I16, I32, IMAGE, INT_TOP, NONE, STR, U16, U8, VOID, ArrayT, BoolT, BottomT,
    BytesT, CInt, DequeT, DictT, FnT, FontT, ImageT, IntT, ListT, NoneT, ObjT, OptT, SetT, StrT, T,
    TargetT, TupleT, ValT, VoidT, cint_for, contains_bottom, is_int_like, is_pointer,
)

ORDER_FREE_CONSUMERS = {'sorted', 'sum', 'any', 'all', 'min', 'max', 'len', 'set', 'frozenset'}


class Loop:
    """Открытый C-цикл итерации: элемент и закрытие; bound — наибольшее число шагов (None — не известно)."""

    def __init__(self, element: Value, close_lines: int, index: str | None = None, bound: int | None = None) -> None:
        self.element = element
        self.close_lines = close_lines
        self.index = index
        self.bound = bound


class BuiltinsMixin:
    # --- материализация ссылок на функции ------------------------------------------

    def materialize(self, value: Value, node: ast.AST) -> Value:
        meta = value.meta
        if meta is None:
            return value
        kind = meta[0]
        if kind == 'bound':
            return self.bound_method_value(meta[1], meta[2], node)
        if kind == 'nested':
            plan = self.c.request_nested(self.plan, meta[1])
            return self.function_value(plan, node)
        if kind == 'function':
            plan = self.c.request_function(meta[1], meta[2], node, self.plan.filename)
            number = self.c.fn_value(('function', plan.key), plan)
            plan.fn_id = number
            t = FnT(tuple(param.t for param in plan.params), plan.ret, frozenset({number}))
            if not self.emit:
                return Value(t, 'p2c_fn')
            return Value(t, self.fn_make(t, self.c.layout.fn_id_symbol(number), 'NULL'))
        if kind == 'method' and isinstance(meta[1].t, (TargetT, FontT)):
            raise self.error(f'метод платформы {meta[2]} как значение не поддержан', node)
        raise self.error(f'{kind} как значение не поддержано', node)

    def value_expr(self, node: ast.expr) -> Value:
        return self.materialize(self.expr(node), node)

    # --- встроенные функции ------------------------------------------------------

    def call_builtin(self, name: str, node: ast.Call) -> Value:
        handler = getattr(self, 'builtin_' + name, None)
        if handler is None:
            raise self.error(f'встроенная функция {name} не поддержана', node)
        if node.keywords and name not in ('sorted', 'min', 'max', 'next', 'getattr', 'round'):
            raise self.error(f'{name}() с именованными аргументами не поддержана', node)
        return handler(node)

    def one_argument(self, node: ast.Call) -> Value:
        if len(node.args) != 1:
            raise self.error(f'{ast.unparse(node.func)} ожидает один аргумент', node)
        return self.value_expr(node.args[0])

    def builtin_len(self, node: ast.Call) -> Value:
        argument = node.args[0] if len(node.args) == 1 else None
        if (isinstance(argument, ast.Call) and isinstance(argument.func, ast.Attribute) and
                argument.func.attr == 'replace' and len(argument.args) == 2 and not argument.keywords and
                isinstance(argument.args[1], ast.Constant) and argument.args[1].value == ''):
            # len(s.replace(old, "")): длина без вхождений old, строка не создаётся (куча и сборка мусора).
            owner = self.value_expr(argument.func.value)
            mark = self.mark()
            old = self.value_expr(argument.args[0])
            self.fix_left([owner], mark)
            if isinstance(owner.t, StrT) and isinstance(old.t, StrT):
                return Value(IntT(0, 65535), f'p2c_str_len_without({owner.code}, {old.code})', U16)
            if self.incomplete(owner.t) or self.incomplete(old.t):
                raise self.unknown(node)
            raise self.error(f'replace у {describe(owner.t)} не поддержан', node)
        value = self.one_argument(node)
        t = value.t
        if self.incomplete(t):
            raise self.unknown(node)
        if isinstance(t, OptT):
            value = Value(t.inner, value.code)
            t = t.inner
        if isinstance(t, TupleT):
            return self.int_const(len(t.items))
        if isinstance(value.const, (tuple, frozenset, bytes, str)):
            return self.int_const(len(value.const))
        if isinstance(t, ObjT) and t.cls != '*' and self.p.list_base_of(t.cls) is not None:
            return Value(IntT(0, 65535), f'((P2cList *){value.code})->length', U16)
        if isinstance(t, StrT):
            return Value(IntT(0, t.max_len), f'{value.code}->length', U16)
        if isinstance(t, (ListT, ArrayT, DequeT, DictT, SetT)):
            return Value(IntT(0, 65535), f'{value.code}->length', U16)
        if isinstance(t, BytesT):
            if isinstance(value.const, (bytes, bytearray)):
                return self.int_const(len(value.const))
            return Value(IntT(0, 65535), f'{value.code}->length', U16)
        raise self.error(f'len от {describe(t)} не поддержан', node)

    def builtin_abs(self, node: ast.Call) -> Value:
        value = self.int_value(self.one_argument(node), node)
        interval = self.interval_of(value) or self.width(value).interval()
        result = Interval(0 if interval.lo <= 0 <= interval.hi else min(abs(interval.lo), abs(interval.hi)),
                          max(abs(interval.lo), abs(interval.hi))).clamp()
        if isinstance(value.const, int):
            return self.int_const(abs(value.const))
        width = self.common_width([value, Value(IntT(result.lo, result.hi), '')])
        return Value(IntT(result.lo, result.hi), f'p2c_abs_{width.key()}({self.cast(value, width, node)})', width)

    def builtin_bool(self, node: ast.Call) -> Value:
        value = self.one_argument(node)
        if isinstance(value.t, BoolT):
            return value
        return self.bool_value(f'((uint8_t){self.truth(value, node)})')

    def builtin_int(self, node: ast.Call) -> Value:
        value = self.one_argument(node)
        if isinstance(value.t, BoolT):
            return Value(IntT(0, 1), f'((uint8_t){value.code})', U8)
        if isinstance(value.t, StrT):
            if isinstance(value.const, str):
                return self.int_const(int(value.const))
            return Value(IntT(-(1 << 31), (1 << 31) - 1), f'p2c_str_int({value.code})', I32)
        return self.int_value(value, node)

    def builtin_ord(self, node: ast.Call) -> Value:
        value = self.one_argument(node)
        if not isinstance(value.t, StrT):
            raise self.error('ord ожидает строку', node)
        if isinstance(value.const, str):
            return self.int_const(ord(value.const))
        return Value(IntT(0, 255), f'p2c_ord({value.code})', U8)

    def builtin_min(self, node: ast.Call) -> Value:
        return self.min_max('min', node)

    def builtin_max(self, node: ast.Call) -> Value:
        return self.min_max('max', node)

    def min_max(self, name: str, node: ast.Call) -> Value:
        if node.keywords:
            raise self.error(f'{name} с key/default не поддержан', node)
        if len(node.args) == 1:
            return self.reduce_iterable(name, node.args[0], node)
        positional, _ = self.arguments(node)
        values = [self.int_value(value, node) for value in positional]
        intervals = [self.interval_of(value) or self.width(value).interval() for value in values]
        if name == 'min':
            interval = Interval(min(item.lo for item in intervals), min(item.hi for item in intervals))
        else:
            interval = Interval(max(item.lo for item in intervals), max(item.hi for item in intervals))
        if all(isinstance(value.const, int) for value in values):
            return self.int_const((min if name == 'min' else max)(value.const for value in values))
        width = self.common_width(values)
        code = self.cast(values[0], width, node)
        for value in values[1:]:
            code = f'p2c_{name}_{width.key()}({code}, {self.cast(value, width, node)})'
        return Value(IntT(interval.lo, interval.hi), code, width)

    def round_reduced(self, argument: ast.BinOp) -> tuple[ast.expr, ast.expr]:
        """round(x * p / q) с целыми константами p и q: дробь p/q сокращается (то же рациональное
        значение), числитель и делитель становятся уже — на Z80 хватает 16-битной арифметики.
        Узлы замены создаются один раз на узел исходника (одинаковы во всех проходах анализа)."""
        cache = self.c.__dict__.setdefault('round_rewrites', {})
        found = cache.get(id(argument))
        if found is not None:
            return found[1], found[2]
        left, right = argument.left, argument.right
        if (isinstance(left, ast.BinOp) and isinstance(left.op, ast.Mult) and isinstance(right, ast.Constant)
                and type(right.value) is int and right.value > 0):
            for factor_side in ('right', 'left'):
                factor = getattr(left, factor_side)
                if isinstance(factor, ast.Constant) and type(factor.value) is int and factor.value > 0:
                    common = math.gcd(factor.value, right.value)
                    if common > 1:
                        reduced = ast.copy_location(ast.Constant(factor.value // common), factor)
                        operands = {'left': left.left, 'right': left.right, factor_side: reduced}
                        left = ast.copy_location(ast.BinOp(operands['left'], ast.Mult(), operands['right']), left)
                        right = ast.copy_location(ast.Constant(right.value // common), right)
                    break
        cache[id(argument)] = (argument, left, right)
        return left, right

    def builtin_round(self, node: ast.Call) -> Value:
        """round(a * p / q) над целыми: точное округление к чётному (как float CPython)."""
        if len(node.args) != 1 or node.keywords:
            raise self.error('round поддержан с одним аргументом', node)
        argument = node.args[0]
        if not (isinstance(argument, ast.BinOp) and isinstance(argument.op, ast.Div)):
            raise self.error('round поддержан только для частного a / b целых', node)
        left, right = self.round_reduced(argument)
        numerator = self.int_value(self.value_expr(left), node)
        mark = self.mark()
        denominator = self.int_value(self.value_expr(right), node)
        self.fix_left([numerator], mark)
        a = self.interval_of(numerator) or self.width(numerator).interval()
        b = self.interval_of(denominator) or self.width(denominator).interval()
        if b.lo <= 0:
            raise self.error('round: делитель должен быть доказанно положительным', node)
        if max(abs(a.lo), abs(a.hi)) >= (1 << 40):
            raise self.error('round: числитель вне точного диапазона float', node)
        if isinstance(numerator.const, int) and isinstance(denominator.const, int):
            return self.int_const(round(numerator.const / denominator.const))
        lows = (a.lo / b.lo, a.lo / b.hi, a.hi / b.lo, a.hi / b.hi)
        result = Interval(int(min(lows)) - 1, int(max(lows)) + 1).clamp()
        return Value(IntT(result.lo, result.hi),
                     f'p2c_round_div({self.cast(numerator, I32, node)}, {self.cast(denominator, I32, node)})', I32)

    def builtin_isinstance(self, node: ast.Call) -> Value:
        if len(node.args) != 2:
            raise self.error('isinstance(x, класс)', node)
        value = self.value_expr(node.args[0])
        classes = self.class_list(node.args[1], node)
        t = value.t
        if self.incomplete(t):
            raise self.unknown(node)
        if isinstance(t, OptT):
            t = t.inner
        if isinstance(t, ValT):
            return self.bool_value('1' if any(self.p.is_subclass(t.cls, name) for name in classes if name in self.p.classes)
                                   else '0')
        if not isinstance(t, ObjT):
            python_types = {'int': IntT, 'bool': BoolT, 'str': StrT, 'tuple': TupleT}
            for name in classes:
                if name in python_types and isinstance(t, python_types[name]):
                    return self.bool_value('1', True)
            return self.bool_value('0', False)
        return self.bool_value(self.class_test(value, classes, node))

    def class_list(self, node: ast.expr, call: ast.AST) -> list[str]:
        items = node.elts if isinstance(node, ast.Tuple) else [node]
        names = []
        for item in items:
            target = self.expr(item)
            if target.meta is not None and target.meta[0] == 'class':
                names.append(target.meta[1])
            elif target.meta is not None and target.meta[0] == 'pytype':
                names.append(target.meta[1].__name__)
            else:
                raise self.error('isinstance ожидает класс пакета', call)
        return names

    def class_test(self, value: Value, classes: list[str], node: ast.AST) -> str:
        """Проверка номера класса: созданные подклассы указанных классов."""
        base = value.t.inner if isinstance(value.t, OptT) else value.t
        live = self.c.live_classes(base.cls) if base.cls != '*' else sorted(self.c.instantiated)
        matching = [name for name in live if any(self.p.is_subclass(name, wanted) for wanted in classes
                                                 if wanted in self.p.classes)]
        if not self.emit:
            return 'p2c_isinstance'
        if not matching:
            return '0'
        if len(matching) == len(live) and not isinstance(value.t, OptT):
            return '1'
        holder = self.hoist(value)
        test = self.c.layout.class_set_test(f'P2C_CLS({holder.code})', matching)
        if isinstance(value.t, OptT):
            return f'({holder.code} != NULL && {test})'
        return test

    def builtin_hasattr(self, node: ast.Call) -> Value:
        if len(node.args) != 2 or not isinstance(node.args[1], ast.Constant):
            raise self.error('hasattr(объект, "имя")', node)
        value = self.value_expr(node.args[0])
        attr = node.args[1].value
        return self.bool_value(self.presence_test(value, attr, node))

    def presence_test(self, value: Value, attr: str, node: ast.AST) -> str:
        t = value.t
        if self.incomplete(t):
            raise self.unknown(node)
        if isinstance(t, OptT):
            t = t.inner
        if not isinstance(t, ObjT):
            raise self.error(f'hasattr у {describe(t)} не поддержан', node)
        live = self.c.live_classes(t.cls) if t.cls != '*' else sorted(self.c.instantiated)
        having = [name for name in live if self.c.layout_has_attribute(name, attr)]
        if attr not in self.c.presence_queries:
            self.c.presence_queries.add(attr)
            self.c.changed = True
        if not self.emit:
            return 'p2c_hasattr'
        if not having:
            return '0'
        holder = self.hoist(Value(t, value.code))
        return self.presence_condition(holder.code, having, attr)

    def presence_condition(self, holder: str, having: list[str], attr: str) -> str:
        """Атрибут есть у экземпляра: класс может его иметь и бит присутствия поднят записью."""
        parts = []
        for classes in self.class_groups(having).values():
            test = self.c.layout.class_set_test(f'P2C_CLS({holder})', classes)
            parts.append(f'({test} && {self.c.layout.presence_code(holder, classes[0], attr)})')
        return '(' + ' || '.join(parts) + ')'

    def builtin_getattr(self, node: ast.Call) -> Value:
        if len(node.args) not in (2, 3) or not isinstance(node.args[1], ast.Constant):
            raise self.error('getattr(объект, "имя"[, умолчание]) с константным именем', node)
        owner = self.value_expr(node.args[0])
        attr = node.args[1].value
        if len(node.args) == 2:
            return self.materialize(self.attribute(owner, attr, node), node)
        t = owner.t
        if self.incomplete(t):
            raise self.unknown(node)
        base = t.inner if isinstance(t, OptT) else t
        if not isinstance(base, ObjT):
            raise self.error(f'getattr у {describe(t)} не поддержан', node)
        live = self.c.live_classes(base.cls) if base.cls != '*' else sorted(self.c.instantiated)
        having = [name for name in live if self.c.layout_has_attribute(name, attr)]
        methods = [name for name in live if self.p.find_method(name, attr) is not None and
                   not self.c.layout_has_attribute(name, attr)]
        default = self.value_expr(node.args[2])
        if not having and not methods:
            return default
        if having and attr not in self.c.presence_queries:
            self.c.presence_queries.add(attr)
            self.c.changed = True
        holder = self.hoist(Value(base, owner.code))
        if methods:
            if having:
                raise self.error(f'getattr {attr}: и поле, и метод у разных классов', node)
            bound = self.bound_method_value(holder, attr, node) if len(methods) == len(live) else None
            if bound is None:
                if not self.emit:
                    for name in methods:
                        plan = self.c.request_method(self.p.find_method(name, attr)[0].name, attr, node,
                                                     self.plan.filename)
                        number = self.c.fn_value(('bound', plan.key), plan)
                        plan.fn_id = number
                        plan.params[0].t = self.c.grow(plan.params[0].t, ObjT(name), node, self.plan.filename)
                    ids = frozenset(self.c.fn_values[('bound', self.c.request_method(
                        self.p.find_method(name, attr)[0].name, attr, node, self.plan.filename).key)]
                                    for name in methods)
                    first = self.c.request_method(self.p.find_method(methods[0], attr)[0].name, attr, node,
                                                  self.plan.filename)
                    ft = FnT(tuple(param.t for param in first.params[1:]), first.ret, ids)
                    return Value(self.c.join(ft, default.t, node, self.plan.filename), 'p2c_getattr')
                return self.getattr_methods(holder, attr, methods, live, default, node)
            return bound
        if base.cls == '*':
            return self.any_getattr(holder, attr, having, default, node)
        field = self.field_value(holder, base.cls, attr, node)
        result_t = self.c.join(field.t, default.t, node, self.plan.filename)
        if not self.emit:
            return Value(result_t, 'p2c_getattr')
        result = self.temp(result_t)
        if is_int_like(result_t):
            self.plan.temps[result] = ('cint', self.r.cint(result_t))
        test = self.presence_condition(holder.code, having, attr)
        self.branch_assign(test, result, lambda: self.convert(field, result_t, node),
                           lambda: self.convert(default, result_t, node))
        value = Value(result_t, result)
        if is_int_like(result_t):
            value.cwidth = self.r.cint(result_t)
        return value

    def class_groups(self, classes: list[str]) -> dict[str, list[str]]:
        groups: dict[str, list[str]] = {}
        for name in classes:
            groups.setdefault(self.p.root(name), []).append(name)
        return groups

    def any_getattr(self, holder: Value, attr: str, having: list[str], default: Value | None,
                    node: ast.AST) -> Value:
        """Поле объекта без общей базы: переход по номеру класса к слоту его иерархии."""
        groups = self.class_groups(having)
        types = [self.c.field_type(classes[0], attr) for classes in groups.values()]
        if default is not None:
            types.append(default.t)
        if any(self.incomplete(item) for item in types):
            raise self.unknown(node, f'поле {attr}')
        result_t = self.c.join_all(types, node, self.plan.filename)
        if not self.emit:
            return Value(result_t, 'p2c_any_field')
        result = self.temp(result_t)
        if is_int_like(result_t):
            self.plan.temps[result] = ('cint', self.r.cint(result_t))
        default_code = self.convert(default, result_t, node) if default is not None else None
        self.line(f'switch (P2C_CLS({holder.code})) {{')
        for classes in groups.values():
            for name in classes:
                self.line(f'case {self.c.layout.class_id_symbol(name)}:')
            field_t = self.c.field_type(classes[0], attr)
            field = Value(field_t, self.c.layout.field_code(holder.code, classes[0], attr),
                          self.r.cint(field_t) if is_int_like(field_t) else None)
            self.indent += 1
            if default is not None:
                present = self.c.layout.presence_code(holder.code, classes[0], attr)
                self.branch_assign(present, result, lambda: self.convert(field, result_t, node),
                                   lambda: default_code)
            else:
                self.line(f'{result} = {self.convert(field, result_t, node)};')
            self.line('break;')
            self.indent -= 1
        if default is not None:
            self.line(f'default: {result} = {default_code}; break;')
        else:
            self.line('default: p2c_raise(P2C_E_DISPATCH);')
        self.line('}')
        value = Value(result_t, result)
        if is_int_like(result_t):
            value.cwidth = self.r.cint(result_t)
        return value

    def any_setattr(self, holder: Value, attr: str, value: Value, node: ast.AST) -> None:
        having = [name for name in sorted(self.c.instantiated) if self.c.layout_has_attribute(name, attr)]
        groups = self.class_groups(having)
        if not self.emit:
            if isinstance(value.t, BottomT):
                raise Unknown()
            for classes in groups.values():
                self.c.store_field(classes[0], attr, value.t, node, self.plan.filename)
            return
        value = self.hoist(value)
        self.line(f'switch (P2C_CLS({holder.code})) {{')
        for classes in groups.values():
            for name in classes:
                self.line(f'case {self.c.layout.class_id_symbol(name)}:')
            field_t = self.c.field_type(classes[0], attr)
            self.line(f'    {self.c.layout.field_code(holder.code, classes[0], attr)} = '
                      f'{self.convert(value, field_t, node)}; {self.c.layout.presence_set(holder.code, classes[0], attr)}'
                      f'break;')
        self.line('default: p2c_raise(P2C_E_DISPATCH);')
        self.line('}')

    def getattr_methods(self, holder: Value, attr: str, methods: list[str], live: list[str], default: Value,
                        node: ast.AST) -> Value:
        ids = []
        plans = []
        for name in methods:
            plan = self.c.request_method(self.p.find_method(name, attr)[0].name, attr, node, self.plan.filename)
            number = self.c.fn_value(('bound', plan.key), plan)
            ids.append((number, name))
            plans.append(plan)
        ft = FnT(tuple(param.t for param in plans[0].params[1:]), plans[0].ret,
                 frozenset(number for number, _ in ids))
        result_t = self.c.join(ft, default.t, node, self.plan.filename)
        result = self.temp(result_t)
        default_code = self.convert(default, result_t, node)
        self.line(f'switch (P2C_CLS({holder.code})) {{')
        for number, name in ids:
            self.line(f'case {self.c.layout.class_id_symbol(name)}: '
                      f'P2C_FN_SET({result}, {self.c.layout.fn_id_symbol(number)}, {holder.code}); break;')
        self.line(f'default: {result} = {default_code}; break;')
        self.line('}')
        return Value(result_t, result)

    def builtin_setattr(self, node: ast.Call) -> Value:
        if len(node.args) != 3 or not isinstance(node.args[1], ast.Constant):
            raise self.error('setattr(объект, "имя", значение) с константным именем', node)
        target = ast.Attribute(value=node.args[0], attr=node.args[1].value, ctx=ast.Store(),
                               lineno=node.lineno, col_offset=node.col_offset)
        value = self.value_expr(node.args[2])
        self.assign_target(target, value, node)
        return Value(VOID, '')

    def builtin_super(self, node: ast.Call) -> Value:
        if node.args or self.plan.owner is None or not self.plan.params:
            raise self.error('super() поддержан только без аргументов в методе', node)
        owner = self.plan.owner
        self_param = self.plan.params[0]
        t = self.resolved(self_param.t, self_param.declared)
        return Value(VOID, '', meta=('super', owner, Value(t, cname(self_param.name), path=self_param.name)))

    def builtin_id(self, node: ast.Call) -> Value:
        raise self.error('id() в исполняемом коде не поддержан', node)

    # --- построение контейнеров ----------------------------------------------------

    def synthetic_generator(self, call: ast.Call, source: ast.expr) -> ast.GeneratorExp:
        """`f(X)` как `f(p2c_item for p2c_item in X)`: один узел на вызов (ключи ячеек стабильны)."""
        cache = self.c.synthetic_nodes
        if id(call) not in cache:
            item = ast.Name(id='p2c_item', ctx=ast.Load(), lineno=call.lineno, col_offset=call.col_offset)
            target = ast.Name(id='p2c_item', ctx=ast.Store(), lineno=call.lineno, col_offset=call.col_offset)
            generator = ast.GeneratorExp(
                elt=item, generators=[ast.comprehension(target=target, iter=source, ifs=[], is_async=0)],
                lineno=call.lineno, col_offset=call.col_offset)
            cache[id(call)] = (call, generator)
        return cache[id(call)][1]

    def builtin_tuple(self, node: ast.Call) -> Value:
        if not node.args:
            t = TupleT(())
            if self.emit:
                return Value(t, self.temp(t), const=())
            return Value(t, 'p2c_tuple', const=())
        source = node.args[0]
        if isinstance(source, ast.GeneratorExp):
            return self.collect(source, 'array', node)
        if not self.is_view_call(source):
            value = self.value_expr(source)
            if isinstance(value.t, (TupleT, ArrayT)):
                return value
        return self.collect(self.synthetic_generator(node, source), 'array', node)

    def is_view_call(self, node: ast.expr) -> bool:
        return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and
                node.func.attr in ('items', 'values', 'keys') and not node.args)

    def builtin_list(self, node: ast.Call) -> Value:
        if not node.args:
            raise self.error('list() без аргументов: форма задаётся только литералом [] с аннотацией', node)
        source = node.args[0]
        if isinstance(source, ast.GeneratorExp):
            return self.collect(source, 'list', node)
        return self.collect(self.synthetic_generator(node, source), 'list', node)

    def builtin_set(self, node: ast.Call) -> Value:
        if not node.args:
            raise self.error('set() без аргументов: форма задаётся только литералом с аннотацией', node)
        source = node.args[0]
        if isinstance(source, ast.GeneratorExp):
            return self.collect(source, 'set', node)
        return self.collect(self.synthetic_generator(node, source), 'set', node)

    builtin_frozenset = builtin_set

    def builtin_dict(self, node: ast.Call) -> Value:
        if node.args:
            raise self.error('dict(...) с аргументами не поддержан', node)
        self.plan.allocates = True
        return Value(DictT(BOTTOM, BOTTOM), 'p2c_dict' if not self.emit else
                     self.empty_container(DictT(BOTTOM, BOTTOM), node))

    def empty_container(self, t: T, node: ast.AST) -> str:
        raise self.error('пустой контейнер без формы из контекста', node)

    def builtin_bytes(self, node: ast.Call) -> Value:
        return self.make_bytes(node, False)

    def builtin_bytearray(self, node: ast.Call) -> Value:
        return self.make_bytes(node, True)

    def make_bytes(self, node: ast.Call, mutable: bool) -> Value:
        self.plan.allocates = True
        t = BytesT(mutable)
        if len(node.args) != 1:
            raise self.error('bytes/bytearray с одним аргументом', node)
        source = node.args[0]
        if isinstance(source, ast.GeneratorExp):
            return self.collect(source, 'bytearray' if mutable else 'bytes', node)
        value = self.value_expr(source)
        if is_int_like(value.t):
            size = self.int_value(value, node)
            return Value(t, f'p2c_buf_new({self.cast(size, U16, node)}, {1 if mutable else 0})')
        if isinstance(value.t, BytesT):
            return Value(t, f'p2c_buf_copy({value.code}, {1 if mutable else 0})')
        return self.collect_from_value(value, 'bytearray' if mutable else 'bytes', node)

    # --- итерация -----------------------------------------------------------------

    def iteration_element_type(self, t: T, node: ast.AST) -> T:
        if isinstance(t, (ListT, ArrayT, DequeT, SetT)):
            return t.elem
        if isinstance(t, TupleT):
            return self.c.join_all(t.items, node, self.plan.filename)
        if isinstance(t, DictT):
            return t.k
        if isinstance(t, BytesT):
            return IntT(0, 255)
        if isinstance(t, StrT):
            return StrT(1)
        if self.incomplete(t):
            raise self.unknown(node)
        if isinstance(t, ObjT) and t.cls != '*' and self.p.list_base_of(t.cls) is not None:
            return self.list_base_type(t.cls, node)
        raise self.error(f'итерация по {describe(t)} не поддержана', node)

    def open_loop(self, iter_node: ast.expr, node: ast.AST, consumer: str = 'for') -> Loop:
        """Открыть C-цикл по итерируемому выражению; элемент доступен в теле."""
        if isinstance(iter_node, ast.Call) and isinstance(iter_node.func, ast.Name):
            name = iter_node.func.id
            if name == 'range' and not self.is_local('range'):
                return self.open_range(iter_node, node)
            if name == 'enumerate' and not self.is_local('enumerate'):
                return self.open_enumerate(iter_node, node, consumer)
            if name == 'reversed' and not self.is_local('reversed'):
                return self.open_reversed(iter_node, node)
            if name == 'zip' and not self.is_local('zip'):
                return self.open_zip(iter_node, node)
        if isinstance(iter_node, ast.Call) and isinstance(iter_node.func, ast.Attribute) and \
                iter_node.func.attr in ('items', 'values', 'keys') and not iter_node.args:
            owner = self.value_expr(iter_node.func.value)
            if isinstance(owner.t, DictT) or (isinstance(owner.t, BottomT)):
                return self.open_dict(owner, iter_node.func.attr, node)
        value = self.value_expr(iter_node)
        return self.open_value_loop(value, node, consumer)

    def open_value_loop(self, value: Value, node: ast.AST, consumer: str = 'for') -> Loop:
        t = value.t
        if self.incomplete(t):
            raise self.unknown(node)
        if isinstance(t, OptT):
            value = Value(t.inner, value.code)
            t = t.inner
        if isinstance(t, ObjT) and t.cls != '*' and self.p.list_base_of(t.cls) is not None:
            value = self.as_list_base(value, node)
            t = value.t
        if isinstance(t, (ListT, ArrayT, DequeT, BytesT, StrT)):
            holder = self.temp(t)
            index = self.temp(U16, 'i')
            elem = self.iteration_element_type(t, node)
            bound = t.max_len if isinstance(t, StrT) else None
            if not self.emit:
                return Loop(Value(elem, 'p2c_item'), 0, index, bound)
            self.line(f'{holder} = {value.code};')
            self.line(f'for ({index} = 0; {index} < {holder}->length; {index}++) {{')
            self.indent += 1
            if isinstance(t, BytesT):
                element = Value(IntT(0, 255), f'P2C_BYTE({holder}, {index})', U8)
            elif isinstance(t, StrT):
                element = Value(StrT(1), f'p2c_str_char({holder}, {index})')
            elif isinstance(t, DequeT):
                element = Value(elem, f'P2C_DEQUE_AT({holder}, {self.ctype(elem)}, {index})')
            else:
                element = Value(elem, f'P2C_AT({holder}, {self.ctype(elem)}, {index})')
            if is_int_like(elem):
                element.cwidth = self.r.cint(elem)
            element = self.hoist(element)
            return Loop(element, 1, index, bound)
        if isinstance(t, TupleT):
            elem = self.iteration_element_type(t, node)
            index = self.temp(U16, 'i')
            if not self.emit:
                return Loop(Value(elem, 'p2c_item'), 0, index)
            holder = self.hoist(value)
            items = self.temp(('carray', elem, len(t.items)))
            for position, item in enumerate(t.items):
                code = self.convert(Value(item, f'({holder.code}).v{position}',
                                          self.r.cint(item) if is_int_like(item) else None), elem, node)
                self.line(f'{items}[{position}] = {code};')
            self.line(f'for ({index} = 0; {index} < {len(t.items)}; {index}++) {{')
            self.indent += 1
            element = Value(elem, f'{items}[{index}]')
            if is_int_like(elem):
                element.cwidth = self.r.cint(elem)
            return Loop(element, 1, index)
        if isinstance(t, DictT):
            return self.open_dict(value, 'keys', node)
        if isinstance(t, SetT):
            if consumer not in ORDER_FREE_CONSUMERS:
                raise self.error('итерация по множеству вне sorted/sum/any/all/min/max не поддержана', node)
            index = self.temp(U16, 'i')
            if not self.emit:
                return Loop(Value(t.elem, 'p2c_item'), 0, index)
            holder = self.hoist(value)
            self.line(f'for ({index} = 0; {index} < {holder.code}->used; {index}++) {{')
            self.indent += 1
            self.line(f'if (!P2C_SET_LIVE({holder.code}, {index})) continue;')
            element = Value(t.elem, f'P2C_SET_KEY({holder.code}, {self.ctype(t.elem)}, {index})')
            if is_int_like(t.elem):
                element.cwidth = self.r.cint(t.elem)
            return Loop(self.hoist(element), 1, index)
        raise self.error(f'итерация по {describe(t)} не поддержана', node)

    def open_range(self, call: ast.Call, node: ast.AST) -> Loop:
        positional, _ = self.arguments(call)
        arguments = [self.int_value(value, node) for value in positional]
        step = 1
        if len(arguments) == 1:
            start, stop = self.int_const(0), arguments[0]
        elif len(arguments) in (2, 3):
            start, stop = arguments[0], arguments[1]
            if len(arguments) == 3:
                if not isinstance(arguments[2].const, int) or arguments[2].const == 0:
                    raise self.error('шаг range должен быть ненулевой константой', node)
                step = arguments[2].const
        else:
            raise self.error('range с неверным числом аргументов', node)
        a = self.interval_of(start) or self.width(start).interval()
        b = self.interval_of(stop) or self.width(stop).interval()
        if step > 0:
            counter = Interval(a.lo, max(a.lo, b.hi + step - 1)).clamp()
            body = Interval(a.lo, max(a.lo, b.hi - 1)).clamp()
        else:
            counter = Interval(min(a.hi, b.lo + step + 1), a.hi).clamp()
            body = Interval(min(a.hi, b.lo + 1), a.hi).clamp()
        index = self.temp(IntT(counter.lo, counter.hi), 'r')
        element = Value(IntT(body.lo, body.hi), index, cint_for(counter))
        if not self.emit:
            return Loop(element, 0, index)
        limit = self.temp(IntT(b.lo, b.hi))
        self.plan.temps[limit] = ('cint', cint_for(Interval(min(b.lo, counter.lo), max(b.hi, counter.hi))))
        self.plan.temps[index] = ('cint', cint_for(Interval(min(counter.lo, b.lo), max(counter.hi, b.hi))))
        element.cwidth = self.plan.temps[index][1]
        self.line(f'{limit} = {stop.code};')
        compare = '<' if step > 0 else '>'
        self.line(f'for ({index} = {start.code}; {index} {compare} {limit}; {index} += {step}) {{')
        self.indent += 1
        return Loop(element, 1, index)

    def open_enumerate(self, call: ast.Call, node: ast.AST, consumer: str) -> Loop:
        if len(call.args) not in (1, 2):
            raise self.error('enumerate(итерируемое[, начало])', node)
        start = 0
        if len(call.args) == 2:
            start_value = self.value_expr(call.args[1])
            if not isinstance(start_value.const, int):
                raise self.error('начало enumerate должно быть константой', node)
            start = start_value.const
        inner = self.open_loop(call.args[0], node, consumer)
        if inner.index is None:
            raise self.error('enumerate поддержан для последовательностей', node)
        # Счётчик меньше числа шагов (строка — не длиннее max_len).
        last = start + max(inner.bound, 1) - 1 if inner.bound is not None and inner.bound < 65535 else start + 65535
        counter = Value(IntT(start, last), f'((int32_t){inner.index} + {start})' if start else
                        f'((uint16_t){inner.index})', I32 if start else U16)
        t = TupleT((counter.t, inner.element.t))
        if not self.emit:
            return Loop(Value(t, 'p2c_enum'), inner.close_lines, inner.index)
        pair = self.temp(t)
        self.line(f'{pair}.v0 = {self.convert(counter, t.items[0], node)}; '
                  f'{pair}.v1 = {self.convert(inner.element, t.items[1], node)};')
        return Loop(Value(t, pair), inner.close_lines, inner.index)

    def open_reversed(self, call: ast.Call, node: ast.AST) -> Loop:
        if len(call.args) != 1:
            raise self.error('reversed(последовательность)', node)
        value = self.value_expr(call.args[0])
        t = value.t
        if self.incomplete(t):
            raise self.unknown(node)
        if isinstance(t, ObjT) and self.p.list_base_of(t.cls) is not None:
            value = self.as_list_base(value, node)
            t = value.t
        if isinstance(t, TupleT):
            elem = self.iteration_element_type(t, node)
            index = self.temp(IntT(-1, 8), 'i')
            if not self.emit:
                return Loop(Value(elem, 'p2c_item'), 0, index)
            self.plan.temps[index] = ('cint', I16)
            holder = self.hoist(value)
            items = self.temp(('carray', elem, len(t.items)))
            for position, item in enumerate(t.items):
                code = self.convert(Value(item, f'({holder.code}).v{position}',
                                          self.r.cint(item) if is_int_like(item) else None), elem, node)
                self.line(f'{items}[{position}] = {code};')
            self.line(f'for ({index} = {len(t.items) - 1}; {index} >= 0; {index}--) {{')
            self.indent += 1
            element = Value(elem, f'{items}[{index}]', self.r.cint(elem) if is_int_like(elem) else None)
            return Loop(element, 1, index)
        if not isinstance(t, (ListT, ArrayT, BytesT)):
            raise self.error(f'reversed от {describe(t)} не поддержан', node)
        elem = IntT(0, 255) if isinstance(t, BytesT) else t.elem
        index = self.temp(IntT(-1, 65535), 'i')
        element = Value(elem, 'p2c_item')
        if not self.emit:
            return Loop(element, 0, index)
        self.plan.temps[index] = ('cint', I32)
        holder = self.hoist(value)
        self.line(f'for ({index} = (int32_t){holder.code}->length - 1; '
                  f'{index} >= 0 && {index} < (int32_t){holder.code}->length; {index}--) {{')
        self.indent += 1
        if isinstance(t, BytesT):
            element = Value(elem, f'P2C_BYTE({holder.code}, {index})', U8)
        else:
            element = Value(elem, f'P2C_AT({holder.code}, {self.ctype(elem)}, {index})')
            if is_int_like(elem):
                element.cwidth = self.r.cint(elem)
        return Loop(self.hoist(element), 1, index)

    def open_zip(self, call: ast.Call, node: ast.AST) -> Loop:
        values = [self.value_expr(item) for item in call.args]
        types = []
        holders = []
        for value in values:
            t = value.t
            if self.incomplete(t):
                raise self.unknown(node)
            if not isinstance(t, (ListT, ArrayT, TupleT)):
                raise self.error(f'zip по {describe(t)} не поддержан', node)
            types.append(self.iteration_element_type(t, node))
        t = TupleT(tuple(types))
        index = self.temp(U16, 'i')
        if not self.emit:
            return Loop(Value(t, 'p2c_zip'), 0, index)
        arrays = []
        for value in values:
            if isinstance(value.t, TupleT):
                elem = self.iteration_element_type(value.t, node)
                arrays.append(Value(ArrayT(elem), self.convert(value, ArrayT(elem), node)))
            else:
                arrays.append(self.hoist(value))
        lengths = ' && '.join(f'{index} < {array.code}->length' for array in arrays)
        self.line(f'for ({index} = 0; {lengths}; {index}++) {{')
        self.indent += 1
        pair = self.temp(t)
        for position, (array, elem) in enumerate(zip(arrays, types)):
            code = f'P2C_AT({array.code}, {self.ctype(array.t.elem)}, {index})'
            self.line(f'{pair}.v{position} = {code};')
        return Loop(Value(t, pair), 1, index)

    def open_dict(self, owner: Value, view: str, node: ast.AST) -> Loop:
        t = owner.t
        if self.incomplete(t):
            raise self.unknown(node)
        if not isinstance(t, DictT):
            raise self.error(f'.{view}() у {describe(t)}', node)
        if view == 'keys':
            elem = t.k
        elif view == 'values':
            elem = t.v
        else:
            elem = TupleT((t.k, t.v))
        index = self.temp(U16, 'i')
        if not self.emit:
            return Loop(Value(elem, 'p2c_dict_item'), 0, index)
        holder = self.hoist(owner)
        self.line(f'for ({index} = 0; {index} < {holder.code}->used; {index}++) {{')
        self.indent += 1
        self.line(f'if (!P2C_DICT_LIVE({holder.code}, {index})) continue;')
        key = Value(t.k, f'P2C_DICT_KEY({holder.code}, {self.ctype(t.k)}, {index})',
                    self.r.cint(t.k) if is_int_like(t.k) else None)
        value = Value(t.v, f'P2C_DICT_VALUE({holder.code}, {self.ctype(t.k)}, {self.ctype(t.v)}, {index})',
                      self.r.cint(t.v) if is_int_like(t.v) else None)
        if view == 'keys':
            element = self.hoist(key)
        elif view == 'values':
            element = self.hoist(value)
        else:
            pair = self.temp(elem)
            self.line(f'{pair}.v0 = {key.code}; {pair}.v1 = {value.code};')
            element = Value(elem, pair)
        return Loop(element, 1, index)

    def close_loop(self, loop: Loop) -> None:
        for _ in range(loop.close_lines):
            self.indent -= 1
            self.line('}')

    # --- включения и потребители генераторов ----------------------------------------

    def comprehension_loops(self, generators: list[ast.comprehension], node: ast.AST,
                            consumer: str, body) -> None:
        """Вложенные циклы включения: переменные в собственной области видимости."""
        scope_number = self.c.scope_number(generators[0])
        scope: dict[str, str] = {}
        self.scopes.append(scope)
        opened: list[Loop] = []
        conditions = 0
        try:
            for generator in generators:
                if generator.is_async:
                    raise self.error('async-включение не поддержано', node)
                loop = self.open_loop(generator.iter, node, consumer)
                opened.append(loop)
                for name in self.target_names(generator.target):
                    scope[name] = f'p2c_c{scope_number}_{name}'
                self.bind_target(generator.target, loop.element, node)
                for condition in generator.ifs:
                    self.line(f'if ({self.condition(condition)}) {{')
                    self.present |= self.narrowing(condition, True)
                    self.indent += 1
                    conditions += 1
            body()
        finally:
            for _ in range(conditions):
                self.indent -= 1
                self.line('}')
            for loop in reversed(opened):
                self.close_loop(loop)
            self.scopes.pop()

    def target_names(self, target: ast.expr) -> list[str]:
        if isinstance(target, ast.Name):
            return [target.id]
        if isinstance(target, (ast.Tuple, ast.List)):
            names = []
            for item in target.elts:
                names.extend(self.target_names(item))
            return names
        raise self.error('цель включения должна быть именем или кортежем имён', target)

    def expr_ListComp(self, node: ast.ListComp) -> Value:
        return self.comprehension(node, 'list')

    def expr_SetComp(self, node: ast.SetComp) -> Value:
        return self.comprehension(node, 'set')

    def expr_DictComp(self, node: ast.DictComp) -> Value:
        return self.comprehension(node, 'dict')

    def expr_GeneratorExp(self, node: ast.GeneratorExp) -> Value:
        raise self.error('генератор вне tuple/list/any/all/sum/next/min/max не поддержан', node)

    def comprehension(self, node, kind: str) -> Value:
        return self.collect(node, kind, node)

    def collect(self, node, kind: str, call: ast.AST, consumer: str | None = None) -> Value:
        """Собрать контейнер из включения или генератора (consumer — потребитель для порядка)."""
        self.plan.allocates = True
        state = {'t': BOTTOM, 'values': []}
        key_name = f'p2c_collect{id(node)}'
        known_t = self.plan.locals.get(key_name, BOTTOM)
        container_t = self.container_of(kind, known_t)
        if self.emit:
            container_t = self.display_type(container_t, node)
            if kind == 'array' and isinstance(container_t, ListT):
                container_t = ArrayT(container_t.elem)
        holder = self.temp(container_t) if self.emit else 'p2c_collect'
        if self.emit:
            self.line(f'{holder} = {self.new_container_code(container_t, call)};')

        def body() -> None:
            if kind == 'dict':
                key = self.value_expr(node.key)
                value = self.value_expr(node.value)
                item_t = TupleT((key.t, value.t))
                state['t'] = self.c.join(state['t'], item_t, call, self.plan.filename)
                if self.emit:
                    self.dict_store(Value(container_t, holder), key, value, call)
                return
            element = self.value_expr(node.elt)
            state['t'] = self.c.join(state['t'], element.t, call, self.plan.filename)
            if self.emit:
                self.container_add(Value(container_t, holder), element, call)

        try:
            self.comprehension_loops(node.generators, call, consumer or kind, body)
        except Unknown:
            if not self.emit:
                if isinstance(known_t, BottomT):
                    raise
        if not self.emit:
            if not isinstance(state['t'], BottomT):
                self.plan.locals[key_name] = self.c.grow(known_t, state['t'], call, self.plan.filename)
            final = self.plan.locals.get(key_name, BOTTOM)
            if isinstance(final, BottomT):
                raise Unknown()
            return Value(self.container_of(kind, final), 'p2c_collect', display=node)
        return Value(container_t, holder)

    def container_of(self, kind: str, item_t: T) -> T:
        if kind == 'list':
            return ListT(item_t)
        if kind == 'array':
            return ArrayT(item_t)
        if kind == 'set':
            return SetT(item_t)
        if kind == 'dict':
            if isinstance(item_t, TupleT):
                return DictT(item_t.items[0], item_t.items[1])
            return DictT(BOTTOM, BOTTOM)
        if kind == 'deque':
            return DequeT(item_t)
        if kind in ('bytes', 'bytearray'):
            return BytesT(kind == 'bytearray')
        raise ValueError(kind)

    def new_container_code(self, t: T, node: ast.AST) -> str:
        if isinstance(t, ListT):
            return f'p2c_list_new({self.container_class(t)}, sizeof({self.ctype(t.elem)}), 0)'
        if isinstance(t, ArrayT):
            return f'p2c_list_new({self.container_class(t)}, sizeof({self.ctype(t.elem)}), 0)'
        if isinstance(t, SetT):
            return self.set_new(t)
        if isinstance(t, DictT):
            return self.dict_new(t)
        if isinstance(t, BytesT):
            return f'p2c_buf_new(0, 1)'
        if isinstance(t, DequeT):
            return f'p2c_deque_new({self.container_class(t)}, sizeof({self.ctype(t.elem)}), 0)'
        raise self.error(f'новый контейнер {describe(t)}', node)

    def container_add(self, container: Value, element: Value, node: ast.AST) -> None:
        t = container.t
        if isinstance(t, (ListT, ArrayT)):
            ctype = self.ctype(t.elem)
            element = self.hoist(Value(t.elem, self.convert(element, t.elem, node),
                                       self.r.cint(t.elem) if is_int_like(t.elem) else None))
            self.line(f'P2C_LIST_APPEND({container.code}, {ctype}, {element.code});')
        elif isinstance(t, SetT):
            self.set_add(container, element, node)
        elif isinstance(t, DequeT):
            ctype = self.ctype(t.elem)
            element = self.hoist(Value(t.elem, self.convert(element, t.elem, node),
                                       self.r.cint(t.elem) if is_int_like(t.elem) else None))
            self.line(f'P2C_DEQUE_PUSH({container.code}, {ctype}, {element.code});')
        elif isinstance(t, BytesT):
            self.line(f'p2c_buf_append({container.code}, {self.cast(self.int_value(element, node), I32, node)});')
        else:
            raise self.error(f'добавление в {describe(t)}', node)

    def collect_from_value(self, value: Value, kind: str, node: ast.AST) -> Value:
        """tuple(x)/list(x)/set(x): копия итерируемого значения."""
        self.plan.allocates = True
        t = value.t
        if self.incomplete(t):
            raise self.unknown(node)
        if isinstance(t, DictT):
            elem = t.k
        else:
            elem = self.iteration_element_type(t, node)
        container_t = self.container_of(kind, elem)
        if not self.emit:
            return Value(container_t, 'p2c_copy')
        holder = self.temp(container_t)
        self.line(f'{holder} = {self.new_container_code(container_t, node)};')
        loop = self.open_value_loop(value, node, kind)
        self.container_add(Value(container_t, holder), loop.element, node)
        self.close_loop(loop)
        return Value(container_t, holder)

    def reduce_iterable(self, name: str, source: ast.expr, node: ast.Call) -> Value:
        """sum/any/all/min/max/next по генератору или последовательности."""
        state = {'t': BOTTOM}
        key_name = f'p2c_reduce{id(node)}'
        known_t = self.plan.locals.get(key_name, BOTTOM)
        if name in ('any', 'all'):
            result_t = BOOL
        else:
            result_t = known_t
        if self.emit:
            if isinstance(result_t, BottomT):
                raise self.error(f'{name}: форма элементов не выведена', node)
            if name == 'sum':
                result_t = INT_TOP if not isinstance(result_t, IntT) else IntT(-32768 if result_t.lo < 0 else 0, 65535) \
                    if result_t.within_16() else INT_TOP
        result = self.temp(result_t if not isinstance(result_t, BottomT) else BOOL) if self.emit else 'p2c_reduce'
        found = self.temp(BOOL) if self.emit else 'p2c_found'
        if self.emit:
            if name == 'any':
                self.line(f'{result} = 0;')
            elif name == 'all':
                self.line(f'{result} = 1;')
            elif name == 'sum':
                self.line(f'{result} = 0;')
            self.line(f'{found} = 0;')
        done = self.temp(BOOL) if self.emit else 'p2c_done'
        if self.emit:
            self.line(f'{done} = 0;')

        def body() -> None:
            if isinstance(source, ast.GeneratorExp):
                element = self.value_expr(source.elt)
            else:
                element = self.current_item
            state['t'] = self.c.join(state['t'], element.t, node, self.plan.filename)
            if not self.emit:
                return
            if name == 'any':
                self.line(f'if ({self.truth(element, node)}) {{ {result} = 1; {done} = 1; break; }}')
            elif name == 'all':
                self.line(f'if (!{self.truth(element, node)}) {{ {result} = 0; {done} = 1; break; }}')
            elif name == 'next':
                self.line(f'{result} = {self.convert(element, result_t, node)}; {found} = 1; {done} = 1; break;')
            elif name == 'sum':
                self.line(f'{result} = P2C_TO_{self.r.cint(result_t).key().upper()}((int32_t){result} + '
                          f'{self.cast(self.int_value(element, node), I32, node)});')
            else:
                symbol = '<' if name == 'min' else '>'
                code = self.convert(element, result_t, node)
                self.line(f'if (!{found} || {code} {symbol} {result}) {{ {result} = {code}; {found} = 1; }}')

        try:
            if isinstance(source, ast.GeneratorExp):
                self.reduce_generators(source.generators, node, name, body, done)
            else:
                loop = self.open_loop(source, node, name)
                self.current_item = loop.element
                try:
                    body()
                finally:
                    self.close_loop(loop)
        except Unknown:
            if not self.emit and name not in ('any', 'all'):
                if isinstance(known_t, BottomT):
                    raise
        if not self.emit:
            if not isinstance(state['t'], BottomT):
                self.plan.locals[key_name] = self.c.grow(known_t, state['t'], node, self.plan.filename)
            if name in ('any', 'all'):
                return self.bool_value('p2c_reduce')
            final = self.plan.locals.get(key_name, BOTTOM)
            if isinstance(final, BottomT):
                raise Unknown()
            if name == 'sum':
                return Value(IntT(-(1 << 31), (1 << 31) - 1), 'p2c_reduce')
            return Value(final, 'p2c_reduce')
        if name in ('min', 'max'):
            self.line(f'if (!{found}) p2c_raise(P2C_E_EMPTY);')
        value = Value(result_t, result)
        if is_int_like(result_t):
            value.cwidth = self.r.cint(result_t)
        if name in ('any', 'all'):
            value.cwidth = U8
        value.found = found
        return value

    def reduce_generators(self, generators, node, name, body, done) -> None:
        """Циклы генератора с досрочным выходом из всех уровней."""
        if len(generators) == 1:
            self.comprehension_loops(generators, node, name, body)
            return
        # Несколько уровней: break выходит из внутреннего цикла, внешние проверяют done.
        scope_number = self.c.scope_number(generators[0])
        scope: dict[str, str] = {}
        self.scopes.append(scope)
        opened = []
        conditions = 0
        try:
            for position, generator in enumerate(generators):
                loop = self.open_loop(generator.iter, node, name)
                opened.append(loop)
                if position:
                    pass
                for target_name in self.target_names(generator.target):
                    scope[target_name] = f'p2c_c{scope_number}_{target_name}'
                self.bind_target(generator.target, loop.element, node)
                for condition in generator.ifs:
                    self.line(f'if ({self.condition(condition)}) {{')
                    self.present |= self.narrowing(condition, True)
                    self.indent += 1
                    conditions += 1
            body()
        finally:
            for _ in range(conditions):
                self.indent -= 1
                self.line('}')
            for position, loop in enumerate(reversed(opened)):
                self.close_loop(loop)
                if position < len(opened) - 1:
                    self.line(f'if ({done}) break;')
            self.scopes.pop()

    def builtin_any(self, node: ast.Call) -> Value:
        if isinstance(node.args[0], (ast.Tuple, ast.List)):
            return self.literal_truths(node.args[0], ' || ', node)
        return self.reduce_iterable('any', node.args[0], node)

    def builtin_all(self, node: ast.Call) -> Value:
        if isinstance(node.args[0], (ast.Tuple, ast.List)):
            return self.literal_truths(node.args[0], ' && ', node)
        return self.reduce_iterable('all', node.args[0], node)

    def literal_truths(self, literal: ast.Tuple | ast.List, symbol: str, node: ast.AST) -> Value:
        """all((a, b))/any([a, b]): элементы вычисляются до проверки, как при создании кортежа."""
        values = []
        for item in literal.elts:
            mark = self.mark()
            value = self.value_expr(item)
            self.fix_left(values, mark)
            values.append(value)
        if not values:
            return self.bool_value('1' if symbol == ' && ' else '0')
        truths = [self.truth(self.hoist(value), node) for value in values]
        return self.bool_value('(' + symbol.join(truths) + ')')

    def builtin_sum(self, node: ast.Call) -> Value:
        if len(node.args) != 1:
            raise self.error('sum с начальным значением не поддержан', node)
        return self.reduce_iterable('sum', node.args[0], node)

    def builtin_next(self, node: ast.Call) -> Value:
        if len(node.args) not in (1, 2):
            raise self.error('next(генератор[, умолчание])', node)
        value = self.reduce_iterable('next', node.args[0], node)
        if len(node.args) == 1:
            if self.emit:
                self.line(f'if (!{value.found}) p2c_raise(P2C_E_STOP);')
            return value
        default = self.value_expr(node.args[1])
        result_t = self.c.join(value.t, default.t, node, self.plan.filename)
        if not self.emit:
            return Value(result_t, 'p2c_next')
        result = self.temp(result_t)
        self.branch_assign(value.found, result, lambda: self.convert(value, result_t, node),
                           lambda: self.convert(default, result_t, node))
        out = Value(result_t, result)
        if is_int_like(result_t):
            out.cwidth = self.r.cint(result_t)
        return out

    def builtin_sorted(self, node: ast.Call) -> Value:
        """Устойчивая сортировка вставками по ключу-кортежу целых (порядок CPython)."""
        if len(node.args) != 1:
            raise self.error('sorted(итерируемое, key=...)', node)
        key_node = None
        for keyword in node.keywords:
            if keyword.arg == 'key':
                key_node = keyword.value
            else:
                raise self.error(f'sorted: аргумент {keyword.arg} не поддержан', node)
        source = node.args[0]
        if not isinstance(source, ast.GeneratorExp):
            source = self.synthetic_generator(node, source)
        items = self.collect(source, 'list', node, 'sorted')
        t = items.t
        if isinstance(t, BottomT) or contains_bottom(t):
            raise self.unknown(node)
        elem = t.elem
        if key_node is None:
            if not is_int_like(elem):
                raise self.error('sorted без key поддержан для целых', node)
            key_lambda = None
        else:
            if not isinstance(key_node, ast.Lambda) or len(key_node.args.args) != 1:
                raise self.error('key sorted должен быть лямбдой одного аргумента', node)
            key_lambda = key_node
        self.sort_list(items, key_lambda, node)
        return items

    def sort_list(self, items: Value, key_lambda: ast.Lambda | None, node: ast.AST) -> None:
        elem = items.t.elem
        scope_name = key_lambda.args.args[0].arg if key_lambda is not None else None
        scope_key = f'p2c_c{self.c.scope_number(key_lambda)}_{scope_name}' if scope_name else None
        key_t_name = f'p2c_sortkey{id(node)}'
        if key_lambda is not None:
            self.scopes.append({scope_name: scope_key})
            try:
                self.plan.locals[scope_key] = self.c.grow(self.plan.locals.get(scope_key, BOTTOM), elem, node,
                                                          self.plan.filename) if not self.emit else elem
                if not self.emit:
                    key_value = self.value_expr(key_lambda.body)
                    self.plan.locals[key_t_name] = self.c.grow(self.plan.locals.get(key_t_name, BOTTOM),
                                                               key_value.t, node, self.plan.filename)
                    return
            finally:
                if not self.emit:
                    self.scopes.pop()
        elif not self.emit:
            return
        key_t = self.plan.locals.get(key_t_name, elem) if key_lambda is not None else elem
        if isinstance(key_t, BottomT):
            raise self.error('sorted: форма ключа не выведена', node)
        key_items = key_t.items if isinstance(key_t, TupleT) else (key_t,)
        if not all(is_int_like(item) for item in key_items):
            raise self.error('ключ sorted должен состоять из целых', node)
        count = self.temp(U16)
        keys = self.temp(('keys', key_t))
        outer = self.temp(U16, 'i')
        inner = self.temp(IntT(-1, 65535), 'j')
        self.plan.temps[inner] = ('cint', I32)
        elem_c = self.ctype(elem)
        key_c = self.ctype(key_t)
        self.line(f'{count} = {items.code}->length;')
        self.line(f'{keys} = ({key_c} *)p2c_scratch((uint16_t)({count} * sizeof({key_c})));')
        self.line(f'for ({outer} = 0; {outer} < {count}; {outer}++) {{')
        self.indent += 1
        if key_lambda is not None:
            self.line(f'{scope_key} = P2C_AT({items.code}, {elem_c}, {outer});')
            key_value = self.value_expr(key_lambda.body)
            self.line(f'{keys}[{outer}] = {self.convert(key_value, key_t, node)};')
        else:
            self.line(f'{keys}[{outer}] = P2C_AT({items.code}, {elem_c}, {outer});')
        self.indent -= 1
        self.line('}')
        if key_lambda is not None:
            self.scopes.pop()
        element_holder = self.temp(elem)
        key_holder = self.temp(key_t)
        self.line(f'for ({outer} = 1; {outer} < {count}; {outer}++) {{')
        self.indent += 1
        self.line(f'{element_holder} = P2C_AT({items.code}, {elem_c}, {outer}); {key_holder} = {keys}[{outer}];')
        self.line(f'for ({inner} = (int32_t){outer} - 1; {inner} >= 0; {inner}--) {{')
        self.indent += 1
        less = self.key_less(key_holder, f'{keys}[{inner}]', key_t)
        self.line(f'if (!{less}) break;')
        self.line(f'P2C_PUT({items.code}, {elem_c}, {inner} + 1, P2C_AT({items.code}, {elem_c}, {inner})); '
                  f'{keys}[{inner} + 1] = {keys}[{inner}];')
        self.indent -= 1
        self.line('}')
        self.line(f'P2C_PUT({items.code}, {elem_c}, {inner} + 1, {element_holder}); {keys}[{inner} + 1] = {key_holder};')
        self.indent -= 1
        self.line('}')

    def key_less(self, left: str, right: str, key_t: T) -> str:
        if not isinstance(key_t, TupleT):
            return f'({left} < {right})'
        parts = []
        for index in range(len(key_t.items)):
            prefix = ' && '.join(f'({left}.v{earlier} == {right}.v{earlier})' for earlier in range(index))
            test = f'({left}.v{index} < {right}.v{index})'
            parts.append(f'({prefix} && {test})' if prefix else test)
        return '(' + ' || '.join(parts) + ')'
