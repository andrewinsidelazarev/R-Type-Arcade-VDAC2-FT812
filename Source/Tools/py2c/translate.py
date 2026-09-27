"""Перевод функций Python-подмножества в C с выводом диапазонов значений.

Фазы: анализ до неподвижной точки (типы локальных, интервалы значений полей,
элементов массивов, параметров и результатов; вызовы; записи), выбор ширины
C-типов по интервалам, вычисление чистоты функций, генерация. Порядок
вычислений Python сохраняется: вызов с эффектами выносится во временную
переменную, а прочитанные до него операнды фиксируются раньше него.
"""
from __future__ import annotations

import ast
import struct as struct_module
from dataclasses import dataclass, field

from .ctypes_model import (
    BOOL, I16, I32, IMAGE, OPT_INT, TARGET, U16, VOID, ArrayType, BoolType, BufferType,
    ClassType, CType, ImageType, IntType, OptionalIntType, TargetType,
    TranslationError, TupleType, VoidType, is_int_like,
)
from .heap import Heap
from .intervals import (
    BOOL_RANGE, NEGATED, SWAPPED, TOP, Interval, binary, refine_compare, type_for, union_all,
    widen_threshold,
)
from .program import ClassInfo, Program

BUILTIN_EXCEPTIONS = {'RuntimeError', 'ValueError', 'IndexError', 'AssertionError'}
C_KEYWORDS = frozenset('''auto break case char const continue default do double else enum
extern float for goto if inline int long register restrict return short signed sizeof static
struct switch typedef union unsigned void volatile while _Bool _Complex _Imaginary'''.split())
COMPARE_SYMBOLS = {'Eq': '==', 'NotEq': '!=', 'Lt': '<', 'LtE': '<=', 'Gt': '>', 'GtE': '>='}
I16_RANGE = Interval(-32768, 32767)
U16_RANGE = Interval(0, 65535)
BITS16_RANGE = Interval(-32768, 65535)
U8_RANGE = Interval(0, 255)
WIDEN_AFTER = 6
FIXPOINT_LIMIT = 80


def cname(name: str) -> str:
    """Имя локальной переменной или параметра в C без конфликта с ключевыми словами."""
    return f'py2c_kw_{name}' if name in C_KEYWORDS else name


def range_of_type(value_type: CType) -> Interval:
    if isinstance(value_type, IntType):
        return Interval(value_type.minimum, value_type.maximum)
    if isinstance(value_type, BoolType):
        return BOOL_RANGE
    return TOP


@dataclass
class Value:
    ctype: CType
    code: str
    interval: Interval | None = None      # диапазон целого значения
    source: str = ''                      # текст Python-выражения для `is not None`
    origins: frozenset = frozenset()      # происхождение массива/буфера
    length: int | None = None             # точная длина локального кортежа
    cwidth: CType | None = None           # C-тип выражения code для целых

    @property
    def nonnegative(self) -> bool:
        return self.interval is not None and self.interval.lo >= 0


@dataclass
class FunctionPlan:
    owner: str                # имя класса или модуля
    name: str
    kind: str                 # method / property / staticmethod / function
    node: ast.FunctionDef
    filename: str
    module: str
    class_info: ClassInfo | None
    c_name: str
    params: list[tuple[str, CType]] = field(default_factory=list)
    returns: CType = VOID
    locals: dict[str, CType] = field(default_factory=dict)
    callees: set[tuple[str, str]] = field(default_factory=set)
    writes: bool = False
    pure: bool = False
    lines: list[str] = field(default_factory=list)
    temps: dict[str, CType] = field(default_factory=dict)
    # Интервалы и происхождения, накопленные анализом.
    local_intervals: dict[str, Interval] = field(default_factory=dict)
    local_origins: dict[str, frozenset] = field(default_factory=dict)
    local_lengths: dict[str, int | None] = field(default_factory=dict)
    param_intervals: dict[str, Interval] = field(default_factory=dict)
    param_origins: dict[str, frozenset] = field(default_factory=dict)
    return_interval: Interval | None = None
    return_origins: frozenset = frozenset()
    explicit_params: dict[str, IntType] = field(default_factory=dict)


class Translator:
    """Сборка всей транслируемой части программы в один C-модуль."""

    def __init__(self, program: Program, heap: Heap) -> None:
        self.program = program
        self.heap = heap
        self.plans: dict[tuple[str, str], FunctionPlan] = {}
        self.queue: list[FunctionPlan] = []
        self.membership: dict[tuple[int, ...], str] = {}
        self.const_arrays: dict[int, tuple[str, ArrayType, tuple]] = {}
        self.raise_messages: list[str] = []
        self.iteration = 0
        # После сходимости неизвестные интервалы считаются int32 и анализ повторяется.
        self.pessimistic = False

    # --- план функций --------------------------------------------------------

    def request_method(self, class_name: str, name: str, node: ast.AST,
                       filename: str) -> FunctionPlan:
        found = self.program.find_method(class_name, name)
        if found is None:
            raise TranslationError(f'нет метода {class_name}.{name}', node, filename)
        info, method = found
        key = (info.name, name)
        if key not in self.plans:
            kind = info.method_kind(name)
            plan = FunctionPlan(info.name, name, kind, method, info.filename, info.module,
                                info, f'{info.name}_{name.lstrip("_")}'
                                if not name.startswith('__') else f'{info.name}_{name.strip("_")}')
            if name.startswith('_') and not name.startswith('__'):
                plan.c_name = f'{info.name}__{name.lstrip("_")}'
            self._signature(plan)
            self.plans[key] = plan
            self.queue.append(plan)
        return self.plans[key]

    def request_function(self, module: str, name: str, node: ast.AST,
                         filename: str) -> FunctionPlan:
        key = (module, name)
        if key not in self.plans:
            function = self.program.modules[module].functions.get(name)
            if function is None:
                raise TranslationError(f'нет функции {module}.{name}', node, filename)
            short = module.rsplit('.', 1)[-1]
            plan = FunctionPlan(module, name, 'function', function.node, function.filename,
                                module, None, f'{short}__{name.lstrip("_")}')
            self._signature(plan)
            self.plans[key] = plan
            self.queue.append(plan)
        return self.plans[key]

    def _signature(self, plan: FunctionPlan) -> None:
        arguments = plan.node.args
        if (arguments.vararg or arguments.kwarg or arguments.kwonlyargs or
                arguments.posonlyargs or arguments.defaults):
            raise TranslationError('сигнатура с *args/**kwargs/умолчаниями не поддержана',
                                   plan.node, plan.filename)
        names = list(arguments.args)
        if plan.kind in ('method', 'property'):
            if not names or names[0].arg != 'self':
                raise TranslationError('метод без явного self', plan.node, plan.filename)
            names = names[1:]
            plan.params.append(('self', ClassType(plan.owner)))
        for argument in names:
            if argument.annotation is None:
                raise TranslationError(f'параметр {argument.arg} без аннотации',
                                       argument, plan.filename)
            value_type = self.heap.parse_annotation(argument.annotation, plan.filename)
            if isinstance(value_type, ImageType):
                # Изображения приходят из данных; параметр Surface — цель вывода.
                value_type = TARGET
            if isinstance(value_type, IntType) and ast.unparse(argument.annotation) != 'int':
                plan.explicit_params[argument.arg] = value_type
            plan.params.append((argument.arg, value_type))
        if plan.node.returns is None:
            raise TranslationError('функция без аннотации результата', plan.node, plan.filename)
        text = ast.unparse(plan.node.returns)
        plan.returns = VOID if text == 'None' else self.heap.parse_annotation(plan.node.returns,
                                                                             plan.filename)
        for _, value_type in plan.params:
            self.heap._register(value_type)
        self.heap._register(plan.returns)

    def translate(self, roots: list[tuple[str, str]]) -> None:
        for class_name, method in roots:
            self.request_method(class_name, method, None, '')
        # Анализ до неподвижной точки: новые функции, интервалы значений и
        # суженные по ним типы требуют повторного прохода. Интервалы только
        # растут; не сходящиеся после WIDEN_AFTER проходов расширяются до int32.
        previous = None
        for self.iteration in range(FIXPOINT_LIMIT):
            for plan in list(self.queue):
                FunctionEmitter(self, plan, emit=False).run()
            self.finalize_types()
            state = self.analysis_state()
            if state == previous:
                if self.pessimistic:
                    break
                self.pessimistic = True
            previous = state
        else:
            raise TranslationError('анализ типов не сошёлся')
        self._purity()
        for plan in self.queue:
            FunctionEmitter(self, plan, emit=True).run()

    def analysis_state(self) -> tuple:
        heap = self.heap
        return (tuple((key, tuple(plan.params), tuple(sorted(plan.locals.items(), key=str)),
                       plan.returns, tuple(sorted(plan.local_intervals.items())),
                       tuple(sorted(plan.param_intervals.items())), plan.return_interval,
                       tuple(sorted((k, tuple(sorted(v))) for k, v in plan.local_origins.items())),
                       tuple(sorted((k, tuple(sorted(v))) for k, v in plan.param_origins.items())))
                      for key, plan in self.plans.items()),
                tuple(sorted(heap.field_intervals.items())),
                tuple(sorted(heap.element_intervals.items(), key=repr)),
                tuple(sorted((k, v) for k, v in heap.origin_lengths.items()), ),
                tuple(sorted((k, tuple(sorted(v.items()))) for k, v in heap.fields.items())))

    def grow(self, previous: Interval | None, new: Interval | None) -> Interval | None:
        """Объединить накопленный интервал с новым; после предела итераций
        расширяется до int32 только интервал, который всё ещё растёт."""
        if new is None:
            return previous
        merged = new if previous is None else previous.union(new)
        if previous is not None and merged == previous:
            return previous
        if self.iteration >= WIDEN_AFTER:
            # Растущий интервал расширяется до ближайших границ 2^k - 1 / -2^k.
            widened = widen_threshold(merged)
            return widened if widened != previous else range_of_type(type_for(merged))
        return merged

    def finalize_types(self) -> None:
        """Сузить типы полей, элементов, параметров, локальных и результатов по интервалам."""
        heap = self.heap
        # Массивы, разделяющие локальную/параметр, получают общий интервал элементов.
        for plan in self.queue:
            for origins in list(plan.local_origins.values()) + list(plan.param_origins.values()):
                heap.merge_origin_intervals(origins)
        for (class_name, attribute), interval in list(heap.field_intervals.items()):
            current = heap.fields[class_name][attribute]
            if isinstance(current, IntType):
                narrowed = type_for(interval)
                explicit = heap.explicit_widths.get((class_name, attribute))
                if explicit is not None and not interval.within(explicit.minimum, explicit.maximum):
                    raise TranslationError(f'{class_name}.{attribute}: значения {interval.lo}…{interval.hi} '
                                           f'не помещаются в объявленный {explicit.c()}')
                heap.fields[class_name][attribute] = narrowed
        for origin, interval in list(heap.element_intervals.items()):
            if origin[0] != 'f':
                continue
            _, class_name, attribute, depth = origin
            current = heap.fields[class_name][attribute]
            narrowed = type_for(interval)
            explicit = heap.explicit_widths.get((class_name, attribute))
            if explicit is not None and not interval.within(explicit.minimum, explicit.maximum):
                raise TranslationError(f'{class_name}.{attribute}: элементы {interval.lo}…{interval.hi} '
                                       f'не помещаются в объявленный {explicit.c()}')
            if depth == 0 and isinstance(current, ArrayType) and isinstance(current.element, IntType):
                heap.fields[class_name][attribute] = ArrayType(narrowed, current.mutable)
            elif (depth == 1 and isinstance(current, ArrayType) and isinstance(current.element, ArrayType)
                  and isinstance(current.element.element, IntType)):
                inner = ArrayType(narrowed, current.element.mutable)
                heap.fields[class_name][attribute] = ArrayType(inner, current.mutable)
            heap._register(heap.fields[class_name][attribute])
        for plan in self.queue:
            for position, (name, value_type) in enumerate(plan.params):
                if isinstance(value_type, IntType) and name in plan.param_intervals:
                    interval = plan.param_intervals[name]
                    explicit = plan.explicit_params.get(name)
                    if explicit is not None and not interval.within(explicit.minimum, explicit.maximum):
                        raise TranslationError(f'{plan.owner}.{plan.name}: аргумент {name} '
                                               f'{interval.lo}…{interval.hi} не помещается в {explicit.c()}',
                                               plan.node, plan.filename)
                    plan.params[position] = (name, type_for(interval))
                elif isinstance(value_type, ArrayType) and isinstance(value_type.element, (IntType, ImageType)) \
                        and name in plan.param_origins:
                    element = heap.element_type_of(plan.param_origins[name], value_type)
                    if element is not None:
                        plan.params[position] = (name, ArrayType(element, value_type.mutable))
                        heap._register(plan.params[position][1])
            for name, value_type in list(plan.locals.items()):
                if isinstance(value_type, IntType) and name in plan.local_intervals:
                    plan.locals[name] = type_for(plan.local_intervals[name])
                elif isinstance(value_type, ArrayType) and name in plan.local_origins:
                    element = heap.element_type_of(plan.local_origins[name], value_type)
                    if element is not None:
                        plan.locals[name] = ArrayType(element, value_type.mutable)
                        heap._register(plan.locals[name])
            if isinstance(plan.returns, IntType) and plan.return_interval is not None:
                plan.returns = type_for(plan.return_interval)
            elif isinstance(plan.returns, ArrayType) and plan.return_origins:
                element = heap.element_type_of(plan.return_origins, plan.returns)
                if element is not None:
                    plan.returns = ArrayType(element, plan.returns.mutable)
                    heap._register(plan.returns)

    def _purity(self) -> None:
        pure = {key for key, plan in self.plans.items() if not plan.writes}
        while True:
            following = {key for key in pure
                         if all(callee in pure for callee in self.plans[key].callees)}
            if following == pure:
                break
            pure = following
        for key, plan in self.plans.items():
            plan.pure = key in pure
        self._check_recursion()

    def _check_recursion(self) -> None:
        state: dict[tuple[str, str], int] = {}

        def visit(key: tuple[str, str]) -> None:
            if state.get(key) == 1:
                plan = self.plans[key]
                raise TranslationError(f'рекурсия через {plan.owner}.{plan.name} не поддержана',
                                       plan.node, plan.filename)
            if state.get(key) == 2:
                return
            state[key] = 1
            for callee in self.plans[key].callees:
                visit(callee)
            state[key] = 2

        for key in self.plans:
            visit(key)

    # --- константы ---------------------------------------------------------

    def membership_function(self, values: frozenset, node: ast.AST, filename: str) -> str:
        items = tuple(sorted(values))
        if any(type(item) is not int or not I32.holds(item) for item in items):
            raise TranslationError('множество должно содержать только int32', node, filename)
        if items not in self.membership:
            self.membership[items] = f'py2c_in_set{len(self.membership) + 1}'
        return self.membership[items]

    def constant_array(self, value: tuple, node: ast.AST, filename: str) -> Value:
        if id(value) not in self.const_arrays:
            array_type = self.heap.constant_type(value, 'константа', node, filename)
            if not isinstance(array_type, ArrayType) or not isinstance(array_type.element, IntType):
                raise TranslationError('модульный кортеж должен состоять из int', node, filename)
            symbol = f'py2c_c{len(self.const_arrays) + 1}'
            self.const_arrays[id(value)] = (symbol, array_type, value)
            origin = ('c', id(value))
            self.heap.element_intervals[origin] = Interval(min(value), max(value))
            self.heap.origin_lengths[origin] = (len(value), True)
        symbol, array_type, _ = self.const_arrays[id(value)]
        return Value(array_type, f'(&{symbol})', origins=frozenset({('c', id(value))}),
                     length=len(value))


