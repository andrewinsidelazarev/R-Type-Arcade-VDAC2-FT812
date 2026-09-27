"""Состояние полнопрограммного анализа: классы, поля, функции, константы.

Анализ повторяется до неподвижной точки: каждый проход по всем достижимым
функциям объединяет потоки значений в ячейки (параметры, локальные, поля
классов, элементы контейнеров, результаты). Затем формы значений
фиксируются, выбираются C-типы и выполняется генерация.
"""
from __future__ import annotations

import ast
import dataclasses
import types as pytypes
from collections import deque
from dataclasses import dataclass, field

import pygame

from .errors import TranslationError
from .intervals import INT32_MAX, INT32_MIN, Interval, widen_threshold
from .program import ClassInfo, Program
from .ptypes import (
    BOOL, BOTTOM, FONT, IMAGE, NONE, STR, TARGET, VOID, ArrayT, BoolT, BottomT, BytesT, DequeT,
    DictT, FnT, FontT, ImageT, IntT, ListT, NoneT, ObjT, OptT, SetT, StrT, T, TargetT, TupleT,
    ValT, VoidT, ExtT, cint_for, contains_bottom,
)

INT_EMPTY = IntT(INT32_MAX, INT32_MIN)
# Ячейка, новое значение которой вычисляется из её же прошлого (x += 1, x = x + …), расширяется
# сразу; остальные — только после WIDEN_AFTER проходов. Иначе величины, производные от растущего
# счётчика (координаты от номера кадра), расширялись вместе с ним до границ int16/int32.
WIDEN_AFTER = 30
FIXPOINT_LIMIT = 120
SMALL_TUPLE = 8
# Встроенные неизменяемые значения, не являющиеся классами пакета.
RECT_FIELDS = ('x', 'y', 'w', 'h')


def int_empty(value: T) -> bool:
    return isinstance(value, IntT) and value.lo > value.hi


@dataclass
class FieldCell:
    """Атрибут экземпляров одной иерархии классов."""

    root: str
    name: str
    t: T = BOTTOM
    classes: set[str] = field(default_factory=set)
    declared: T | None = None
    used: bool = False            # атрибут читается или пишется транслируемым кодом


@dataclass
class Param:
    name: str
    declared: T | None
    t: T = BOTTOM
    default: ast.expr | None = None
    keyword_only: bool = False


@dataclass
class Capture:
    name: str
    t: T = BOTTOM
    by_pointer: bool = False


@dataclass
class Plan:
    key: tuple
    kind: str                     # function/method/property/staticmethod/classmethod/lambda/nested
    name: str
    module: str
    filename: str
    node: ast.AST
    owner: str | None             # класс-владелец метода
    c_name: str
    params: list[Param] = field(default_factory=list)
    ret_declared: T | None = None
    ret: T = BOTTOM
    locals: dict[str, T] = field(default_factory=dict)
    captures: list[Capture] = field(default_factory=list)
    parent: 'Plan | None' = None  # объемлющая функция для nested/lambda
    callees: set = field(default_factory=set)
    writes: bool = False
    pure: bool = False
    allocates: bool = False
    lines: list[str] = field(default_factory=list)
    temps: dict[str, object] = field(default_factory=dict)
    tables: list[str] = field(default_factory=list)   # объявления таблиц значений выражений (fn_expr.tabulated)
    fn_id: int | None = None      # номер вызываемого значения, если функция используется как значение
    reached: bool = True
    class_binding: tuple | None = None  # classmethod: (имя параметра cls, класс)
    errors: list = field(default_factory=list)  # ошибки последнего прохода анализа


@dataclass
class ExternMethod:
    """Метод объекта платформы (звук, цель вывода, шрифт)."""

    c_name: str
    params: tuple
    ret: T


