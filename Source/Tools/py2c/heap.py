"""Снимок объектов CPython: типы полей и C-данные начального состояния."""
from __future__ import annotations

import ast
from dataclasses import dataclass, field

import pygame

from .ctypes_model import (
    BOOL, IMAGE, OPT_INT, ArrayType, BoolType, BufferType, ClassType, CType,
    I32, IntType, OptionalIntType, TranslationError, TupleType, WIDTH_ALIASES,
    ImageType, narrowest_int,
)
from .intervals import TOP, Interval, type_for, union_all
from .program import Program


@dataclass(frozen=True)
class NarrowInt(CType):
    """Элемент неизменяемого кортежа: ширина выбирается по фактическим значениям."""

    def c(self) -> str:
        raise TranslationError('ширина элемента ещё не выбрана')

    def key(self) -> str:
        return 'narrow'


@dataclass
class ExternalData:
    """Крупный массив или буфер: данные связываются платформой, не C-инициализатором."""

    symbol: str
    kind: str              # 'buffer' или 'array'
    element: CType | None
    length: int
    payload: bytes
    mutable: bool


@dataclass
class ImageEntry:
    index: int
    surface: pygame.Surface


class Heap:
    """Граф объектов от корней: экземпляры, использованные поля и их данные."""

    def __init__(self, program: Program, roots: dict[str, object],
                 external_threshold: int = 512) -> None:
        self.program = program
        self.roots = roots
        self.external_threshold = external_threshold
        self.instances: dict[str, list[object]] = {}
        self.fields: dict[str, dict[str, CType]] = {}
        self.images: dict[int, ImageEntry] = {}
        self.array_types: set[ArrayType] = set()
        self.tuple_types: set[TupleType] = set()
        # Интервалы значений: поля, элементы массивов по происхождению, длины.
        self.field_intervals: dict[tuple[str, str], Interval] = {}
        self.element_intervals: dict[tuple, Interval] = {}
        self.origin_lengths: dict[tuple, tuple[int, bool]] = {}
        self.origin_max_lengths: dict[tuple, int] = {}
        self.explicit_widths: dict[tuple[str, str], IntType] = {}
        self._collect()

    # --- интервалы -------------------------------------------------------------

    def field_interval(self, class_name: str, attribute: str) -> Interval:
        interval = self.field_intervals.get((class_name, attribute))
        if interval is None:
            field_type = self.fields.get(class_name, {}).get(attribute)
            if isinstance(field_type, IntType):
                return Interval(field_type.minimum, field_type.maximum)
            return TOP
        return interval

    def record_field(self, class_name: str, attribute: str, interval: Interval) -> None:
        key = (class_name, attribute)
        self.field_intervals[key] = interval.union(self.field_intervals.get(key))

    def record_element(self, origin: tuple, interval: Interval) -> None:
        self.element_intervals[origin] = interval.union(self.element_intervals.get(origin))

    def elements_interval(self, origins, element_type: CType) -> Interval:
        """Интервал элементов по всем происхождениям; без сведений — по типу."""
        result = None
        for origin in origins:
            nested = (origin[0], origin[1], origin[2], origin[3] + 1) if origin[0] == 'f' else origin
            interval = self.element_intervals.get(nested)
            if interval is None:
                return (Interval(element_type.minimum, element_type.maximum)
                        if isinstance(element_type, IntType) else TOP)
            result = interval if result is None else result.union(interval)
        if result is None:
            return (Interval(element_type.minimum, element_type.maximum)
                    if isinstance(element_type, IntType) else TOP)
        return result

    def ensure_origin(self, origin: tuple, class_name: str, attribute: str, depth: int) -> None:
        """Начальные интервалы и длины массива/буфера поля (глубина 0 или 1) из снимка."""
        if origin in self.origin_lengths:
            return
        values = [vars(instance)[attribute] for instance in self.instances.get(class_name, [])
                  if attribute in vars(instance)]
        containers = list(values)
        for _ in range(depth):
            containers = [item for container in containers for item in container]
        if not containers:
            return
        lengths = [len(container) for container in containers]
        self.origin_lengths[origin] = (min(lengths), True)
        self.origin_max_lengths[origin] = max(lengths)
        items = [item for container in containers for item in container]
        nested = (origin[0], origin[1], origin[2], origin[3] + 1)
        if items and all(type(item) is int or type(item) is bool for item in items):
            self.record_element(nested, Interval(min(items), max(items)))
        elif items and all(isinstance(item, (list, tuple)) for item in items):
            inner_lengths = [len(item) for item in items]
            self.origin_lengths[nested] = (min(inner_lengths), True)
            self.origin_max_lengths[nested] = max(inner_lengths)
            inner = [value for item in items for value in item]
            if inner and all(type(value) is int for value in inner):
                self.record_element((origin[0], origin[1], origin[2], origin[3] + 2),
                                    Interval(min(inner), max(inner)))

    def variable_length(self, origin: tuple) -> None:
        """append/clear: длина массива этого происхождения больше не постоянна."""
        info = self.origin_lengths.get(origin)
        self.origin_lengths[origin] = (0, False) if info is None else (info[0], False)

    def merge_origin_intervals(self, origins) -> None:
        """Массивы, попадающие в одну переменную, получают общий интервал элементов."""
        nested = [(origin[0], origin[1], origin[2], origin[3] + 1) if origin[0] == 'f' else origin
                  for origin in origins]
        merged = union_all(self.element_intervals.get(item) for item in nested)
        if merged is None or len(nested) < 2:
            return
        for item in nested:
            self.element_intervals[item] = merged

    def element_type_of(self, origins, current: ArrayType) -> CType | None:
        if not isinstance(current.element, IntType):
            return None
        return type_for(self.elements_interval(origins, current.element))

    # --- обход графа -------------------------------------------------------

    def _collect(self) -> None:
        seen: set[int] = set()
        stack = list(self.roots.values())
        while stack:
            value = stack.pop()
            if id(value) in seen:
                continue
            seen.add(id(value))
            info = self.program.class_of(value)
            if info is not None:
                self.instances.setdefault(info.name, []).append(value)
                stack.extend(vars(value).values())
            elif isinstance(value, (list, tuple)):
                stack.extend(value)
            elif isinstance(value, dict):
                stack.extend(value.values())

    # --- аннотации ---------------------------------------------------------

    def parse_annotation(self, node: ast.expr, filename: str) -> CType:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return self.parse_annotation(ast.parse(node.value, mode='eval').body, filename)
        text = ast.unparse(node)
        if text == 'int':
            return I32
        if text == 'bool':
            return BOOL
        if text in WIDTH_ALIASES:
            return WIDTH_ALIASES[text]
        if text == 'bytes':
            return BufferType(False)
        if text == 'bytearray':
            return BufferType(True)
        if text in ('pygame.Surface',):
            return IMAGE
        if text in ('int | None', 'None | int'):
            return OPT_INT
        if isinstance(node, ast.Name) and node.id in self.program.classes:
            return ClassType(node.id)
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
            container = node.value.id
            argument = node.slice
            if container == 'list':
                element = self.parse_annotation(argument, filename)
                # Списки изображений — ресурсы: запись в них транслятор отвергает.
                return ArrayType(element, not isinstance(element, ImageType))
            if container == 'tuple':
                if (isinstance(argument, ast.Tuple) and len(argument.elts) == 2 and
                        isinstance(argument.elts[1], ast.Constant) and
                        argument.elts[1].value is Ellipsis):
                    element = self.parse_annotation(argument.elts[0], filename)
                    if element == I32:
                        element = NarrowInt()
                    return ArrayType(element, False)
                if isinstance(argument, ast.Tuple):
                    return TupleType(tuple(self.parse_annotation(item, filename)
                                           for item in argument.elts))
        raise TranslationError(f'аннотация «{text}» не поддержана', node, filename)

    # --- типы полей ----------------------------------------------------------

    def field_type(self, class_name: str, attribute: str, node: ast.AST,
                   filename: str) -> CType:
        known = self.fields.setdefault(class_name, {})
        if attribute in known:
            return known[attribute]
        instances = self.instances.get(class_name)
        if not instances:
            raise TranslationError(f'в снимке нет экземпляров {class_name}', node, filename)
        values = []
        for instance in instances:
            if attribute not in vars(instance):
                raise TranslationError(f'{class_name}.{attribute} есть не у всех экземпляров',
                                       node, filename)
            values.append(vars(instance)[attribute])
        info = self.program.classes[class_name]
        annotation = info.annotations.get(attribute)
        where = f'{class_name}.{attribute}'
        if annotation is not None:
            declared = self.parse_annotation(annotation, info.filename)
            result = self._resolve(declared, values, where, node, filename)
            explicit = ast.unparse(annotation)
            if isinstance(declared, IntType) and explicit in WIDTH_ALIASES:
                self.explicit_widths[(class_name, attribute)] = declared
            elif (isinstance(declared, ArrayType) and isinstance(declared.element, IntType)
                  and explicit.startswith(('list[', 'tuple[')) and any(
                      alias in explicit for alias in WIDTH_ALIASES)):
                self.explicit_widths[(class_name, attribute)] = declared.element
        else:
            result = self._infer(values, where, node, filename)
        known[attribute] = result
        self._register(result)
        if isinstance(result, IntType) and all(type(value) is int for value in values):
            self.record_field(class_name, attribute, Interval(min(values), max(values)))
        return result

    def constant_type(self, value: object, where: str, node: ast.AST, filename: str) -> CType:
        """Тип модульной константы (неизменяемые значения)."""
        result = self._infer([value], where, node, filename)
        self._register(result)
        return result

    def _register(self, value_type: CType) -> None:
        if isinstance(value_type, ArrayType):
            if isinstance(value_type.element, NarrowInt):
                # Ширина выбирается позже, по фактическому аргументу.
                return
            self.array_types.add(value_type)
            self._register(value_type.element)
        elif isinstance(value_type, TupleType):
            self.tuple_types.add(value_type)
            for element in value_type.elements:
                self._register(element)

    def _resolve(self, declared: CType, values: list, where: str,
                 node: ast.AST, filename: str) -> CType:
        """Проверить значения против аннотации и доуточнить ширину кортежей."""
        if isinstance(declared, ArrayType):
            items = []
            for value in values:
                if not isinstance(value, (list, tuple)):
                    raise TranslationError(f'{where}: ожидался список/кортеж, есть {type(value)}',
                                           node, filename)
                items.extend(value)
            if isinstance(declared.element, NarrowInt):
                if any(type(item) is not int for item in items):
                    raise TranslationError(f'{where}: элементы не int', node, filename)
                return ArrayType(narrowest_int(items), declared.mutable)
            return ArrayType(self._resolve(declared.element, items, where + '[]', node, filename)
                             if items else self._check_empty(declared.element),
                             declared.mutable)
        for value in values:
            self._check_value(declared, value, where, node, filename)
        return declared

    @staticmethod
    def _check_empty(element: CType) -> CType:
        if isinstance(element, NarrowInt):
            return I32
        return element

    def _check_value(self, declared: CType, value: object, where: str,
                     node: ast.AST, filename: str) -> None:
        ok = True
        if isinstance(declared, IntType):
            ok = type(value) is int and declared.holds(value)
        elif isinstance(declared, BoolType):
            ok = type(value) is bool
        elif isinstance(declared, OptionalIntType):
            ok = value is None or (type(value) is int and I32.holds(value))
        elif isinstance(declared, BufferType):
            ok = isinstance(value, bytearray if declared.mutable else (bytes, bytearray))
        elif isinstance(declared, ImageType):
            ok = isinstance(value, pygame.Surface)
        elif isinstance(declared, ClassType):
            info = self.program.class_of(value)
            ok = info is not None and info.name == declared.name
        elif isinstance(declared, TupleType):
            ok = isinstance(value, tuple) and len(value) == len(declared.elements)
            if ok:
                for element, item in zip(declared.elements, value):
                    self._check_value(element, item, where, node, filename)
        if not ok:
            raise TranslationError(f'{where}: значение {value!r:.60} не соответствует {declared}',
                                   node, filename)

    def _infer(self, values: list, where: str, node: ast.AST, filename: str) -> CType:
        if all(type(value) is bool for value in values):
            return BOOL
        if all(type(value) is int for value in values):
            return I32
        if all(value is None or type(value) is int for value in values):
            return OPT_INT
        if all(isinstance(value, bytearray) for value in values):
            return BufferType(True)
        if all(isinstance(value, (bytes, bytearray)) for value in values):
            return BufferType(False)
        if all(isinstance(value, pygame.Surface) for value in values):
            return IMAGE
        infos = [self.program.class_of(value) for value in values]
        if infos and all(info is not None for info in infos):
            names = {info.name for info in infos}
            if len(names) == 1:
                return ClassType(names.pop())
        if all(isinstance(value, tuple) for value in values):
            items = [item for value in values for item in value]
            if items and all(type(item) is int for item in items):
                return ArrayType(narrowest_int(items), False)
            if items:
                return ArrayType(self._infer(items, where + '[]', node, filename), False)
        if all(isinstance(value, list) for value in values):
            items = [item for value in values for item in value]
            if items and all(type(item) is int for item in items):
                return ArrayType(I32, True)
            if items:
                element = self._infer(items, where + '[]', node, filename)
                return ArrayType(element, not isinstance(element, ImageType))
        kinds = sorted({type(value).__name__ for value in values})
        raise TranslationError(f'{where}: не выводится тип из значений {kinds}; '
                               'нужна аннотация', node, filename)