class FunctionEmitter:
    """Анализ или генерация одной функции."""

    def __init__(self, translator: Translator, plan: FunctionPlan, emit: bool) -> None:
        self.t = translator
        self.plan = plan
        self.emit = emit
        self.lines: list[str] = []
        self.indent = 1
        self.temp_counter = 0
        self.param_names = {name for name, _ in plan.params}
        self.assigned = self._assigned_names()
        # Выражения `int | None`, доказанно не None в текущей ветви.
        self.present: set[str] = set()
        # Уточнения интервалов локальных переменных по условиям ветвей/циклов.
        self.refinements: list[dict[str, Interval]] = [{}]

    # --- утилиты -------------------------------------------------------------

    def error(self, message: str, node: ast.AST) -> TranslationError:
        return TranslationError(f'{self.plan.owner}.{self.plan.name}: {message}', node,
                                self.plan.filename)

    def line(self, text: str) -> None:
        if self.emit:
            self.lines.append('    ' * self.indent + text)

    def temp(self, value_type: CType) -> str:
        self.temp_counter += 1
        name = f'py2c_t{self.temp_counter}'
        self.plan.temps[name] = value_type
        return name

    def _assigned_names(self) -> set[str]:
        names = set()
        for node in ast.walk(self.plan.node):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                names.add(node.id)
        return names - self.param_names

    def run(self) -> None:
        body = self.plan.node.body
        if (body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            body = body[1:]
        self.statements(body)
        if self.emit:
            self.plan.lines = self.lines

    # --- интервалы -------------------------------------------------------------

    def refined(self, name: str, interval: Interval | None) -> Interval | None:
        for scope in self.refinements:
            refinement = scope.get(name)
            if refinement is not None:
                if interval is None:
                    interval = refinement
                else:
                    narrowed = interval.intersect(refinement)
                    interval = narrowed if narrowed is not None else interval
        return interval

    def kill_refinement(self, name: str) -> None:
        for scope in self.refinements:
            scope.pop(name, None)

    def condition_refinements(self, node: ast.expr, truth: bool) -> dict[str, Interval]:
        """Уточнения по истинному (или ложному) условию: сравнения имён и их `and`."""
        result: dict[str, Interval] = {}
        if isinstance(node, ast.BoolOp):
            if (truth and isinstance(node.op, ast.And)) or (not truth and isinstance(node.op, ast.Or)):
                for item in node.values:
                    for name, interval in self.condition_refinements(item, truth).items():
                        current = result.get(name)
                        merged = interval if current is None else current.intersect(interval)
                        if merged is not None:
                            result[name] = merged
            return result
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return self.condition_refinements(node.operand, not truth)
        if isinstance(node, ast.Compare) and len(node.ops) == 1:
            op = type(node.ops[0]).__name__
            if op not in COMPARE_SYMBOLS:
                return result
            if not truth:
                op = NEGATED[op]
                if op == 'NotEq':
                    return result
            left, right = node.left, node.comparators[0]
            for name_node, other_node, operator in ((left, right, op), (right, left, SWAPPED[op])):
                if isinstance(name_node, ast.Name) and self.is_local(name_node.id):
                    other = self.static_interval(other_node)
                    if other is None:
                        continue
                    base = self.name_interval(name_node.id)
                    if base is None:
                        base = TOP
                    refined = refine_compare(operator, base, other)
                    if refined is not None:
                        result[name_node.id] = refined
        return result

    def is_local(self, name: str) -> bool:
        return name in self.param_names or name in self.assigned

    def name_interval(self, name: str) -> Interval | None:
        """Накопленный интервал имени; None — ещё не известен в этом проходе."""
        if name in self.param_names:
            value_type = dict(self.plan.params)[name]
            interval = self.plan.param_intervals.get(name)
            if interval is None and isinstance(value_type, BoolType):
                interval = BOOL_RANGE
            if interval is None and self.strict and is_int_like(value_type):
                interval = range_of_type(value_type)
            return interval
        interval = self.plan.local_intervals.get(name)
        if interval is None and self.strict and name in self.plan.locals:
            interval = range_of_type(self.plan.locals[name])
        return interval

    @property
    def strict(self) -> bool:
        """Неизвестный интервал считается int32: генерация или пессимистичная фаза."""
        return self.emit or self.t.pessimistic

    def static_interval(self, node: ast.expr) -> Interval | None:
        """Интервал выражения без генерации и без эффектов (константы, имена, поля)."""
        if isinstance(node, ast.Constant) and type(node.value) is int:
            return Interval.of(node.value)
        if isinstance(node, ast.Name):
            if self.is_local(node.id):
                return self.refined(node.id, self.name_interval(node.id))
            module = self.t.program.modules[self.plan.module].python
            value = getattr(module, node.id, None)
            if type(value) is int:
                return Interval.of(value)
            return None
        if isinstance(node, ast.BinOp):
            left = self.static_interval(node.left)
            right = self.static_interval(node.right)
            if left is None or right is None:
                return None
            constant = node.right.value if isinstance(node.right, ast.Constant) else None
            return binary(type(node.op).__name__, left, right, constant)
        if isinstance(node, ast.Attribute):
            owner = self.static_type_or_none(node.value)
            if isinstance(owner, ClassType):
                found = self.t.program.find_method(owner.name, node.attr)
                if found is None:
                    return self.t.heap.field_interval(owner.name, node.attr)
        return None

    # --- типы значений -------------------------------------------------------

    def int_value(self, value: Value, node: ast.AST) -> Value:
        """Целое значение с известным C-типом кода (Optional только после доказательства)."""
        if isinstance(value.ctype, OptionalIntType):
            if (value.source and value.source in self.present) or not self.emit:
                interval = value.interval if value.interval is not None or not self.strict else TOP
                return Value(I32, f'{value.code}.value', interval, cwidth=I32)
            raise self.error(f'чтение int | None без доказательства is not None: {value.source}', node)
        if isinstance(value.ctype, (IntType, BoolType)):
            return value
        raise self.error(f'ожидалось целое, есть {value.ctype}', node)

    def cast(self, value: Value, target: IntType, node: ast.AST) -> str:
        """Код значения в виде C-типа target (проверенный на ПК переход к узкому типу)."""
        value = self.int_value(value, node)
        width = value.cwidth or value.ctype
        if isinstance(width, BoolType):
            return value.code if target == U16 or target == I16 else f'(({target.c()}){value.code})'
        if width == target:
            return value.code
        interval = value.interval or range_of_type(width)
        if interval.within(target.minimum, target.maximum):
            return f'(({target.c()}){value.code})'
        if target.bits == 32 or not self.emit:
            return f'(({target.c()}){value.code})'
        # Значение шире цели: допустимо только при доказанном интервале.
        raise self.error(f'значение {interval.lo}…{interval.hi} не помещается в {target.c()}', node)

    def as_int(self, value: Value, node: ast.AST) -> str:
        """Код значения как int32 (для вызовов рантайма)."""
        return self.cast(value, I32, node)

    def as_test(self, value: Value, node: ast.AST) -> str:
        if isinstance(value.ctype, BoolType):
            return value.code
        if isinstance(value.ctype, IntType):
            return f'({value.code} != 0)'
        if isinstance(value.ctype, ArrayType):
            return f'({value.code}->length != 0)'
        if isinstance(value.ctype, BufferType):
            return f'({value.code}->length != 0)'
        raise self.error(f'истинность {value.ctype} не поддержана', node)

    def store_int(self, target_type: CType, value: Value, node: ast.AST) -> str:
        """Преобразование значения к типу поля/переменной с проверкой на ПК."""
        value = self.int_value(value, node)
        width = value.cwidth or value.ctype
        if isinstance(target_type, IntType):
            if width == target_type:
                return value.code
            interval = value.interval or range_of_type(width)
            if self.emit and not interval.within(target_type.minimum, target_type.maximum):
                raise self.error(f'значение {interval.lo}…{interval.hi} не помещается в '
                                 f'{target_type.c()}', node)
            return f'PY2C_TO_{target_type.key().upper()}({value.code})'
        if isinstance(target_type, BoolType):
            if not isinstance(value.ctype, BoolType):
                raise self.error('bool-переменной присваивается не bool', node)
            return value.code
        return value.code

    def common_width(self, values: list[Value], node: ast.AST) -> IntType:
        """Общий C-тип для сравнения/выбора: вмещает все интервалы."""
        intervals = [value.interval or range_of_type(value.cwidth or value.ctype) for value in values]
        if all(item.within(I16_RANGE.lo, I16_RANGE.hi) for item in intervals):
            return I16
        if all(item.within(U16_RANGE.lo, U16_RANGE.hi) for item in intervals):
            return U16
        return I32

    def arithmetic_width(self, result: Interval, operands: list[Value]) -> IntType:
        """Ширина модульной 16-битной арифметики или int32."""
        patterns = [value.interval or range_of_type(value.cwidth or value.ctype) for value in operands]
        if all(item.within(BITS16_RANGE.lo, BITS16_RANGE.hi) for item in patterns):
            if result.within(I16_RANGE.lo, I16_RANGE.hi):
                return I16
            if result.within(U16_RANGE.lo, U16_RANGE.hi):
                return U16
        return I32

    @staticmethod
    def op_macro(width: IntType) -> str:
        return {'i16': 'PY2C_I16', 'u16': 'PY2C_U16'}.get(width.key(), 'PY2C_I32')

    # --- выражения ----------------------------------------------------------

    def expr(self, node: ast.expr) -> Value:
        method = getattr(self, 'expr_' + type(node).__name__, None)
        if method is None:
            raise self.error(f'выражение {type(node).__name__} не поддержано: {ast.unparse(node)}', node)
        return method(node)

    def expr_Constant(self, node: ast.Constant) -> Value:
        if type(node.value) is bool:
            return Value(BOOL, '1' if node.value else '0', BOOL_RANGE, cwidth=BOOL)
        if type(node.value) is int:
            if not I32.holds(node.value):
                raise self.error('константа вне int32', node)
            return self.constant_value(node.value)
        raise self.error(f'константа {node.value!r} не поддержана', node)

    @staticmethod
    def constant_value(value: int) -> Value:
        interval = Interval.of(value)
        width = type_for(interval)
        suffix = 'L' if width.bits == 32 else ''
        return Value(width, f'{value}{suffix}', interval, cwidth=width)

    def expr_Name(self, node: ast.Name) -> Value:
        name = node.id
        if name in self.param_names:
            value_type = dict(self.plan.params)[name]
            interval = self.refined(name, self.name_interval(name)) if is_int_like(value_type) else None
            return Value(value_type, cname(name), interval, name,
                         self.plan.param_origins.get(name, frozenset()), cwidth=value_type)
        if name in self.assigned:
            if name not in self.plan.locals:
                if self.emit:
                    raise self.error(f'переменная {name} без типа', node)
                return Value(I32, cname(name), self.refined(name, TOP if self.strict else None), name,
                             cwidth=I32)
            value_type = self.plan.locals[name]
            interval = None
            if is_int_like(value_type):
                interval = self.refined(name, self.name_interval(name))
                if isinstance(value_type, BoolType):
                    interval = BOOL_RANGE
            return Value(value_type, cname(name), interval, name,
                         self.plan.local_origins.get(name, frozenset()),
                         self.plan.local_lengths.get(name), cwidth=value_type)
        module = self.t.program.modules[self.plan.module].python
        if hasattr(module, name):
            return self.module_constant(getattr(module, name), name, node)
        raise self.error(f'неизвестное имя {name}', node)

    def module_constant(self, value: object, name: str, node: ast.AST) -> Value:
        if type(value) is bool:
            return Value(BOOL, '1' if value else '0', BOOL_RANGE, cwidth=BOOL)
        if type(value) is int:
            if not I32.holds(value):
                raise self.error(f'константа {name} вне int32', node)
            return self.constant_value(value)
        if isinstance(value, tuple):
            return self.t.constant_array(value, node, self.plan.filename)
        raise self.error(f'модульная константа {name} типа {type(value).__name__} не поддержана', node)

    def expr_Attribute(self, node: ast.Attribute) -> Value:
        owner = self.expr(node.value)
        if not isinstance(owner.ctype, ClassType):
            raise self.error(f'атрибут у {owner.ctype} не поддержан: {ast.unparse(node)}', node)
        class_name = owner.ctype.name
        found = self.t.program.find_method(class_name, node.attr)
        if found is not None:
            info, _ = found
            if info.method_kind(node.attr) != 'property':
                raise self.error(f'ссылка на метод без вызова: {ast.unparse(node)}', node)
            plan = self.t.request_method(class_name, node.attr, node, self.plan.filename)
            self.plan.callees.add((plan.owner, plan.name))
            return self.call_plan(plan, [owner], [], node)
        heap = self.t.heap
        field_type = heap.field_type(class_name, node.attr, node, self.plan.filename)
        code = f'{owner.code}->{node.attr}'
        if isinstance(field_type, (IntType, BoolType)):
            interval = BOOL_RANGE if isinstance(field_type, BoolType) else heap.field_interval(class_name, node.attr)
            return Value(field_type, code, interval, ast.unparse(node), cwidth=field_type)
        if isinstance(field_type, OptionalIntType):
            return Value(field_type, code, heap.field_intervals.get((class_name, node.attr)),
                         ast.unparse(node))
        origins = frozenset()
        if isinstance(field_type, (ArrayType, BufferType)):
            origins = frozenset({('f', class_name, node.attr, 0)})
            heap.ensure_origin(('f', class_name, node.attr, 0), class_name, node.attr, 0)
        return Value(field_type, code, None, ast.unparse(node), origins)

    def expr_Subscript(self, node: ast.Subscript) -> Value:
        if isinstance(node.slice, ast.Slice):
            raise self.error('срезы не поддержаны', node)
        if (isinstance(node.value, ast.Call) and self.call_name(node.value) == 'struct.unpack_from'
                and isinstance(node.slice, ast.Constant) and type(node.slice.value) is int):
            values = self.unpack_from(node.value)
            if not 0 <= node.slice.value < len(values):
                raise self.error('индекс результата unpack_from вне формата', node)
            return values[node.slice.value]
        container = self.expr(node.value)
        mark = self.mark()
        index = self.expr(node.slice)
        self.fix_left([container], mark)
        return self.element(container, index, node)

    def index_in_range(self, container: Value, index: Value) -> bool:
        """Доказано: 0 <= index < длина для всех происхождений контейнера."""
        if index.interval is None or index.interval.lo < 0:
            return False
        length = self.min_length(container)
        return length is not None and index.interval.hi < length

    def min_length(self, container: Value) -> int | None:
        if container.length is not None:
            return container.length
        if not container.origins:
            return None
        lengths = []
        for origin in container.origins:
            info = self.t.heap.origin_lengths.get(origin)
            if info is None or not info[1]:
                return None
            lengths.append(info[0])
        return min(lengths) if lengths else None

    def single_page(self, container: Value) -> bool:
        """Буфер помещается в одну 16-КБ страницу (или резидентен)."""
        if not container.origins:
            return False
        for origin in container.origins:
            info = self.t.heap.origin_lengths.get(origin)
            if info is None:
                return False
            maximum = self.t.heap.origin_max_lengths.get(origin, info[0])
            if maximum > 16384:
                return False
        return True

    def element_origins(self, container: Value) -> frozenset:
        return frozenset((origin[0], origin[1], origin[2], origin[3] + 1) if origin[0] == 'f' else origin
                         for origin in container.origins)

    def element(self, container: Value, index: Value, node: ast.AST) -> Value:
        index = self.int_value(index, node)
        if isinstance(container.ctype, ArrayType):
            element = container.ctype.element
            origins = self.element_origins(container)
            if isinstance(element, IntType):
                interval = self.t.heap.elements_interval(container.origins, element)
            elif isinstance(element, BoolType):
                interval = BOOL_RANGE
            else:
                interval = None
            if self.index_in_range(container, index):
                width = self.common_width([index], node)
                code = f'PY2C_ELEM({container.code}, {self.cast(index, width, node)})'
            else:
                suffix = '' if index.nonnegative else '_any'
                code = f'py2c_get_{container.ctype.key()}{suffix}({container.code}, {self.as_int(index, node)})'
            if isinstance(element, ArrayType):
                # Вложенный массив: длины внутренних массивов по происхождению.
                return Value(element, code, None, '', origins)
            return Value(element, code, interval, '', origins if isinstance(element, (ArrayType, BufferType))
                         else frozenset(), cwidth=element if isinstance(element, (IntType, BoolType)) else None)
        if isinstance(container.ctype, BufferType):
            if self.index_in_range(container, index) and self.single_page(container):
                width = self.common_width([index], node)
                code = f'PY2C_BUF_ELEM({container.code}, {self.cast(index, width, node)})'
            else:
                suffix = '' if index.nonnegative else '_any'
                code = f'py2c_buf_get{suffix}({container.code}, {self.as_int(index, node)})'
            return Value(IntType(8, False), code, U8_RANGE, cwidth=IntType(8, False))
        raise self.error(f'индексирование {container.ctype} не поддержано', node)

    def expr_BinOp(self, node: ast.BinOp) -> Value:
        left = self.expr(node.left)
        mark = self.mark()
        right = self.expr(node.right)
        self.fix_left([left], mark)
        return self.binop(left, node.op, right, node.right, node)

    def binop(self, left: Value, operator: ast.operator, right: Value,
              right_node: ast.expr, node: ast.AST) -> Value:
        left = self.int_value(left, node)
        right = self.int_value(right, node)
        op = type(operator).__name__
        constant = (right_node.value if isinstance(right_node, ast.Constant) and
                    type(right_node.value) is int else None)
        unknown = left.interval is None or right.interval is None
        a_interval = left.interval or range_of_type(left.cwidth or left.ctype)
        b_interval = right.interval or range_of_type(right.cwidth or right.ctype)
        if op == 'FloorDiv' and constant is not None and constant > 0 and constant & (constant - 1) == 0:
            op, right, constant = 'RShift', self.constant_value(constant.bit_length() - 1), constant.bit_length() - 1
            b_interval = right.interval
        if op == 'Mod' and constant is not None and constant > 0 and constant & (constant - 1) == 0:
            op, right, constant = 'BitAnd', self.constant_value(constant - 1), constant - 1
            b_interval = right.interval
        result = binary(op, a_interval, b_interval, constant)
        known = None if unknown else result
        if op in ('Add', 'Sub', 'Mult', 'BitAnd', 'BitOr', 'BitXor', 'LShift'):
            if op == 'LShift' and (constant is None or not 0 <= constant < 32):
                return Value(I32, f'PY2C_SHL({self.as_int(left, node)}, {self.as_int(right, node)})', TOP,
                             cwidth=I32)
            symbol = {'Add': '+', 'Sub': '-', 'Mult': '*', 'BitAnd': '&', 'BitOr': '|',
                      'BitXor': '^', 'LShift': '<<'}[op]
            width = self.arithmetic_width(result, [left, right])
            code = f'{self.op_macro(width)}({left.code}, {symbol}, {right.code})'
            return Value(width, code, known, cwidth=width)
        if op == 'RShift':
            if constant is None or constant < 0:
                return Value(I32, f'py2c_shr({self.as_int(left, node)}, {self.as_int(right, node)})',
                             known, cwidth=I32)
            width = (I16 if a_interval.within(I16_RANGE.lo, I16_RANGE.hi)
                     else U16 if a_interval.within(U16_RANGE.lo, U16_RANGE.hi) else I32)
            code = f'{self.op_macro(width)}({left.code}, >>, {min(constant, 31)})'
            return Value(width, code, known, cwidth=width)
        if op == 'FloorDiv':
            return Value(I32, f'py2c_floordiv({self.as_int(left, node)}, {self.as_int(right, node)})',
                         known, cwidth=I32)
        if op == 'Mod':
            return Value(I32, f'py2c_mod({self.as_int(left, node)}, {self.as_int(right, node)})',
                         known, cwidth=I32)
        raise self.error(f'операция {op} не поддержана (float запрещён)', node)

    def expr_UnaryOp(self, node: ast.UnaryOp) -> Value:
        operand = self.expr(node.operand)
        op = type(node.op).__name__
        if op == 'Not':
            return Value(BOOL, f'(!{self.as_test(operand, node)})', BOOL_RANGE, cwidth=BOOL)
        operand = self.int_value(operand, node)
        unknown = operand.interval is None
        interval = operand.interval or range_of_type(operand.cwidth or operand.ctype)
        if op == 'USub':
            result = Interval(-interval.hi, -interval.lo).clamp()
            width = self.arithmetic_width(result, [operand])
            return Value(width, f'{self.op_macro(width)}(0, -, {operand.code})',
                         None if unknown else result, cwidth=width)
        if op == 'UAdd':
            return operand
        if op == 'Invert':
            result = Interval(-interval.hi - 1, -interval.lo - 1).clamp()
            width = self.arithmetic_width(result, [operand])
            return Value(width, f'{self.op_macro(width)}(-1, -, {operand.code})',
                         None if unknown else result, cwidth=width)
        raise self.error(f'унарная операция {op} не поддержана', node)

    def expr_BoolOp(self, node: ast.BoolOp) -> Value:
        values = [self.expr(item) for item in node.values]
        if not all(isinstance(value.ctype, BoolType) for value in values):
            raise self.error('and/or над не-bool значениями вне условия не поддержаны', node)
        if any(self.has_effects(item) for item in node.values[1:]):
            raise self.error('and/or с эффектами в правом операнде требует ветвления', node)
        symbol = ' && ' if isinstance(node.op, ast.And) else ' || '
        return Value(BOOL, '(' + symbol.join(value.code for value in values) + ')', BOOL_RANGE,
                     cwidth=BOOL)

    def expr_Compare(self, node: ast.Compare) -> Value:
        operands = [node.left, *node.comparators]
        if len(operands) > 2 and any(self.has_effects(item) for item in operands):
            raise self.error('цепочка сравнений с эффектами не поддержана', node)
        parts = []
        left_value = self.expr(node.left)
        for op, right_node in zip(node.ops, node.comparators):
            parts.append(self.compare_pair(left_value, op, right_node, node))
            if len(node.ops) > 1:
                left_value = self.expr(right_node)
        return Value(BOOL, '(' + ' && '.join(parts) + ')', BOOL_RANGE, cwidth=BOOL)

    def compare_pair(self, left: Value, op: ast.cmpop, right_node: ast.expr, node: ast.AST) -> str:
        name = type(op).__name__
        if name in ('In', 'NotIn'):
            constant = self.static_value(right_node)
            if isinstance(constant, (frozenset, set)):
                function = self.t.membership_function(frozenset(constant), node, self.plan.filename)
                code = f'{function}({self.as_int(left, node)})'
                return code if name == 'In' else f'(!{code})'
            raise self.error('in поддержан только для константного множества int', node)
        if name in ('Is', 'IsNot'):
            if not (isinstance(right_node, ast.Constant) and right_node.value is None):
                raise self.error('is поддержан только для None', node)
            if not isinstance(left.ctype, OptionalIntType):
                raise self.error('is None у не-Optional значения', node)
            return f'({left.code}.present == 0)' if name == 'Is' else f'({left.code}.present != 0)'
        mark = self.mark()
        right = self.expr(right_node)
        self.fix_left([left], mark)
        symbol = COMPARE_SYMBOLS.get(name)
        if symbol is None:
            raise self.error(f'сравнение {name} не поддержано', node)
        if isinstance(left.ctype, ClassType) and isinstance(right.ctype, ClassType) and symbol in ('==', '!='):
            return f'({left.code} {symbol} {right.code})'
        left = self.int_value(left, node)
        right = self.int_value(right, node)
        width = self.common_width([left, right], node)
        return f'({self.cast(left, width, node)} {symbol} {self.cast(right, width, node)})'

    def expr_IfExp(self, node: ast.IfExp) -> Value:
        if self.has_effects(node.body) or self.has_effects(node.orelse):
            raise self.error('условное выражение с эффектами в ветвях не поддержано', node)
        test = self.as_test(self.expr(node.test), node.test)
        body = self.expr(node.body)
        other = self.expr(node.orelse)
        if is_int_like(body.ctype) and is_int_like(other.ctype):
            body = self.int_value(body, node)
            other = self.int_value(other, node)
            interval = None
            if body.interval is not None and other.interval is not None:
                interval = body.interval.union(other.interval)
            width = self.common_width([body, other], node)
            return Value(width, f'({test} ? {self.cast(body, width, node)} : {self.cast(other, width, node)})',
                         interval, cwidth=width)
        if body.ctype == other.ctype:
            return Value(body.ctype, f'({test} ? {body.code} : {other.code})',
                         origins=body.origins | other.origins)
        raise self.error('ветви условного выражения разных типов', node)

    def expr_Call(self, node: ast.Call) -> Value:
        if node.keywords:
            raise self.error('именованные аргументы не поддержаны', node)
        name = self.call_name(node)
        if name in ('min', 'max'):
            values = [self.int_value(value, node) for value in self.arguments(node.args)]
            if len(values) < 2:
                raise self.error(f'{name} требует минимум два аргумента', node)
            intervals = [value.interval or range_of_type(value.cwidth) for value in values]
            if name == 'min':
                interval = Interval(min(item.lo for item in intervals), min(item.hi for item in intervals))
            else:
                interval = Interval(max(item.lo for item in intervals), max(item.hi for item in intervals))
            if any(value.interval is None for value in values):
                interval = None
            width = self.common_width(values, node)
            code = self.cast(values[0], width, node)
            for value in values[1:]:
                code = f'py2c_{name}_{width.key()}({code}, {self.cast(value, width, node)})'
            return Value(width, code, interval, cwidth=width)
        if name == 'abs':
            value = self.int_value(self.expr(node.args[0]), node)
            interval = value.interval or range_of_type(value.cwidth)
            result = Interval(0 if interval.lo <= 0 <= interval.hi else min(abs(interval.lo), abs(interval.hi)),
                              max(abs(interval.lo), abs(interval.hi))).clamp()
            width = self.common_width([value, Value(I32, '', result)], node)
            return Value(width, f'py2c_abs_{width.key()}({self.cast(value, width, node)})',
                         None if value.interval is None else result, cwidth=width)
        if name == 'bool':
            value = self.expr(node.args[0])
            return Value(BOOL, f'(uint8_t){self.as_test(value, node)}', BOOL_RANGE, cwidth=BOOL)
        if name == 'int':
            value = self.int_value(self.expr(node.args[0]), node)
            if isinstance(value.ctype, BoolType):
                return Value(IntType(8, False), f'((uint8_t){value.code})', BOOL_RANGE, cwidth=IntType(8, False))
            return value
        if name == 'len':
            value = self.expr(node.args[0])
            if isinstance(value.ctype, (ArrayType, BufferType)):
                length = self.min_length(value)
                interval = Interval.of(length) if length is not None else Interval(0, 65535)
                if isinstance(value.ctype, BufferType) and length is None:
                    return Value(I32, f'((int32_t){value.code}->length)', TOP, cwidth=I32)
                return Value(U16, f'((uint16_t){value.code}->length)', interval, cwidth=U16)
            raise self.error(f'len от {value.ctype} не поддержан', node)
        if name == 'struct.unpack_from':
            values = self.unpack_from(node)
            if len(values) != 1:
                raise self.error('многозначный unpack_from допустим только при распаковке', node)
            raise self.error('unpack_from без индекса результата', node)
        if name == 'struct.pack_into':
            self.pack_into(node)
            return Value(VOID, '')
        if isinstance(node.func, ast.Attribute):
            if node.func.attr in ('clear', 'append'):
                return self.list_method(node)
            owner = self.expr(node.func.value)
            if isinstance(owner.ctype, TargetType):
                return self.target_call(node)
            if isinstance(owner.ctype, ClassType):
                plan = self.t.request_method(owner.ctype.name, node.func.attr, node,
                                             self.plan.filename)
                self.plan.callees.add((plan.owner, plan.name))
                values = self.arguments(node.args, [owner])
                return self.call_plan(plan, values[:1], values[1:], node)
        if isinstance(node.func, ast.Name):
            module = self.t.program.modules[self.plan.module]
            if node.func.id in module.functions:
                plan = self.t.request_function(self.plan.module, node.func.id, node, self.plan.filename)
                self.plan.callees.add((plan.owner, plan.name))
                return self.call_plan(plan, [], self.arguments(node.args), node)
        raise self.error(f'вызов {ast.unparse(node.func)} не поддержан', node)

    def arguments(self, nodes: list[ast.expr], earlier: list[Value] | None = None) -> list[Value]:
        """Аргументы слева направо; ранние чтения фиксируются перед эффектами поздних."""
        values = list(earlier or [])
        for item in nodes:
            mark = self.mark()
            value = self.expr(item)
            self.fix_left(values, mark)
            values.append(value)
        return values

    def call_name(self, node: ast.Call) -> str:
        return ast.unparse(node.func)

    def call_plan(self, plan: FunctionPlan, receiver: list[Value], arguments: list[Value],
                  node: ast.AST) -> Value:
        values = receiver + arguments
        if len(values) != len(plan.params):
            raise self.error(f'{plan.owner}.{plan.name}: ожидалось {len(plan.params)} аргументов', node)
        codes = []
        for position, ((name, param_type), value) in enumerate(zip(plan.params, values)):
            if (isinstance(param_type, ArrayType) and param_type.element.key() == 'narrow' and
                    isinstance(value.ctype, ArrayType) and isinstance(value.ctype.element, IntType)):
                # Ширина элементов параметра-кортежа берётся у фактического аргумента.
                param_type = ArrayType(value.ctype.element, param_type.mutable)
                plan.params[position] = (name, param_type)
                self.t.heap._register(param_type)
            if not self.emit:
                # Накопление интервалов и происхождений аргументов.
                if is_int_like(param_type) and is_int_like(value.ctype) and value.interval is not None:
                    plan.param_intervals[name] = self.t.grow(plan.param_intervals.get(name), value.interval)
                elif isinstance(param_type, (ArrayType, BufferType)) and value.origins:
                    plan.param_origins[name] = plan.param_origins.get(name, frozenset()) | value.origins
            codes.append(self.convert(value, param_type, node))
        call = f'{plan.c_name}({", ".join(codes)})'
        result_type = plan.returns
        if isinstance(result_type, VoidType):
            return Value(VOID, call)
        interval = plan.return_interval if is_int_like(result_type) else None
        if isinstance(result_type, BoolType):
            interval = BOOL_RANGE
        if interval is None and is_int_like(result_type):
            interval = range_of_type(result_type)
        width = result_type if is_int_like(result_type) else None
        if not self.emit or plan.pure:
            return Value(result_type, call, interval, '', plan.return_origins, cwidth=width)
        name = self.temp(result_type)
        self.line(f'{name} = {call};')
        return Value(result_type, name, interval, '', plan.return_origins, cwidth=width)

    def convert(self, value: Value, target: CType, node: ast.AST) -> str:
        if isinstance(target, IntType):
            return self.store_int(target, value, node)
        if isinstance(target, BoolType):
            if isinstance(value.ctype, BoolType):
                return value.code
            raise self.error('ожидалось bool', node)
        if isinstance(target, OptionalIntType):
            if isinstance(value.ctype, OptionalIntType):
                if value.source and value.source in self.present:
                    return f'py2c_some({value.code}.value)'
                return value.code
            if is_int_like(value.ctype):
                return f'py2c_some({self.as_int(value, node)})'
            raise self.error('ожидалось int | None', node)
        if isinstance(target, ArrayType) and isinstance(value.ctype, ArrayType):
            if target.element != value.ctype.element:
                if self.emit:
                    raise self.error(f'массив {value.ctype.element} вместо {target.element}', node)
            return value.code
        if target == value.ctype or (isinstance(target, BufferType) and isinstance(value.ctype, BufferType)):
            return value.code
        if isinstance(target, TargetType):
            return '0'
        raise self.error(f'нельзя передать {value.ctype} как {target}', node)

    # --- struct -------------------------------------------------------------

    def struct_format(self, node: ast.AST, format_node: ast.expr) -> list[tuple[str, int]]:
        if not (isinstance(format_node, ast.Constant) and isinstance(format_node.value, str)):
            raise self.error('формат struct должен быть литералом', node)
        text = format_node.value
        if not text.startswith('<'):
            raise self.error('поддержан только явный little-endian формат', node)
        fields = []
        for char in text[1:]:
            if char == 'H':
                fields.append(('u16', 2))
            elif char == 'h':
                fields.append(('i16', 2))
            elif char == 'B':
                fields.append(('u8', 1))
            elif char == 'b':
                fields.append(('i8', 1))
            else:
                raise self.error(f'поле формата {char!r} не поддержано', node)
        if struct_module.calcsize(text) != sum(size for _, size in fields):
            raise self.error('размер формата не совпал с CPython', node)
        return fields

    @staticmethod
    def field_kind_type(kind: str) -> IntType:
        return {'u16': U16, 'i16': I16, 'u8': IntType(8, False), 'i8': IntType(8, True)}[kind]

    def unpack_from(self, node: ast.Call) -> list[Value]:
        if len(node.args) != 3:
            raise self.error('unpack_from(format, buffer, offset)', node)
        fields = self.struct_format(node, node.args[0])
        buffer, offset = self.arguments(node.args[1:3])
        if not isinstance(buffer.ctype, BufferType):
            raise self.error('unpack_from ожидает bytes/bytearray', node)
        offset = self.int_value(offset, node)
        total = sum(size for _, size in fields)
        offset_interval = offset.interval or range_of_type(offset.cwidth)
        length = self.min_length(buffer)
        in_range = (length is not None and offset_interval.lo >= 0 and offset_interval.hi + total <= length
                    and self.single_page(buffer))
        if len(fields) == 1:
            kind = fields[0][0]
            result_type = self.field_kind_type(kind)
            if in_range:
                width = self.common_width([offset], node)
                code = f'PY2C_BUF_{kind.upper()}LE({buffer.code}, {self.cast(offset, width, node)})'
            else:
                code = f'py2c_buf_{kind}le({buffer.code}, {self.as_int(offset, node)})'
            return [Value(result_type, code, range_of_type(result_type), cwidth=result_type)]
        if not self.emit:
            return [Value(self.field_kind_type(kind), 'py2c_field', range_of_type(self.field_kind_type(kind)),
                          cwidth=self.field_kind_type(kind)) for kind, _ in fields]
        # Все поля читаются сразу, до следующих эффектов, как в CPython.
        values = []
        position = 0
        if in_range:
            width = self.common_width([offset, Value(I32, '', Interval(offset_interval.lo, offset_interval.hi + total))], node)
            base = self.temp(width)
            self.line(f'{base} = {self.cast(offset, width, node)};')
            for kind, size in fields:
                result_type = self.field_kind_type(kind)
                captured = self.temp(result_type)
                self.line(f'{captured} = PY2C_BUF_{kind.upper()}LE({buffer.code}, {base} + {position});')
                values.append(Value(result_type, captured, range_of_type(result_type), cwidth=result_type))
                position += size
            return values
        base = self.temp(I32)
        self.line(f'{base} = py2c_buf_require({buffer.code}, {self.as_int(offset, node)}, {total});')
        for kind, size in fields:
            result_type = self.field_kind_type(kind)
            captured = self.temp(result_type)
            self.line(f'{captured} = py2c_buf_{kind}le_raw({buffer.code}, {base} + {position}L);')
            values.append(Value(result_type, captured, range_of_type(result_type), cwidth=result_type))
            position += size
        return values

    def pack_into(self, node: ast.Call) -> None:
        fields = self.struct_format(node, node.args[0])
        if len(node.args) != 3 + len(fields):
            raise self.error('число значений pack_into не совпадает с форматом', node)
        self.plan.writes = True
        evaluated = self.arguments(node.args[1:])
        buffer, offset, values = evaluated[0], evaluated[1], evaluated[2:]
        if not isinstance(buffer.ctype, BufferType) or not buffer.ctype.mutable:
            raise self.error('pack_into ожидает bytearray', node)
        offset = self.int_value(offset, node)
        values = [self.int_value(value, node) for value in values]
        if not self.emit:
            return
        total = sum(size for _, size in fields)
        offset_interval = offset.interval or range_of_type(offset.cwidth)
        length = self.min_length(buffer)
        in_range = (length is not None and offset_interval.lo >= 0 and offset_interval.hi + total <= length
                    and self.single_page(buffer))
        values_in_range = all(
            (value.interval or range_of_type(value.cwidth)).within(self.field_kind_type(kind).minimum,
                                                                   self.field_kind_type(kind).maximum)
            for (kind, _), value in zip(fields, values))
        holder = self.temp(buffer.ctype)
        self.line(f'{holder} = {buffer.code};')
        codes = []
        for (kind, _), value in zip(fields, values):
            result_type = self.field_kind_type(kind) if values_in_range else I32
            name = self.temp(result_type)
            self.line(f'{name} = {self.cast(value, result_type, node)};')
            if not values_in_range:
                # CPython проверяет диапазон каждого значения до записи.
                self.line(f'py2c_require_{kind}({name});')
            codes.append(name)
        if in_range:
            width = self.common_width([offset, Value(I32, '', Interval(offset_interval.lo, offset_interval.hi + total))], node)
            base = self.temp(width)
            self.line(f'{base} = {self.cast(offset, width, node)};')
            position = 0
            for (kind, size), code in zip(fields, codes):
                self.line(f'PY2C_BUF_SET_{kind.upper()}LE({holder}, {base} + {position}, {code});')
                position += size
            return
        base = self.temp(I32)
        self.line(f'{base} = py2c_buf_require({holder}, {self.as_int(offset, node)}, {total});')
        position = 0
        for (kind, size), code in zip(fields, codes):
            self.line(f'py2c_buf_set_{kind}le_raw({holder}, {base} + {position}L, {code});')
            position += size

    # --- списки и цель вывода ----------------------------------------------

    def list_method(self, node: ast.Call) -> Value:
        owner = self.expr(node.func.value)
        if not isinstance(owner.ctype, ArrayType) or not owner.ctype.mutable:
            raise self.error(f'{node.func.attr} у неизменяемого значения', node)
        self.plan.writes = True
        for origin in owner.origins:
            self.t.heap.variable_length(origin)
        if node.func.attr == 'clear':
            if node.args:
                raise self.error('clear() без аргументов', node)
            return Value(VOID, f'{owner.code}->length = 0')
        owner, value = self.arguments(node.args[:1], [owner])
        self.record_element_store(owner, value)
        code = self.convert(value, owner.ctype.element, node)
        return Value(VOID, f'py2c_append_{owner.ctype.key()}({owner.code}, {code})')

    def record_element_store(self, container: Value, value: Value) -> None:
        if self.emit or not isinstance(container.ctype, ArrayType):
            return
        if is_int_like(container.ctype.element) and is_int_like(value.ctype) and value.interval is not None:
            heap = self.t.heap
            for origin in self.element_origins(container):
                heap.element_intervals[origin] = self.t.grow(heap.element_intervals.get(origin), value.interval)

    def target_call(self, node: ast.Call) -> Value:
        if node.func.attr != 'blit' or len(node.args) != 2:
            raise self.error('у цели вывода поддержан только blit(image, (x, y))', node)
        self.plan.writes = True
        position = node.args[1]
        if not isinstance(position, ast.Tuple) or len(position.elts) != 2:
            raise self.error('позиция blit должна быть кортежем (x, y)', node)
        image, x, y = self.arguments([node.args[0], *position.elts])
        if not isinstance(image.ctype, ImageType):
            raise self.error('blit ожидает изображение ресурса', node)
        x = self.int_value(x, node)
        y = self.int_value(y, node)
        return Value(VOID, f'py2c_blit({image.code}, {self.cast(x, I16, node)}, {self.cast(y, I16, node)})')

    # --- порядок вычислений -------------------------------------------------

    def has_effects(self, node: ast.AST) -> bool:
        """Может ли вычисление узла выполнить запись (вызов нечистой функции)."""
        if not self.emit:
            # Чистота функций известна только после анализа всей программы.
            return False
        for part in ast.walk(node):
            if isinstance(part, ast.Call):
                name = ast.unparse(part.func)
                if name in ('min', 'max', 'abs', 'bool', 'int', 'len', 'struct.unpack_from'):
                    continue
                plan = self.resolve_call_plan(part)
                if plan is None or not plan.pure:
                    return True
            elif isinstance(part, ast.Attribute):
                plan = self.resolve_property_plan(part)
                if plan is not None and not plan.pure:
                    return True
        return False

    def resolve_call_plan(self, node: ast.Call) -> FunctionPlan | None:
        if isinstance(node.func, ast.Attribute):
            owner = self.static_type_or_none(node.func.value)
            if isinstance(owner, ClassType):
                found = self.t.program.find_method(owner.name, node.func.attr)
                if found is not None:
                    return self.t.plans.get((found[0].name, node.func.attr))
            return None
        if isinstance(node.func, ast.Name):
            return self.t.plans.get((self.plan.module, node.func.id))
        return None

    def resolve_property_plan(self, node: ast.Attribute) -> FunctionPlan | None:
        owner = self.static_type_or_none(node.value)
        if isinstance(owner, ClassType):
            found = self.t.program.find_method(owner.name, node.attr)
            if found is not None:
                return self.t.plans.get((found[0].name, node.attr))
        return None

    def static_type(self, node: ast.expr) -> CType:
        """Тип выражения без генерации (для анализа эффектов)."""
        if isinstance(node, ast.Name):
            if node.id in self.param_names:
                return dict(self.plan.params)[node.id]
            if node.id in self.plan.locals:
                return self.plan.locals[node.id]
            raise self.error('нет типа', node)
        if isinstance(node, ast.Attribute):
            owner = self.static_type(node.value)
            if isinstance(owner, ClassType):
                found = self.t.program.find_method(owner.name, node.attr)
                if found is not None:
                    plan = self.t.plans.get((found[0].name, node.attr))
                    if plan is not None:
                        return plan.returns
                return self.t.heap.field_type(owner.name, node.attr, node, self.plan.filename)
        if isinstance(node, ast.Subscript):
            owner = self.static_type(node.value)
            if isinstance(owner, ArrayType):
                return owner.element
        raise self.error('нет типа', node)

    def static_type_or_none(self, node: ast.expr) -> CType | None:
        try:
            return self.static_type(node)
        except TranslationError:
            return None

    def mark(self) -> int:
        return len(self.lines)

    @staticmethod
    def stable(code: str) -> bool:
        """Код не читает состояние объектов: литерал, локальная или временная."""
        stripped = code.strip('()')
        for prefix in ('(int32_t)', '(int16_t)', '(uint16_t)', '(uint8_t)', '(int8_t)'):
            if stripped.startswith(prefix):
                stripped = stripped[len(prefix):].strip('()')
        return stripped.replace('_', 'a').isalnum() or stripped.rstrip('L').lstrip('-').isdigit()

    def fix_left(self, earlier: list[Value], mark: int) -> None:
        """Если позднее подвыражение породило строки, зафиксировать ранние чтения.

        Строки после отметки — вызовы и захваты, которые CPython выполняет
        после вычисления ранних операндов. Их чтения состояния копируются во
        временные переменные перед этими строками.
        """
        if not self.emit or len(self.lines) == mark:
            return
        inserted = []
        for value in earlier:
            if not value.code or self.stable(value.code) or isinstance(value.ctype, VoidType):
                continue
            value_type = value.cwidth if is_int_like(value.ctype) and value.cwidth else value.ctype
            if isinstance(value.ctype, OptionalIntType):
                value_type = OPT_INT
            name = self.temp(value_type)
            inserted.append('    ' * self.indent + f'{name} = {value.code};')
            value.code = name
            value.ctype = value_type
        self.lines[mark:mark] = inserted

    def expr_Tuple(self, node: ast.Tuple) -> Value:
        """Локальный однородный кортеж целых: массив во фрейме функции."""
        values = []
        for item in node.elts:
            mark = self.mark()
            value = self.expr(item)
            self.fix_left(values, mark)
            if not is_int_like(value.ctype):
                raise self.error('локальный кортеж поддержан только из целых', node)
            values.append(self.int_value(value, node))
        origin = ('t', self.plan.owner, self.plan.name, node.lineno, node.col_offset)
        interval = union_all(value.interval or range_of_type(value.cwidth) for value in values) or TOP
        heap = self.t.heap
        if not self.emit:
            if all(value.interval is not None for value in values):
                heap.element_intervals[origin] = self.t.grow(heap.element_intervals.get(origin), interval)
            heap.origin_lengths[origin] = (len(values), True)
        element = type_for(heap.element_intervals.get(origin, interval))
        array_type = ArrayType(element, False)
        heap._register(array_type)
        if not self.emit:
            return Value(array_type, 'py2c_tuple', origins=frozenset({origin}), length=len(values))
        name = self.temp(array_type)
        self.plan.temps[name] = ('tuple', len(values), element)
        for index, value in enumerate(values):
            self.line(f'{name}_data[{index}] = {self.store_int(element, value, node)};')
        self.line(f'{name}.data = {name}_data; {name}.length = {len(values)}; '
                  f'{name}.capacity = {len(values)}; {name}.page = 0;')
        return Value(array_type, f'(&{name})', origins=frozenset({origin}), length=len(values))

    def static_value(self, node: ast.expr) -> object:
        if isinstance(node, ast.Name) and node.id not in self.assigned and node.id not in self.param_names:
            module = self.t.program.modules[self.plan.module].python
            if hasattr(module, node.id):
                return getattr(module, node.id)
        if isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id == 'self' and self.plan.class_info:
                value = getattr(self.plan.class_info.python, node.attr, None)
                if isinstance(value, (frozenset, set)):
                    return value
        raise self.error(f'нужна константа: {ast.unparse(node)}', node)

    # --- инструкции ---------------------------------------------------------

    def statements(self, nodes: list[ast.stmt]) -> None:
        for node in nodes:
            method = getattr(self, 'stmt_' + type(node).__name__, None)
            if method is None:
                raise self.error(f'инструкция {type(node).__name__} не поддержана', node)
            self.line(f'/* {self.plan.filename.rsplit(chr(92), 1)[-1]}:{node.lineno} */')
            method(node)

    def stmt_Pass(self, node: ast.Pass) -> None:
        return

    def stmt_Expr(self, node: ast.Expr) -> None:
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            return
        value = self.expr(node.value)
        if value.code:
            self.line(f'{value.code};' if not value.code.endswith(';') else value.code)

    def record_local(self, name: str, value: Value, node: ast.AST) -> CType:
        """Тип локальной переменной: накопление интервалов/происхождений при анализе."""
        plan = self.plan
        if self.emit:
            return plan.locals[name]
        value_type = value.ctype
        if isinstance(value_type, OptionalIntType):
            raise self.error(f'локальная переменная {name} типа int | None не поддержана', node)
        if is_int_like(value_type):
            if isinstance(value_type, BoolType):
                current = plan.locals.get(name)
                if current is not None and not isinstance(current, BoolType):
                    raise self.error(f'переменной {name} присваиваются bool и int', node)
                plan.locals[name] = BOOL
                plan.local_intervals[name] = BOOL_RANGE
                return BOOL
            if value.interval is None:
                plan.locals.setdefault(name, I32)
                return plan.locals[name]
            merged = self.t.grow(plan.local_intervals.get(name), value.interval)
            plan.local_intervals[name] = merged
            plan.locals[name] = type_for(merged)
            return plan.locals[name]
        current = plan.locals.get(name)
        if isinstance(value_type, ArrayType):
            plan.local_origins[name] = plan.local_origins.get(name, frozenset()) | value.origins
            if name in plan.local_lengths and plan.local_lengths[name] != value.length:
                plan.local_lengths[name] = None
            else:
                plan.local_lengths.setdefault(name, value.length)
            if current is not None and isinstance(current, ArrayType):
                if current.element != value_type.element and not (
                        is_int_like(current.element) and is_int_like(value_type.element)):
                    raise self.error(f'переменной {name} присваиваются массивы разных типов', node)
                plan.locals[name] = ArrayType(current.element, current.mutable or value_type.mutable)
            else:
                plan.locals[name] = value_type
            return plan.locals[name]
        if isinstance(value_type, BufferType):
            plan.local_origins[name] = plan.local_origins.get(name, frozenset()) | value.origins
            plan.locals[name] = BufferType(current.mutable and value_type.mutable) if isinstance(
                current, BufferType) else value_type
            return plan.locals[name]
        if current is not None and current != value_type:
            raise self.error(f'переменной {name} присваиваются значения разных типов', node)
        plan.locals[name] = value_type
        return value_type

    def assign_name(self, name: str, value: Value, node: ast.AST) -> None:
        if name in self.param_names:
            raise self.error(f'присваивание параметру {name} не поддержано', node)
        target_type = self.record_local(name, value, node)
        self.kill_refinement(name)
        if isinstance(target_type, (IntType, BoolType)):
            self.line(f'{cname(name)} = {self.store_int(target_type, value, node)};')
            return
        self.line(f'{cname(name)} = {self.convert(value, target_type, node)};')

    def assign_target(self, target: ast.expr, value: Value, node: ast.AST) -> None:
        if isinstance(target, ast.Name):
            self.assign_name(target.id, value, node)
            return
        if isinstance(target, ast.Attribute):
            self.plan.writes = True
            mark = self.mark()
            owner = self.expr(target.value)
            self.fix_left([value], mark)
            if not isinstance(owner.ctype, ClassType):
                raise self.error('запись атрибута не у объекта', target)
            heap = self.t.heap
            field_type = heap.field_type(owner.ctype.name, target.attr, target, self.plan.filename)
            if (not self.emit and (is_int_like(field_type) or isinstance(field_type, OptionalIntType))
                    and (is_int_like(value.ctype) or isinstance(value.ctype, OptionalIntType))):
                # Optional → int: интервал значения `.value` (в пессимистичной фазе int32).
                probe = (self.int_value(value, node)
                         if isinstance(value.ctype, OptionalIntType) and is_int_like(field_type) else value)
                if probe.interval is not None:
                    key = (owner.ctype.name, target.attr)
                    heap.field_intervals[key] = self.t.grow(heap.field_intervals.get(key), probe.interval)
            if not self.emit and isinstance(field_type, (ArrayType, BufferType)):
                raise self.error('замена массива или буфера в поле не поддержана (правьте на месте)', node)
            self.line(f'{owner.code}->{target.attr} = {self.convert(value, field_type, node)};')
            return
        if isinstance(target, ast.Subscript):
            self.plan.writes = True
            mark = self.mark()
            container = self.expr(target.value)
            index_mark = self.mark()
            index = self.expr(target.slice)
            self.fix_left([container], index_mark)
            self.fix_left([value], mark)
            self.store_element(container, index, value, node)
            return
        raise self.error(f'цель присваивания {ast.unparse(target)} не поддержана', target)

    def store_element(self, container: Value, index: Value, value: Value, node: ast.AST) -> None:
        index = self.int_value(index, node)
        if isinstance(container.ctype, ArrayType):
            self.record_element_store(container, value)
            element = container.ctype.element
            if isinstance(element, (ArrayType, BufferType)):
                raise self.error('замена вложенного массива не поддержана', node)
            code = self.convert(value, element, node)
            if self.index_in_range(container, index):
                width = self.common_width([index], node)
                self.line(f'PY2C_ELEM({container.code}, {self.cast(index, width, node)}) = {code};')
            else:
                suffix = '' if index.nonnegative else '_any'
                self.line(f'py2c_set_{container.ctype.key()}{suffix}({container.code}, '
                          f'{self.as_int(index, node)}, {code});')
            return
        if isinstance(container.ctype, BufferType):
            value = self.int_value(value, node)
            value_interval = value.interval or range_of_type(value.cwidth)
            if (self.index_in_range(container, index) and self.single_page(container)
                    and value_interval.within(0, 255)):
                width = self.common_width([index], node)
                self.line(f'PY2C_BUF_ELEM({container.code}, {self.cast(index, width, node)}) = '
                          f'{self.cast(value, IntType(8, False), node)};')
            else:
                suffix = '' if index.nonnegative else '_any'
                self.line(f'py2c_buf_set{suffix}({container.code}, {self.as_int(index, node)}, '
                          f'{self.as_int(value, node)});')
            return
        raise self.error(f'запись элемента {container.ctype} не поддержана', node)

    def stmt_Assign(self, node: ast.Assign) -> None:
        if len(node.targets) != 1:
            raise self.error('цепочка присваиваний не поддержана', node)
        target = node.targets[0]
        if isinstance(target, ast.Tuple):
            self.unpack_assign(target, node.value, node)
            return
        if isinstance(node.value, ast.Constant) and node.value.value is None:
            self.assign_none(target, node)
            return
        value = self.expr(node.value)
        if isinstance(value.ctype, VoidType):
            raise self.error('присваивание результата без значения', node)
        self.assign_target(target, self.capture(value, node) if isinstance(target, ast.Subscript) else value, node)
        self.forget(target)
        if isinstance(target, ast.Attribute) and isinstance(value.ctype, IntType):
            owner_type = self.static_type_or_none(target.value)
            if isinstance(owner_type, ClassType):
                field_type = self.t.heap.field_type(owner_type.name, target.attr, target, self.plan.filename)
                if isinstance(field_type, OptionalIntType):
                    self.present.add(ast.unparse(target))

    def assign_none(self, target: ast.expr, node: ast.AST) -> None:
        if not isinstance(target, ast.Attribute):
            raise self.error('None присваивается только полю int | None', node)
        self.plan.writes = True
        owner = self.expr(target.value)
        if not isinstance(owner.ctype, ClassType):
            raise self.error('запись None не в поле объекта', node)
        field_type = self.t.heap.field_type(owner.ctype.name, target.attr, target, self.plan.filename)
        if not isinstance(field_type, OptionalIntType):
            raise self.error(f'поле {target.attr} не int | None', node)
        self.line(f'{owner.code}->{target.attr}.present = 0; {owner.code}->{target.attr}.value = 0;')
        self.forget(target)

    def stmt_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is None:
            return
        self.stmt_Assign(ast.copy_location(ast.Assign(targets=[node.target], value=node.value), node))

    def capture(self, value: Value, node: ast.AST) -> Value:
        """Вычислить значение до индекса цели, как CPython (правая часть первой)."""
        if not self.emit or not value.code or isinstance(value.ctype, VoidType):
            return value
        if isinstance(value.ctype, (IntType, BoolType)):
            width = value.cwidth or value.ctype
            name = self.temp(width)
            self.line(f'{name} = {value.code};')
            return Value(width, name, value.interval, value.source, cwidth=width)
        return value

    def unpack_assign(self, target: ast.Tuple, value_node: ast.expr, node: ast.AST) -> None:
        names = target.elts
        if isinstance(value_node, ast.Tuple):
            if len(value_node.elts) != len(names):
                raise self.error('число элементов распаковки не совпадает', node)
            captured = []
            for item in value_node.elts:
                value = self.expr(item)
                if self.emit:
                    if is_int_like(value.ctype):
                        value = self.int_value(value, item)
                        width = value.cwidth or value.ctype
                        name = self.temp(width)
                        self.line(f'{name} = {value.code};')
                        value = Value(width, name, value.interval, cwidth=width)
                    else:
                        name = self.temp(value.ctype)
                        self.line(f'{name} = {value.code};')
                        value = Value(value.ctype, name, origins=value.origins, length=value.length)
                captured.append(value)
            for name_node, value in zip(names, captured):
                self.assign_target(name_node, value, node)
            return
        if isinstance(value_node, ast.Call) and self.call_name(value_node) == 'struct.unpack_from':
            values = self.unpack_from(value_node)
            if len(values) != len(names):
                raise self.error('распаковка unpack_from: число полей не совпадает', node)
            for name_node, value in zip(names, values):
                self.assign_target(name_node, value, node)
            return
        raise self.error('распаковка поддержана для литерала кортежа и struct.unpack_from', node)

    def stmt_AugAssign(self, node: ast.AugAssign) -> None:
        target = node.target
        if isinstance(target, ast.Name):
            combined = ast.copy_location(ast.BinOp(left=ast.copy_location(
                ast.Name(id=target.id, ctx=ast.Load()), node), op=node.op, right=node.value), node)
            self.assign_name(target.id, self.expr(combined), node)
            return
        if isinstance(target, ast.Attribute):
            self.plan.writes = True
            owner = self.expr(target.value)
            if not isinstance(owner.ctype, ClassType):
                raise self.error('составное присваивание атрибута не у объекта', node)
            heap = self.t.heap
            field_type = heap.field_type(owner.ctype.name, target.attr, target, self.plan.filename)
            holder = owner.code
            if self.emit and not holder.isidentifier():
                name = self.temp(owner.ctype)
                self.line(f'{name} = {holder};')
                holder = name
            current = Value(field_type, f'{holder}->{target.attr}',
                            heap.field_interval(owner.ctype.name, target.attr), cwidth=field_type)
            mark = self.mark()
            right = self.expr(node.value)
            self.fix_left([current], mark)
            result = self.binop(current, node.op, right, node.value, node)
            if not self.emit and result.interval is not None:
                key = (owner.ctype.name, target.attr)
                heap.field_intervals[key] = self.t.grow(heap.field_intervals.get(key), result.interval)
            self.line(f'{holder}->{target.attr} = {self.convert(result, field_type, node)};')
            return
        if isinstance(target, ast.Subscript):
            self.plan.writes = True
            container = self.expr(target.value)
            index = self.int_value(self.expr(target.slice), node)
            holder = container.code
            if self.emit:
                name = self.temp(container.ctype)
                self.line(f'{name} = {holder};')
                holder = name
                width = index.cwidth or index.ctype
                slot = self.temp(width)
                self.line(f'{slot} = {index.code};')
                index = Value(width, slot, index.interval, cwidth=width)
            holder_value = Value(container.ctype, holder, origins=container.origins, length=container.length)
            current = self.element(holder_value, index, node)
            mark = self.mark()
            right = self.expr(node.value)
            self.fix_left([current], mark)
            result = self.binop(current, node.op, right, node.value, node)
            self.store_element(holder_value, index, result, node)
            return
        raise self.error('цель составного присваивания не поддержана', node)

    def stmt_If(self, node: ast.If) -> None:
        present_body = present_else = None
        test_node = node.test
        if (isinstance(test_node, ast.Compare) and len(test_node.ops) == 1 and
                isinstance(test_node.ops[0], (ast.Is, ast.IsNot)) and
                isinstance(test_node.comparators[0], ast.Constant) and
                test_node.comparators[0].value is None):
            text = ast.unparse(test_node.left)
            if isinstance(test_node.ops[0], ast.IsNot):
                present_body = text
            else:
                present_else = text
        test = self.as_test(self.expr(node.test), node.test)
        saved = set(self.present)
        # Присваивания в ветви, которая не доходит до конца, не действуют после if.
        snapshot = [dict(scope) for scope in self.refinements]
        self.line(f'if ({test}) {{')
        self.indent += 1
        if present_body:
            self.present.add(present_body)
        self.refinements.append(self.condition_refinements(node.test, True))
        self.statements(node.body)
        self.refinements.pop()
        if self.terminates(node.body):
            self.refinements = [dict(scope) for scope in snapshot]
        after_body = set(self.present)
        self.present = set(saved)
        self.indent -= 1
        if node.orelse:
            self.line('} else {')
            self.indent += 1
        if present_else:
            self.present.add(present_else)
        if node.orelse:
            self.refinements.append(self.condition_refinements(node.test, False))
            self.statements(node.orelse)
            self.refinements.pop()
            if self.terminates(node.orelse):
                self.refinements = [dict(scope) for scope in snapshot]
            self.indent -= 1
        after_else = set(self.present)
        self.line('}')
        # Ветвь, которая не доходит до конца, не ограничивает знание после if.
        if self.terminates(node.body):
            self.present = after_else
            for name, interval in self.condition_refinements(node.test, False).items():
                self.refinements[-1][name] = interval
        elif node.orelse and self.terminates(node.orelse):
            self.present = after_body
            for name, interval in self.condition_refinements(node.test, True).items():
                self.refinements[-1][name] = interval
        else:
            self.present = after_body & after_else

    @staticmethod
    def terminates(body: list[ast.stmt]) -> bool:
        return bool(body) and isinstance(body[-1], (ast.Return, ast.Raise, ast.Continue, ast.Break))

    def forget(self, target: ast.expr) -> None:
        """Запись в выражение отменяет доказанное `is not None` для него и производных."""
        text = ast.unparse(target)
        self.present = {item for item in self.present
                        if item != text and not item.startswith(text + '.')}

    def stmt_While(self, node: ast.While) -> None:
        if node.orelse:
            raise self.error('while … else не поддержан', node)
        if self.has_effects(node.test):
            raise self.error('условие while с эффектами не поддержано', node)
        self.line('for (;;) {')
        self.indent += 1
        test = self.as_test(self.expr(node.test), node.test)
        self.line(f'if (!{test}) break;')
        self.refinements.append(self.condition_refinements(node.test, True))
        self.statements(node.body)
        self.refinements.pop()
        self.indent -= 1
        self.line('}')

    def stmt_For(self, node: ast.For) -> None:
        if node.orelse:
            raise self.error('for … else не поддержан', node)
        if not (isinstance(node.iter, ast.Call) and isinstance(node.iter.func, ast.Name)
                and node.iter.func.id == 'range' and not node.iter.keywords):
            raise self.error('for поддержан только по range(...)', node)
        if not isinstance(node.target, ast.Name):
            raise self.error('переменная цикла должна быть именем', node)
        loop_name = node.target.id
        for part in node.body:
            for inner in ast.walk(part):
                if isinstance(inner, ast.Name) and inner.id == loop_name and isinstance(inner.ctx, ast.Store):
                    raise self.error('присваивание переменной цикла в теле не поддержано', inner)
        arguments = [self.int_value(value, node) for value in self.arguments(node.iter.args)]
        if len(arguments) == 1:
            start, stop, step = self.constant_value(0), arguments[0], 1
        elif len(arguments) in (2, 3):
            start, stop = arguments[0], arguments[1]
            step = 1
            if len(arguments) == 3:
                step_node = node.iter.args[2]
                if isinstance(step_node, ast.UnaryOp) and isinstance(step_node.op, ast.USub) \
                        and isinstance(step_node.operand, ast.Constant):
                    step = -step_node.operand.value
                elif isinstance(step_node, ast.Constant) and type(step_node.value) is int:
                    step = step_node.value
                else:
                    raise self.error('шаг range должен быть константой', node)
                if step == 0:
                    raise self.error('нулевой шаг range', node)
        else:
            raise self.error('range с неверным числом аргументов', node)
        bounds_known = start.interval is not None and stop.interval is not None
        start_interval = start.interval or range_of_type(start.cwidth)
        stop_interval = stop.interval or range_of_type(stop.cwidth)
        # Переменная цикла хранит и конечное значение счётчика: без переполнения.
        if step > 0:
            counter_interval = Interval(start_interval.lo, max(start_interval.lo, stop_interval.hi + (step - 1)))
            body_interval = Interval(start_interval.lo, max(start_interval.lo, stop_interval.hi - 1))
        else:
            counter_interval = Interval(min(start_interval.hi, stop_interval.lo + (step + 1)), start_interval.hi)
            body_interval = Interval(min(start_interval.hi, stop_interval.lo + 1), start_interval.hi)
        counter_interval = counter_interval.clamp()
        body_interval = body_interval.clamp()
        plan = self.plan
        if not self.emit:
            if bounds_known:
                merged = self.t.grow(plan.local_intervals.get(loop_name), counter_interval)
                plan.local_intervals[loop_name] = merged
                plan.locals[loop_name] = type_for(merged)
            else:
                plan.locals.setdefault(loop_name, I32)
        counter_type = plan.locals[loop_name]
        limit = self.temp(counter_type)
        self.line(f'{limit} = {self.store_int(counter_type, stop, node)};')
        compare = '<' if step > 0 else '>'
        self.line(f'for ({cname(loop_name)} = {self.store_int(counter_type, start, node)}; '
                  f'{cname(loop_name)} {compare} {limit}; {cname(loop_name)} += {step}) {{')
        self.indent += 1
        self.kill_refinement(loop_name)
        self.refinements.append({loop_name: body_interval} if bounds_known else {})
        self.statements(node.body)
        self.refinements.pop()
        self.indent -= 1
        self.line('}')

    def stmt_Break(self, node: ast.Break) -> None:
        self.line('break;')

    def stmt_Continue(self, node: ast.Continue) -> None:
        self.line('continue;')

    def stmt_Return(self, node: ast.Return) -> None:
        plan = self.plan
        returns = plan.returns
        if node.value is None:
            if not isinstance(returns, VoidType):
                raise self.error('return без значения в функции с результатом', node)
            self.line('return;')
            return
        if isinstance(returns, TupleType):
            if not isinstance(node.value, ast.Tuple) or len(node.value.elts) != len(returns.elements):
                raise self.error('результат-кортеж должен быть литералом нужной длины', node)
            parts = []
            for element_type, item in zip(returns.elements, node.value.elts):
                value = self.expr(item)
                name = self.temp(element_type)
                self.line(f'{name} = {self.convert(value, element_type, item)};')
                parts.append(name)
            result = self.temp(returns)
            for index, part in enumerate(parts):
                self.line(f'{result}.v{index} = {part};')
            self.line(f'return {result};')
            return
        value = self.expr(node.value)
        if not self.emit:
            if is_int_like(returns) and is_int_like(value.ctype) and value.interval is not None:
                plan.return_interval = self.t.grow(plan.return_interval, value.interval)
            elif isinstance(returns, (ArrayType, BufferType)):
                plan.return_origins = plan.return_origins | value.origins
        self.line(f'return {self.convert(value, returns, node)};')

    def stmt_Raise(self, node: ast.Raise) -> None:
        exception = node.exc
        name = ast.unparse(exception.func) if isinstance(exception, ast.Call) else ast.unparse(exception)
        if name not in BUILTIN_EXCEPTIONS:
            raise self.error(f'исключение {name} не поддержано', node)
        message = ast.unparse(exception)
        if message not in self.t.raise_messages:
            self.t.raise_messages.append(message)
        index = self.t.raise_messages.index(message) + 1
        self.line(f'py2c_raise({index}); /* {message[:60].replace("*/", "")} */')
        returns = self.plan.returns
        if isinstance(returns, VoidType):
            self.line('return;')
        elif isinstance(returns, (IntType, BoolType)):
            self.line('return 0;')
        else:
            self.line(f'{{ static {returns.c()} py2c_none; return py2c_none; }}')