class Compiler:
    """Полнопрограммный анализ и сбор фактов для генерации."""

    def __init__(self, program: Program, roots: dict[str, object],
                 externs: dict[str, dict[str, ExternMethod]] | None = None,
                 extern_methods: dict[tuple[str, str], ExternMethod] | None = None) -> None:
        self.program = program
        self.roots = roots
        self.externs = externs or {}                  # тип Python -> методы
        self.extern_methods = extern_methods or {}    # (класс пакета, метод) -> адаптер
        self.instantiated: set[str] = set()
        self.fields: dict[tuple[str, str], FieldCell] = {}
        self.plans: dict[tuple, Plan] = {}
        self.queue: list[Plan] = []
        self.strings: dict[str, int] = {}
        self.fn_values: dict[tuple, int] = {}         # ключ вызываемого значения -> номер
        self.fn_targets: dict[int, tuple] = {}
        self.constants: dict[int, tuple[object, T]] = {}
        self.const_alive: list[object] = []
        self.iteration = 0
        self.pessimistic = False
        self.changed = False
        self.raise_messages: list[str] = []
        self.container_cells: dict[tuple, T] = {}
        self.snapshot_objects: list[object] = []
        # Синтетические узлы AST (генераторы вызовов tuple(x)/list(x)): живут весь анализ.
        self.synthetic_nodes: dict[int, tuple] = {}
        self.pass_visited: set = set()
        self.pass_worklist: list[Plan] = []
        import os
        self.debug_unknown = os.environ.get('P2C_DEBUG_UNKNOWN')
        self.scanned_ids: set[int] = set()
        # Формы ячеек, в которые попадают дисплеи и включения (по узлу AST).
        self.display_types: dict[int, T] = {}
        self.display_nodes: dict[int, object] = {}
        self.scope_numbers: dict[int, tuple[int, object]] = {}
        self.line_numbers: dict[str, int] = {}
        # Атрибуты, наличие которых проверяется у экземпляра (hasattr, getattr с умолчанием).
        self.presence_queries: set[str] = set()
        # Собственные тела функций платформы (ключ плана → строки C по генератору функции): анализ идёт по
        # исходнику Python, а генерация выводит эти строки (например, вызов ассемблерной отрисовки).
        self.native_bodies: dict[tuple, object] = {}
        self.native_prototypes: list[str] = []            # объявления функций, вызываемых собственными телами
        self._scan_snapshot()

    # --- решётка ---------------------------------------------------------------

    def join(self, left: T, right: T, node: ast.AST | None = None, filename: str | None = None,
             widen: bool = False) -> T:
        if left == right:
            return left
        if isinstance(left, BottomT):
            return right
        if isinstance(right, BottomT):
            return left
        if isinstance(left, IntT) and isinstance(right, IntT):
            if int_empty(left):
                return right
            if int_empty(right):
                return left
            merged = Interval(min(left.lo, right.lo), max(left.hi, right.hi))
            if widen and merged != left.interval:
                merged = widen_threshold(merged)
            return IntT(merged.lo, merged.hi)
        if isinstance(left, StrT) and isinstance(right, StrT):
            longest = max(left.max_len, right.max_len)
            if widen and longest != left.max_len:
                longest = 255 if longest <= 255 else 65535
            return StrT(longest)
        if isinstance(left, BoolT) and isinstance(right, BoolT):
            return BOOL
        if isinstance(left, BoolT) and isinstance(right, IntT):
            return self.join(IntT(0, 1), right, node, filename, widen)
        if isinstance(left, IntT) and isinstance(right, BoolT):
            return self.join(left, IntT(0, 1), node, filename, widen)
        if isinstance(left, NoneT):
            return right if isinstance(right, OptT) else OptT(right)
        if isinstance(right, NoneT):
            return left if isinstance(left, OptT) else OptT(left)
        if isinstance(left, OptT) or isinstance(right, OptT):
            inner_left = left.inner if isinstance(left, OptT) else left
            inner_right = right.inner if isinstance(right, OptT) else right
            return OptT(self.join(inner_left, inner_right, node, filename, widen))
        if isinstance(left, ObjT) and isinstance(right, ObjT):
            if left.cls == '*' or right.cls == '*':
                return ObjT('*')
            common = self.program.lca(left.cls, right.cls)
            return ObjT(common if common is not None else '*')
        if isinstance(left, TupleT) and isinstance(right, TupleT):
            if len(left.items) == len(right.items):
                return TupleT(tuple(self.join(a, b, node, filename, widen)
                                    for a, b in zip(left.items, right.items)))
            return ArrayT(self.join_all(list(left.items) + list(right.items), node, filename, widen))
        if isinstance(left, ArrayT) and isinstance(right, TupleT):
            return ArrayT(self.join_all([left.elem, *right.items], node, filename, widen))
        if isinstance(left, TupleT) and isinstance(right, ArrayT):
            return ArrayT(self.join_all([right.elem, *left.items], node, filename, widen))
        # list и tuple[T, ...] имеют одно C-представление (P2cList): последовательность.
        if isinstance(left, (ListT, ArrayT)) and isinstance(right, (ListT, ArrayT)) and type(left) is not type(right):
            return ListT(self.join(left.elem, right.elem, node, filename, widen))
        if isinstance(left, ListT) and isinstance(right, TupleT):
            return ListT(self.join_all([left.elem, *right.items], node, filename, widen))
        if isinstance(left, TupleT) and isinstance(right, ListT):
            return ListT(self.join_all([right.elem, *left.items], node, filename, widen))
        for kind in (ListT, ArrayT, DequeT, SetT):
            if isinstance(left, kind) and isinstance(right, kind):
                return kind(self.join(left.elem, right.elem, node, filename, widen))
        if isinstance(left, DictT) and isinstance(right, DictT):
            return DictT(self.join(left.k, right.k, node, filename, widen),
                         self.join(left.v, right.v, node, filename, widen))
        if isinstance(left, BytesT) and isinstance(right, BytesT):
            return BytesT(left.mutable or right.mutable)
        if isinstance(left, FnT) and isinstance(right, FnT) and len(left.params) == len(right.params):
            return FnT(tuple(self.join(a, b, node, filename, widen) for a, b in zip(left.params, right.params)),
                       self.join(left.ret, right.ret, node, filename, widen), left.ids | right.ids)
        raise TranslationError(f'несовместимые формы {describe(left)} и {describe(right)}', node, filename)

    def join_all(self, items, node=None, filename=None, widen=False) -> T:
        result: T = BOTTOM
        for item in items:
            result = self.join(result, item, node, filename, widen)
        return result

    def grow(self, previous: T, new: T, node=None, filename=None) -> T:
        """Объединение в ячейку: самоссылающийся поток расширяется сразу, прочие — после WIDEN_AFTER проходов."""
        widen = self.iteration >= WIDEN_AFTER or self.self_referential(node)
        merged = self.join(previous, new, node, filename, widen=widen)
        if merged != previous:
            self.changed = True
        return merged

    def self_referential(self, node) -> bool:
        """Поток из присваивания, правая часть которого читает саму цель (x += 1, self.n = self.n + 1)."""
        if not isinstance(node, (ast.AugAssign, ast.Assign)):
            return False
        cache = self.__dict__.setdefault('self_reference_cache', {})
        found = cache.get(id(node))
        if found is not None and found[0] is node:
            return found[1]
        result = isinstance(node, ast.AugAssign)
        if not result:
            targets = {ast.unparse(target) for target in node.targets}
            result = any(isinstance(item, (ast.Name, ast.Attribute)) and ast.unparse(item) in targets
                         for item in ast.walk(node.value))
        # Узел хранится вместе с ответом: id освобождённого синтетического узла может повториться.
        cache[id(node)] = (node, result)
        return result

    # --- снимок объектов --------------------------------------------------------

    def value_type(self, value: object, where: str = '', prefer_array: bool = False) -> T:
        """Форма значения CPython (снимок, константа модуля; prefer_array — для таблиц-констант)."""
        if value is None:
            return NONE
        if type(value) is bool:
            return BOOL
        if type(value) is int:
            if not INT32_MIN <= value <= INT32_MAX:
                raise TranslationError(f'{where}: целое {value} вне int32')
            return IntT(value, value)
        if isinstance(value, str):
            self.intern(value)
            return StrT(min(65535, len(value.encode('utf-8'))))
        if isinstance(value, float):
            raise TranslationError(f'{where}: вещественное значение {value!r} не поддержано')
        if isinstance(value, bytearray):
            return BytesT(True)
        if isinstance(value, bytes):
            return BytesT(False)
        if isinstance(value, pygame.Surface):
            return IMAGE
        if isinstance(value, pygame.Rect):
            return ValT('Rect')
        if isinstance(value, pygame.font.Font):
            return FONT
        if type(value).__name__ in self.externs:
            return ExtT(type(value).__name__)
        info = self.program.class_of(value)
        if info is not None:
            if info.frozen:
                return ValT(info.name)
            return ObjT(info.name)
        if isinstance(value, tuple):
            items = [self.value_type(item, where + '[]', False) for item in value]
            if prefer_array and len(items) >= 3:
                # Константа-таблица: однородные записи индексируются и перебираются как массив.
                try:
                    joined = self.join_all(items)
                except TranslationError:
                    joined = None
                if joined is not None and not isinstance(joined, (ArrayT, ListT)) or (
                        isinstance(joined, ArrayT) and all(isinstance(item, ArrayT) for item in items)):
                    return ArrayT(joined)
            if len(items) <= SMALL_TUPLE:
                return TupleT(tuple(items))
            return ArrayT(self.join_all(items))
        if isinstance(value, list):
            return ListT(self.join_all(self.value_type(item, where + '[]') for item in value))
        if isinstance(value, deque):
            return DequeT(self.join_all(self.value_type(item, where + '[]') for item in value))
        if isinstance(value, dict):
            return DictT(self.join_all(self.value_type(item, where + '{}') for item in value.keys()),
                         self.join_all(self.value_type(item, where + '{}') for item in value.values()))
        if isinstance(value, (set, frozenset)):
            return SetT(self.join_all(self.value_type(item, where + '{}') for item in value))
        if isinstance(value, pytypes.MethodType):
            return self.extern_callable_type(value, where)
        raise TranslationError(f'{where}: значение типа {type(value).__name__} не поддержано')

    def extern_callable_type(self, value: pytypes.MethodType, where: str) -> T:
        owner = type(value.__self__).__name__
        methods = self.externs.get(owner, {})
        method = methods.get(value.__func__.__name__)
        if method is None:
            raise TranslationError(f'{where}: вызываемое {owner}.{value.__func__.__name__} не объявлено адаптером')
        number = self.fn_value(('extern', owner, value.__func__.__name__), None)
        return FnT(method.params, method.ret, frozenset({number}))

    def _scan_snapshot(self) -> None:
        """Классы и поля экземпляров, достижимых из корней снимка."""
        self.scan_values(list(self.roots.values()))

    def scan_values(self, values: list) -> None:
        """Поля объектов графа значений (снимок или константа модуля) как потоки ячеек."""
        seen: set[int] = self.scanned_ids
        stack = list(values)
        while stack:
            value = stack.pop()
            if id(value) in seen:
                continue
            seen.add(id(value))
            info = self.program.class_of(value)
            if info is not None:
                self.snapshot_objects.append(value)
                if not info.frozen:
                    self.instantiated.add(info.name)
                for name, item in vars(value).items():
                    cell = self.field_cell(info.name, name)
                    cell.classes.add(info.name)
                    cell.t = self.join(cell.t, self.value_type(item, f'{info.name}.{name}'))
                    stack.append(item)
                if isinstance(value, list):
                    stack.extend(value)
            elif isinstance(value, (list, tuple, deque, set, frozenset)):
                stack.extend(value)
            elif isinstance(value, dict):
                stack.extend(value.keys())
                stack.extend(value.values())

    # --- классы и поля ----------------------------------------------------------

    def field_cell(self, class_name: str, attribute: str) -> FieldCell:
        root = self.program.root(class_name)
        key = (root, attribute)
        cell = self.fields.get(key)
        if cell is None:
            cell = FieldCell(root, attribute)
            self.fields[key] = cell
            declared = self.declared_field(root, attribute)
            if declared is not None:
                cell.declared = declared
        return cell

    def declared_field(self, root: str, attribute: str) -> T | None:
        from .annotations import parse_annotation
        for name in self.program.descendants(root):
            info = self.program.classes[name]
            node = info.annotations.get(attribute)
            if node is not None:
                return parse_annotation(self, node, info.module, info.filename)
        return None

    def note_instantiated(self, class_name: str) -> None:
        if class_name not in self.instantiated:
            self.instantiated.add(class_name)
            self.changed = True

    def live_classes(self, class_name: str) -> list[str]:
        """Созданные классы, совместимые с формой ObjT(class_name)."""
        return [name for name in self.program.descendants(class_name) if name in self.instantiated]

    def store_field(self, class_name: str, attribute: str, value: T, node=None, filename=None) -> FieldCell:
        cell = self.field_cell(class_name, attribute)
        if not cell.used:
            cell.used = True
            self.changed = True
        for name in self.live_classes(class_name) or [class_name]:
            if name not in cell.classes:
                cell.classes.add(name)
                self.changed = True
        cell.t = self.grow(cell.t, value, node, filename)
        return cell

    def field_type(self, class_name: str, attribute: str) -> T:
        cell = self.fields.get((self.program.root(class_name), attribute))
        if cell is None:
            return BOTTOM
        if not cell.used:
            cell.used = True
            self.changed = True
        if isinstance(cell.t, BottomT) and cell.declared is not None and self.pessimistic:
            return cell.declared
        return cell.t

    # --- строки и вызываемые значения -------------------------------------------

    def intern(self, text: str) -> int:
        if text not in self.strings:
            self.strings[text] = len(self.strings) + 1
        return self.strings[text]

    def fn_value(self, key: tuple, plan: Plan | None) -> int:
        if key not in self.fn_values:
            number = len(self.fn_values) + 1
            self.fn_values[key] = number
            self.fn_targets[number] = (key, plan)
            self.changed = True
        return self.fn_values[key]

    # --- константы -------------------------------------------------------------

    def constant(self, value: object, where: str) -> tuple[int, T]:
        number = id(value)
        if number not in self.constants:
            self.constants[number] = (value, self.value_type(value, where, prefer_array=True))
            self.const_alive.append(value)
            # Экземпляры dataclass внутри константы дают потоки своим полям.
            self.scan_values([value])
            self.changed = True
        return number, self.constants[number][1]

    # --- сообщения ошибок ----------------------------------------------------------

    def raise_index(self, message: str) -> int:
        if message not in self.raise_messages:
            self.raise_messages.append(message)
        return self.raise_messages.index(message) + 1

    # --- функции -------------------------------------------------------------------

    def _add_plan(self, plan: Plan) -> Plan:
        self.plans[plan.key] = plan
        self.queue.append(plan)
        self.changed = True
        return self.reach(plan)

    def reach(self, plan: Plan) -> Plan:
        """Функция достижима в текущем проходе: анализируется в нём же."""
        if plan.key not in self.pass_visited and plan.kind != 'value_init':
            self.pass_visited.add(plan.key)
            self.pass_worklist.append(plan)
        return plan

    def _params(self, plan: Plan, arguments: ast.arguments, module: str, filename: str,
                self_type: T | None) -> None:
        from .annotations import parse_annotation
        if arguments.vararg or arguments.kwarg or arguments.posonlyargs:
            raise TranslationError('сигнатура с *args/**kwargs не поддержана', plan.node, filename)
        names = list(arguments.args)
        defaults = [None] * (len(names) - len(arguments.defaults)) + list(arguments.defaults)
        start = 0
        if self_type is not None:
            if not names:
                raise TranslationError('метод без self', plan.node, filename)
            plan.params.append(Param(names[0].arg, self_type))
            start = 1
        for argument, default in list(zip(names, defaults))[start:]:
            declared = (parse_annotation(self, argument.annotation, module, filename)
                        if argument.annotation is not None else None)
            if isinstance(declared, BottomT):
                declared = None
            plan.params.append(Param(argument.arg, declared, default=default))
        for argument, default in zip(arguments.kwonlyargs, arguments.kw_defaults):
            declared = (parse_annotation(self, argument.annotation, module, filename)
                        if argument.annotation is not None else None)
            if isinstance(declared, BottomT):
                declared = None
            plan.params.append(Param(argument.arg, declared, default=default, keyword_only=True))
        if isinstance(plan.node, ast.FunctionDef):
            returns = plan.node.returns
            if returns is None:
                plan.ret_declared = None
            elif isinstance(returns, ast.Constant) and returns.value is None:
                plan.ret_declared = VOID
            else:
                declared = parse_annotation(self, returns, module, filename)
                plan.ret_declared = VOID if isinstance(declared, NoneT) else (
                    None if isinstance(declared, BottomT) else declared)

    def request_function(self, module: str, name: str, node=None, filename=None) -> Plan:
        key = ('function', module, name)
        plan = self.plans.get(key)
        if plan is not None:
            return self.reach(plan)
        info = self.program.modules[module].functions.get(name)
        if info is None:
            raise TranslationError(f'нет функции {module}.{name}', node, filename)
        short = module.rsplit('.', 1)[-1]
        plan = Plan(key, 'function', name, module, info.filename, info.node, None, f'{short}_f_{name}')
        self._params(plan, info.node.args, module, info.filename, None)
        return self._add_plan(plan)

    def request_method(self, impl_class: str, name: str, node=None, filename=None, cls: str | None = None) -> Plan:
        info = self.program.classes[impl_class]
        function = info.methods.get(name) or info.synthesized.get(name)
        if function is None:
            raise TranslationError(f'нет метода {impl_class}.{name}', node, filename)
        kind = info.method_kind(name)
        if info.frozen and name == '__init__':
            kind = 'value_init'
        key = ('method', impl_class, name) if kind != 'classmethod' else ('method', impl_class, name, cls)
        plan = self.plans.get(key)
        if plan is not None:
            return self.reach(plan)
        c_name = f'{impl_class}_m_{name}' if kind != 'classmethod' else f'{impl_class}_m_{name}_for_{cls}'
        plan = Plan(key, kind, name, info.module, info.filename, function, impl_class, c_name)
        if kind == 'staticmethod':
            self_type = None
        elif kind == 'classmethod':
            self_type = VOID
        else:
            self_type = ValT(impl_class) if info.frozen else ObjT(impl_class)
        self._params(plan, function.args, info.module, info.filename, self_type)
        if kind == 'classmethod':
            plan.params = plan.params[1:]
            plan.class_binding = (function.args.args[0].arg, cls)
        return self._add_plan(plan)

    def request_nested(self, parent: Plan, function: ast.FunctionDef) -> Plan:
        key = ('nested', id(function))
        plan = self.plans.get(key)
        if plan is not None:
            return self.reach(plan)
        plan = Plan(key, 'nested', function.name, parent.module, parent.filename, function, parent.owner,
                    f'{parent.c_name}_n_{function.name}', parent=parent)
        self._params(plan, function.args, parent.module, parent.filename, None)
        plan.captures = self._captures(parent, function)
        return self._add_plan(plan)

    def request_lambda(self, parent: Plan, function: ast.Lambda) -> Plan:
        key = ('lambda', id(function))
        plan = self.plans.get(key)
        if plan is not None:
            return self.reach(plan)
        plan = Plan(key, 'lambda', f'lambda{function.lineno}', parent.module, parent.filename, function,
                    parent.owner, f'{parent.c_name}_l{function.lineno}_{function.col_offset}', parent=parent)
        self._params(plan, function.args, parent.module, parent.filename, None)
        plan.captures = self._captures(parent, function)
        return self._add_plan(plan)

    def _captures(self, parent: Plan, function: ast.AST) -> list[Capture]:
        """Свободные имена вложенной функции, принадлежащие объемлющим функциям."""
        own = set()
        arguments = function.args
        for argument in arguments.args + arguments.kwonlyargs + arguments.posonlyargs:
            own.add(argument.arg)
        body = function.body if isinstance(function.body, list) else [function.body]
        loads: list[str] = []
        stores: set[str] = set()
        for statement in body:
            for part in ast.walk(statement):
                if isinstance(part, ast.Name):
                    if isinstance(part.ctx, ast.Load):
                        loads.append(part.id)
                    else:
                        stores.add(part.id)
                elif isinstance(part, ast.comprehension):
                    for target in ast.walk(part.target):
                        if isinstance(target, ast.Name):
                            stores.add(target.id)
                elif isinstance(part, ast.Lambda):
                    for argument in part.args.args:
                        stores.add(argument.arg)
        parent_names = self._scope_names(parent)
        result = []
        seen = set()
        for name in loads:
            if name in own or name in stores or name in seen:
                continue
            if name in parent_names:
                seen.add(name)
                result.append(Capture(name, BOTTOM, self._captured_by_pointer(parent, function, name)))
        return result

    def _scope_names(self, plan: Plan) -> set[str]:
        names = {param.name for param in plan.params}
        node = plan.node
        body = node.body if isinstance(node.body, list) else [node.body]
        for statement in body:
            for part in ast.walk(statement):
                if isinstance(part, ast.Name) and isinstance(part.ctx, ast.Store):
                    names.add(part.id)
                elif isinstance(part, ast.FunctionDef):
                    names.add(part.name)
        names.update(capture.name for capture in plan.captures)
        return names

    @staticmethod
    def _captured_by_pointer(parent: Plan, function: ast.AST, name: str) -> bool:
        body = parent.node.body if isinstance(parent.node.body, list) else [parent.node.body]
        stores = []
        for statement in body:
            for part in ast.walk(statement):
                if isinstance(part, ast.Name) and part.id == name and isinstance(part.ctx, ast.Store):
                    stores.append(part)
        if not stores:
            return False
        if len(stores) == 1 and stores[0].lineno < function.lineno:
            return False
        return True

    def line_index(self, where: str) -> int:
        """Номер места исходника для диагностики отказов проверочной сборки."""
        if where not in self.line_numbers:
            self.line_numbers[where] = len(self.line_numbers) + 1
        return self.line_numbers[where]

    def scope_number(self, node: object) -> int:
        """Постоянный номер области видимости включения (одинаков во всех проходах)."""
        key = id(node)
        if key not in self.scope_numbers:
            self.scope_numbers[key] = (len(self.scope_numbers) + 1, node)
        return self.scope_numbers[key][0]

    def extern_by_key(self, key: tuple) -> ExternMethod:
        if key[0] == 'extern':
            return self.externs[key[1]][key[2]]
        if key[0] == 'extern_method':
            return self.extern_methods[(key[1], key[2])]
        raise KeyError(key)

    def layout_has_attribute(self, class_name: str, attr: str) -> bool:
        cell = self.fields.get((self.program.root(class_name), attr))
        if cell is not None and class_name in cell.classes:
            return True
        return False

    def refresh_captures(self, plan: Plan) -> None:
        for capture in plan.captures:
            parent = plan.parent
            found: T = BOTTOM
            while parent is not None:
                if capture.name in parent.locals:
                    found = parent.locals[capture.name]
                    break
                param = next((item for item in parent.params if item.name == capture.name), None)
                if param is not None:
                    found = param.t if not isinstance(param.t, BottomT) else (
                        param.declared if self.pessimistic and param.declared is not None else BOTTOM)
                    break
                if any(item.name == capture.name for item in parent.captures):
                    parent = parent.parent
                    continue
                break
            if found != capture.t:
                capture.t = self.join(capture.t, found)
                self.changed = True

    def analyze(self, crepr, roots: list[Plan]) -> None:
        """Проходы анализа до неподвижной точки, затем пессимистичные проходы.

        Каждый проход обходит только функции, достижимые из корней при текущих
        формах: ветви с постоянными условиями отсекаются вместе с вызовами.
        """
        from .emitter import FunctionEmitter
        for self.iteration in range(FIXPOINT_LIMIT):
            self.changed = False
            self.pass_visited = set()
            self.pass_worklist = []
            for plan in roots:
                self.reach(plan)
            index = 0
            while index < len(self.pass_worklist):
                plan = self.pass_worklist[index]
                index += 1
                self.refresh_captures(plan)
                FunctionEmitter(self, plan, False, crepr).run()
            if not self.changed:
                if self.pessimistic:
                    self.queue = list(self.pass_worklist)
                    for plan in self.queue:
                        if plan.errors:
                            raise plan.errors[0]
                    return
                self.pessimistic = True
        raise TranslationError('анализ форм не сошёлся')

    def prune_native(self, roots: list[Plan]) -> list[str]:
        """Убрать из генерации функции, вызываемые только из собственных тел (native_bodies): обход вызовов от
        корней и функций-значений не заходит в тела с заменой. Возвращает имена убранных функций."""
        live: set = set()
        stack = [plan.key for plan in roots] + [plan.key for plan in self.queue if plan.fn_id is not None]
        while stack:
            key = stack.pop()
            if key in live or key not in self.plans:
                continue
            live.add(key)
            if key not in self.native_bodies:
                stack.extend(self.plans[key].callees)
        removed = [plan.c_name for plan in self.queue if plan.key not in live and plan.kind != 'value_init']
        self.queue = [plan for plan in self.queue if plan.key in live or plan.kind == 'value_init']
        return removed

    def purity(self) -> None:
        pure = {key for key, plan in self.plans.items() if not plan.writes and plan.kind != 'lambda'}
        while True:
            following = {key for key in pure if all(callee in pure for callee in self.plans[key].callees)}
            if following == pure:
                break
            pure = following
        for key, plan in self.plans.items():
            plan.pure = key in pure


def describe(value: T) -> str:
    if isinstance(value, IntT):
        if int_empty(value):
            return 'int(?)'
        return f'int[{value.lo}..{value.hi}]'
    if isinstance(value, ObjT):
        return value.cls
    if isinstance(value, ValT):
        return f'value {value.cls}'
    if isinstance(value, TupleT):
        return 'tuple(' + ', '.join(describe(item) for item in value.items) + ')'
    if isinstance(value, ListT):
        return f'list[{describe(value.elem)}]'
    if isinstance(value, ArrayT):
        return f'tuple[{describe(value.elem)}, ...]'
    if isinstance(value, DequeT):
        return f'deque[{describe(value.elem)}]'
    if isinstance(value, SetT):
        return f'set[{describe(value.elem)}]'
    if isinstance(value, DictT):
        return f'dict[{describe(value.k)}, {describe(value.v)}]'
    if isinstance(value, OptT):
        return f'{describe(value.inner)} | None'
    if isinstance(value, FnT):
        return 'Callable[[' + ', '.join(describe(item) for item in value.params) + f'], {describe(value.ret)}]'
    return type(value).__name__.removesuffix('T').lower()