@dataclass
class EmittedData:
    declarations: list[str] = field(default_factory=list)
    definitions: list[str] = field(default_factory=list)
    externals: list[ExternalData] = field(default_factory=list)
    root_symbols: dict[str, str] = field(default_factory=dict)


class DataEmitter:
    """Материализация использованной части графа в C-объекты."""

    def __init__(self, heap: Heap) -> None:
        self.heap = heap
        self.symbols: dict[int, str] = {}
        self.alive: list[object] = []
        self.output = EmittedData()
        self.counter = 0
        self.image_ids: dict[int, int] = {}
        self.array_types: dict[str, ArrayType] = {}
        # Независимое от платформы описание данных в порядке определения.
        self.records: list[dict] = []

    def image_id(self, surface: pygame.Surface) -> int:
        """Номер изображения; одинаковые объекты Surface получают один номер.

        Платформа может задать готовую нумерацию (`fixed_images`): тогда
        неизвестные поверхности получают номер «не загружено» 0xFFFF.
        """
        fixed = getattr(self, 'fixed_images', None)
        if fixed is not None:
            return fixed.get(id(surface), 0xFFFF)
        if id(surface) not in self.image_ids:
            index = len(self.heap.images)
            self.heap.images[index] = ImageEntry(index, surface)
            self.image_ids[id(surface)] = index
            self.alive.append(surface)
        return self.image_ids[id(surface)]

    def _name(self, prefix: str) -> str:
        self.counter += 1
        return f'py2c_{prefix}{self.counter}'

    def emit_roots(self) -> EmittedData:
        for name, value in self.heap.roots.items():
            info = self.heap.program.class_of(value)
            if info is None:
                raise TranslationError(f'корень {name} не объект пакета')
            symbol = self.object_symbol(info.name, value, name)
            self.output.root_symbols[name] = symbol
        return self.output

    def value_initializer(self, value_type: CType, value: object, where: str) -> str:
        """C-выражение инициализатора значения данного типа."""
        if isinstance(value_type, IntType):
            if type(value) is not int or not value_type.holds(value):
                raise TranslationError(f'{where}: {value!r} вне {value_type}')
            return f'{value}' if value_type.bits < 32 else f'{value}L'
        if isinstance(value_type, BoolType):
            return '1' if value else '0'
        if isinstance(value_type, OptionalIntType):
            return '{0L, 0}' if value is None else f'{{{value}L, 1}}'
        if isinstance(value_type, ImageType):
            return str(self.image_id(value))
        if isinstance(value_type, ClassType):
            return '&' + self.object_symbol(value_type.name, value, where)
        if isinstance(value_type, BufferType):
            return '&' + self.buffer_symbol(value_type, value, where)
        if isinstance(value_type, ArrayType):
            return '&' + self.array_symbol(value_type, value, where)
        if isinstance(value_type, TupleType):
            parts = [self.value_initializer(element, item, where)
                     for element, item in zip(value_type.elements, value)]
            return '{' + ', '.join(parts) + '}'
        raise TranslationError(f'{where}: нет инициализатора для {value_type}')

    def object_symbol(self, class_name: str, value: object, where: str) -> str:
        if id(value) in self.symbols:
            return self.symbols[id(value)]
        symbol = self._name('o')
        self.symbols[id(value)] = symbol
        self.alive.append(value)
        self.output.declarations.append(f'extern {class_name} {symbol};')
        fields = self.heap.fields.get(class_name, {})
        parts = []
        record_fields = []
        for attribute, field_type in fields.items():
            initializer = self.value_initializer(field_type, vars(value)[attribute],
                                                 f'{where}.{attribute}')
            parts.append(f'    .{attribute} = ' + initializer)
            record_fields.append((attribute, field_type, initializer))
        body = ',\n'.join(parts) if parts else '    0'
        self.output.definitions.append(f'{class_name} {symbol} = {{\n{body}\n}};')
        self.records.append({'kind': 'object', 'symbol': symbol, 'class': class_name,
                             'fields': record_fields})
        return symbol

    def buffer_symbol(self, value_type: BufferType, value: object, where: str) -> str:
        if id(value) in self.symbols:
            return self.symbols[id(value)]
        symbol = self._name('b')
        self.symbols[id(value)] = symbol
        self.alive.append(value)
        data = bytes(value)
        self.output.declarations.append(f'extern Py2cBuffer {symbol};')
        external = len(data) > self.heap.external_threshold
        self.records.append({'kind': 'buffer', 'symbol': symbol, 'length': len(data), 'data': data,
                             'external': external, 'mutable': value_type.mutable, 'where': where})
        if external:
            self.output.externals.append(ExternalData(symbol, 'buffer', None, len(data), data,
                                                      value_type.mutable))
            self.output.definitions.append(
                f'Py2cBuffer {symbol} = {{ 0, {len(data)}UL, 0 }}; /* {where}: внешние данные */')
        else:
            body = ', '.join(str(byte) for byte in data) or '0'
            self.output.definitions.append(
                f'uint8_t {symbol}_data[{max(1, len(data))}] = {{ {body} }};')
            self.output.definitions.append(
                f'Py2cBuffer {symbol} = {{ {symbol}_data, {len(data)}UL, 0 }};')
        return symbol

    def array_symbol(self, value_type: ArrayType, value: object, where: str) -> str:
        if id(value) in self.symbols:
            return self.symbols[id(value)]
        symbol = self._name('a')
        self.symbols[id(value)] = symbol
        self.alive.append(value)
        items = list(value)
        element = value_type.element
        self.heap.array_types.add(value_type)
        self.array_types[symbol] = value_type
        struct = value_type.struct_name()
        self.output.declarations.append(f'extern {struct} {symbol};')
        capacity = max(1, len(items))
        if isinstance(element, ImageType):
            numbers = [self.image_id(item) for item in items]
            storage = IntType(16, False)
        elif isinstance(element, IntType):
            numbers = list(items)
            storage = element
        else:
            numbers = None
            storage = None
        if numbers is not None and len(numbers) * (storage.bits // 8) > self.heap.external_threshold:
            payload = b''.join(number.to_bytes(storage.bits // 8, 'little', signed=storage.signed)
                               for number in numbers)
            self.output.externals.append(ExternalData(symbol, 'array', storage, len(items),
                                                      payload, value_type.mutable))
            self.output.definitions.append(
                f'{struct} {symbol} = {{ 0, {len(items)}, {capacity}, 0 }}; /* {where}: внешние данные */')
            self.records.append({'kind': 'array', 'symbol': symbol, 'type': value_type,
                                 'length': len(items), 'capacity': capacity, 'external': True,
                                 'payload': payload, 'mutable': value_type.mutable,
                                 'initializers': None, 'numbers': numbers, 'where': where})
            return symbol
        initializers = [self.value_initializer(element, item, f'{where}[{index}]')
                        for index, item in enumerate(items)]
        self.records.append({'kind': 'array', 'symbol': symbol, 'type': value_type,
                             'length': len(items), 'capacity': capacity, 'external': False,
                             'payload': None, 'mutable': value_type.mutable,
                             'initializers': initializers, 'numbers': numbers, 'where': where})
        body = ', '.join(initializers) or '0'
        self.output.definitions.append(
            f'{value_type.element_c()} {symbol}_data[{capacity}] = {{ {body} }};')
        self.output.definitions.append(
            f'{struct} {symbol} = {{ {symbol}_data, {len(items)}, {capacity}, 0 }};')
        return symbol
