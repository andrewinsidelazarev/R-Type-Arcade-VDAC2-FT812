"""Выражения: константы, имена, атрибуты, индексы, операции, сравнения, дисплеи."""
from __future__ import annotations

import ast
import types as pytypes

from .compiler import INT_EMPTY, describe, int_empty
from .errors import TranslationError
from .fn_base import COMPARE_SYMBOLS, I16_RANGE, NO_CONST, U16_RANGE, Unknown, Value, cname
from .intervals import BOOL_RANGE, TOP, Interval, binary
from .ptypes import (
    BOOL, BOTTOM, I16, I32, IMAGE, INT_TOP, NONE, STR, U16, U8, VOID, ArrayT, BoolT, BottomT,
    BytesT, CInt, DequeT, DictT, FnT, FontT, ImageT, IntT, ListT, NoneT, ObjT, OptT, SetT, StrT,
    T, TargetT, TupleT, ValT, VoidT, ExtT, cint_for, contains_bottom, is_int_like, is_pointer,
)

RECT_ATTRIBUTES = {'x': 'x', 'y': 'y', 'w': 'w', 'h': 'h', 'width': 'w', 'height': 'h',
                   'left': 'x', 'top': 'y'}
# Таблицы значений выражений (tabulated): число значений переменной части и байт на таблицу.
TABLE_LIMIT = 4096
TABLE_BYTES = 8192
TABLE_OPERATORS = frozenset(('Add', 'Sub', 'Mult', 'FloorDiv', 'Mod', 'LShift', 'RShift', 'BitAnd', 'BitOr', 'BitXor'))
TABLE_PLACEHOLDER = '__p2c_table_value__'


class ExprMixin:
    def expr(self, node: ast.expr) -> Value:
        method = getattr(self, 'expr_' + type(node).__name__, None)
        if method is None:
            raise self.error(f'выражение {type(node).__name__} не поддержано: {ast.unparse(node)[:80]}', node)
        if self.emit and isinstance(node, (ast.BinOp, ast.Call)):
            tabulated = self.tabulated(node, method)
            if tabulated is not None:
                return tabulated
        return method(node)

    # --- таблицы значений выражений -------------------------------------------------
    #
    # Целое выражение с одной переменной частью v (имя, поле, элемент, вызов или подвыражение с
    # несколькими переменными) и умножением, делением, остатком или round по константам вне v
    # вычисляется поиском: r = TAB[v − lo]. Значения таблицы на каждое v из интервала анализа
    # вычисляет сам CPython по исходнику выражения — результат совпадает с исполнением Python.
    # Интервал v — тот же, по которому выбраны C-типы; C-тип и интервал результата — как у обычной
    # трансляции (она строится и отбрасывается). Проверочная сборка сверяет индекс с таблицей.

    def table_constant(self, node: ast.expr) -> int | None:
        if isinstance(node, ast.Constant) and type(node.value) is int:
            return node.value
        if isinstance(node, ast.Name) and not self.is_local(node.id) and node.id not in self.capture_names:
            found, value = self.module_global(node.id)
            if found and type(value) is int:
                return value
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            inner = self.table_constant(node.operand)
            return None if inner is None else -inner
        return None

    def table_costly(self, node: ast.BinOp) -> bool:
        """Умножение не на степень двойки, деление и остаток не на степень двойки."""
        op = type(node.op).__name__
        power = lambda value: value is not None and value > 0 and value & (value - 1) == 0
        if op == 'Mult':
            return not (power(self.table_constant(node.left)) or power(self.table_constant(node.right)))
        if op in ('FloorDiv', 'Mod'):
            return not power(self.table_constant(node.right))
        return False

    def table_parts(self, node: ast.expr) -> tuple[ast.expr | None, bool]:
        """(переменная часть или None у константы, есть ли дорогая операция между узлом и ней)."""
        if self.table_constant(node) is not None:
            return None, False
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd, ast.Invert)):
            return self.table_parts(node.operand)
        if isinstance(node, ast.BinOp) and type(node.op).__name__ in TABLE_OPERATORS:
            return self.table_join(node, [node.left, node.right], self.table_costly(node))
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords and
                not self.is_local(node.func.id) and not self.module_global(node.func.id)[0]):
            name = node.func.id
            if (name == 'round' and len(node.args) == 1 and isinstance(node.args[0], ast.BinOp) and
                    isinstance(node.args[0].op, ast.Div)):
                return self.table_join(node, [node.args[0].left, node.args[0].right], True)
            if name in ('min', 'max', 'abs') and node.args and not any(isinstance(item, ast.Starred) for item in node.args):
                return self.table_join(node, list(node.args), False)
        return node, False

    def table_join(self, node: ast.expr, children: list[ast.expr], costly: bool) -> tuple[ast.expr | None, bool]:
        variables = [part for part in (self.table_parts(child) for child in children) if part[0] is not None]
        if not variables:
            return None, False
        if len(variables) == 1:
            return variables[0][0], costly or variables[0][1]
        return node, False

    def table_values(self, node: ast.expr, variable: ast.expr, low: int, high: int) -> list[int] | None:
        """Значения выражения CPython для каждого значения переменной части из [low, high]."""
        def rebuild(item):
            if item is variable:
                return ast.Name(id=TABLE_PLACEHOLDER, ctx=ast.Load())
            if isinstance(item, ast.AST):
                fields = {name: [rebuild(element) for element in value] if isinstance(value, list) else rebuild(value)
                          for name, value in ast.iter_fields(item)}
                return type(item)(**fields)
            return item
        expression = ast.fix_missing_locations(ast.Expression(body=rebuild(node)))
        code = compile(expression, '<p2c: таблица значений>', 'eval')
        environment = dict(vars(self.module))
        values = []
        for value in range(low, high + 1):
            environment[TABLE_PLACEHOLDER] = value
            try:
                result = eval(code, environment)
            except Exception:
                return None
            if type(result) is not int:
                return None
            values.append(result)
        return values

    def tabulated(self, node: ast.expr, method) -> Value | None:
        variable, costly = self.table_parts(node)
        if variable is None or variable is node or not costly:
            return None
        mark = self.mark()
        saved = (self.temp_counter, dict(self.plan.temps), len(self.plan.tables))

        def rollback() -> None:
            del self.lines[mark:]
            self.temp_counter = saved[0]
            self.plan.temps.clear()
            self.plan.temps.update(saved[1])
            del self.plan.tables[saved[2]:]

        normal = method(node)
        if not isinstance(normal.t, IntT) or normal.const is not NO_CONST or int_empty(normal.t):
            return normal
        width = self.width(normal)
        rollback()
        part = self.int_value(self.expr(variable), node)
        interval = self.interval_of(part)
        values = None
        if interval is not None and interval.hi - interval.lo + 1 <= TABLE_LIMIT:
            values = self.table_values(node, variable, interval.lo, interval.hi)
        if values is None or not all(normal.t.lo <= value <= normal.t.hi for value in values):
            rollback()
            return method(node)
        element = cint_for(Interval(min(values), max(values)))
        count = len(values)
        if count * element.bits // 8 > TABLE_BYTES:
            rollback()
            return method(node)
        name = f'p2c_tab{len(self.plan.tables) + 1}'
        rows = [', '.join(str(value) for value in values[start:start + 16]) for start in range(0, count, 16)]
        source = ast.unparse(node).replace('*/', '* /')
        self.plan.tables.append(f'/* {source}: {ast.unparse(variable)} ∈ [{interval.lo}, {interval.hi}] */')
        self.plan.tables.append(f'static const {element.c()} {name}[{count}] = {{\n        ' +
                                ',\n        '.join(rows) + ' };')
        index = 'P2C_TAB_INDEX8' if count <= 256 else 'P2C_TAB_INDEX'
        code = f'(({width.c()}){name}[{index}({part.code}, {interval.lo}L, {count})])'
        return Value(normal.t, code, width)

    # --- константы и имена ---------------------------------------------------------

    def expr_Constant(self, node: ast.Constant) -> Value:
        value = node.value
        if value is None:
            return Value(NONE, 'NULL', const=None)
        if type(value) is bool:
            return self.bool_value('1' if value else '0', value)
        if type(value) is int:
            return self.int_const(value)
        if isinstance(value, str):
            return self.string_constant(value)
        if isinstance(value, bytes):
            return self.constant_value(value, node)
        raise self.error(f'константа {value!r:.40} не поддержана', node)

    def string_constant(self, text: str) -> Value:
        number = self.c.intern(text)
        return Value(StrT(min(65535, len(text.encode('utf-8')))), f'P2C_STR({number})', const=text)

    def expr_Name(self, node: ast.Name) -> Value:
        name = node.id
        for scope in reversed(self.scopes):
            if name in scope:
                return self.local_value(scope[name], name, node)
        if name in self.param_names:
            param = self.param(name)
            t = self.resolved(param.t, param.declared)
            return self.with_refinement(Value(t, cname(name), path=name, cell=('param', name)), name)
        if name in self.assigned:
            return self.local_value(name, name, node)
        if name in self.capture_names:
            return self.capture_value(name, node)
        if self.plan.class_binding is not None and name == self.plan.class_binding[0]:
            return Value(VOID, '', meta=('class', self.plan.class_binding[1]))
        found, value = self.module_global(name)
        if found:
            return self.global_value(name, value, node)
        if self.builtin_exists(name):
            return Value(VOID, '', meta=('builtin', name))
        raise self.error(f'неизвестное имя {name}', node)

    def local_value(self, key: str, name: str, node: ast.AST) -> Value:
        t = self.plan.locals.get(key, BOTTOM)
        if self.incomplete(t):
            nested = self.nested_function(name)
            if nested is not None:
                return Value(VOID, '', meta=('nested', nested))
        code = cname(key) if key == name else key
        return self.with_refinement(Value(t, code, path=name, cell=('local', key)), key)

    def with_refinement(self, value: Value, key: str) -> Value:
        value = self.narrowed(value)
        if isinstance(value.t, IntT) and not int_empty(value.t):
            interval = self.refined(key, value.t.interval)
            if interval is not None:
                value.t = IntT(interval.lo, interval.hi)
        elif isinstance(value.t, IntT) and self.strict:
            interval = self.refined(key, TOP)
            value.t = IntT(interval.lo, interval.hi)
        if isinstance(value.t, IntT) and self.emit:
            declared = self.plan.locals.get(key) if key not in self.param_names else self.param(key).t
            declared = self.resolved(declared, self.param(key).declared if key in self.param_names else None) \
                if declared is not None else None
            if isinstance(declared, IntT):
                value.cwidth = self.r.cint(declared)
        elif isinstance(value.t, BoolT):
            value.cwidth = U8
        return value

    def capture_value(self, name: str, node: ast.AST) -> Value:
        capture = next(item for item in self.plan.captures if item.name == name)
        parent_type = self.enclosing_type(name)
        t = self.resolved(parent_type, None)
        if self.emit and self.c.layout.env_is_direct(self.plan):
            code = 'p2c_direct'
        else:
            code = f'(*p2c_env->{cname(name)})' if capture.by_pointer else f'p2c_env->{cname(name)}'
        value = Value(t, code, path=name)
        if isinstance(t, IntT) and self.emit:
            value.cwidth = self.r.cint(t)
        return value

    def enclosing_type(self, name: str) -> T:
        parent = self.plan.parent
        while parent is not None:
            if name in parent.locals:
                return parent.locals[name]
            for param in parent.params:
                if param.name == name:
                    return self.resolved(param.t, param.declared)
            for capture in parent.captures:
                if capture.name == name:
                    parent = parent.parent
                    break
            else:
                return BOTTOM
        return BOTTOM

    def nested_function(self, name: str):
        for item in ast.walk(self.plan.node):
            if isinstance(item, ast.FunctionDef) and item.name == name and item is not self.plan.node:
                return item
        return None

    def global_value(self, name: str, value: object, node: ast.AST) -> Value:
        if type(value) is bool:
            return self.bool_value('1' if value else '0', value)
        if type(value) is int:
            return self.int_const(value)
        if isinstance(value, str):
            return self.string_constant(value)
        if isinstance(value, type):
            info = self.p.classes.get(value.__name__)
            if info is not None and info.python is value:
                return Value(VOID, '', meta=('class', info.name))
            return Value(VOID, '', meta=('pytype', value))
        if isinstance(value, pytypes.FunctionType):
            module = value.__module__
            if module in self.p.modules and value.__name__ in self.p.modules[module].functions:
                return Value(VOID, '', meta=('function', module, value.__name__))
            return Value(VOID, '', meta=('pyfunction', value))
        if isinstance(value, pytypes.ModuleType):
            return Value(VOID, '', meta=('module', value.__name__))
        if isinstance(value, (tuple, frozenset, set, dict, bytes, list)):
            return self.constant_value(value, node)
        if value is None:
            return Value(NONE, 'NULL', const=None)
        return Value(VOID, '', meta=('pyobject', value), const=value)

    def constant_value(self, value: object, node: ast.AST) -> Value:
        """Неизменяемые данные модуля: C-данные константы и её форма."""
        number, t = self.c.constant(value, ast.unparse(node) if isinstance(node, ast.AST) else '')
        code = f'P2C_CONST({number})' if not self.emit else self.c.layout.constant_code(number)
        return Value(t, code, const=value)

    # --- атрибуты ----------------------------------------------------------------

    def expr_Attribute(self, node: ast.Attribute) -> Value:
        owner = self.expr(node.value)
        return self.attribute(owner, node.attr, node)

    def attribute(self, owner: Value, attr: str, node: ast.AST) -> Value:
        meta = owner.meta
        if meta is not None:
            return self.meta_attribute(owner, attr, node)
        t = owner.t
        if isinstance(t, BottomT) or (isinstance(t, NoneT) and not self.emit):
            raise self.unknown(node)
        if isinstance(t, OptT) and isinstance(t.inner, (ObjT, ValT)):
            owner = Value(t.inner, owner.code if isinstance(t.inner, ObjT) else f'P2C_UNWRAP({owner.code})',
                          path=owner.path)
            t = owner.t
        if isinstance(t, ObjT):
            return self.object_attribute(owner, attr, node)
        if isinstance(t, ValT):
            return self.value_attribute(owner, attr, node)
        if isinstance(t, (ListT, ArrayT, DequeT, DictT, SetT, StrT, BytesT, TargetT, FontT, ImageT, ExtT,
                          IntT, BoolT)):
            return Value(VOID, '', meta=('method', owner, attr))
        raise self.error(f'атрибут {attr} у {describe(t)} не поддержан', node)

    def meta_attribute(self, owner: Value, attr: str, node: ast.AST) -> Value:
        meta = owner.meta
        kind = meta[0]
        if kind == 'module':
            module = __import__(meta[1], fromlist=['_'])
            if not hasattr(module, attr):
                raise self.error(f'нет {meta[1]}.{attr}', node)
            value = getattr(module, attr)
            if isinstance(value, pytypes.ModuleType):
                return Value(VOID, '', meta=('module', value.__name__))
            if type(value) is int or type(value) is bool:
                return self.global_value(attr, value, node)
            return Value(VOID, '', meta=('modattr', meta[1], attr), const=value)
        if kind == 'class':
            class_name = meta[1]
            found = self.p.find_method(class_name, attr)
            if found is not None:
                info, _ = found
                return Value(VOID, '', meta=('classmethod_ref', class_name, info.name, attr))
            exists, value = self.p.class_attribute(class_name, attr)
            if exists:
                return self.global_value(attr, value, node)
            raise self.error(f'нет атрибута класса {class_name}.{attr}', node)
        if kind == 'super':
            return Value(VOID, '', meta=('super_method', meta[1], meta[2], attr))
        if kind == 'pytype':
            return Value(VOID, '', meta=('pytype_attr', meta[1], attr))
        raise self.error(f'атрибут {attr} у {kind} не поддержан', node)

    def object_attribute(self, owner: Value, attr: str, node: ast.AST) -> Value:
        class_name = owner.t.cls
        if class_name == '*':
            return self.any_object_field(owner, attr, node)
        found = self.p.find_method(class_name, attr)
        if found is None:
            for live in self.c.live_classes(class_name):
                found = self.p.find_method(live, attr)
                if found is not None:
                    break
        if found is not None and not self.has_instance_field(class_name, attr):
            info, function = found
            kind = info.method_kind(attr)
            if kind == 'property':
                return self.call_method(owner, attr, [], {}, node)
            return Value(VOID, '', meta=('bound', owner, attr))
        if not self.has_instance_field(class_name, attr):
            exists, value = self.p.class_attribute(class_name, attr)
            if exists:
                return self.global_value(attr, value, node)
        return self.field_value(owner, class_name, attr, node)

    def has_instance_field(self, class_name: str, attr: str) -> bool:
        cell = self.c.fields.get((self.p.root(class_name), attr))
        return cell is not None and bool(cell.classes)

    def field_value(self, owner: Value, class_name: str, attr: str, node: ast.AST) -> Value:
        cell = self.c.field_cell(class_name, attr)
        t = self.c.field_type(class_name, attr)
        if isinstance(t, BottomT):
            if self.emit:
                raise self.error(f'поле {class_name}.{attr} без записанных значений', node)
            raise Unknown()
        if self.emit:
            code = self.c.layout.field_code(owner.code, class_name, attr)
        else:
            code = f'{owner.code}->{attr}'
        path = f'{owner.path}.{attr}' if owner.path else None
        value = Value(t, code, path=path, cell=('field', class_name, attr))
        if is_int_like(t) and self.emit:
            value.cwidth = self.r.cint(t)
        return self.narrowed(value)

    def any_object_field(self, owner: Value, attr: str, node: ast.AST) -> Value:
        having = [name for name in sorted(self.c.instantiated) if self.c.layout_has_attribute(name, attr)]
        if not having:
            raise self.unknown(node, f'поле {attr} у object')
        return self.any_getattr(self.hoist(owner), attr, having, None, node)

    def value_attribute(self, owner: Value, attr: str, node: ast.AST) -> Value:
        class_name = owner.t.cls
        if class_name == 'Rect':
            if attr in RECT_ATTRIBUTES:
                member = RECT_ATTRIBUTES[attr]
                return Value(IntT(-(1 << 31), (1 << 31) - 1), f'({owner.code}).{member}', I32)
            if attr in ('right', 'bottom'):
                first, second = ('x', 'w') if attr == 'right' else ('y', 'h')
                holder = self.hoist(owner)
                return Value(IntT(-(1 << 31), (1 << 31) - 1),
                             f'P2C_I32({holder.code}.{first}, +, {holder.code}.{second})', I32)
            if attr == 'colliderect':
                return Value(VOID, '', meta=('method', owner, attr))
            raise self.error(f'Rect.{attr} не поддержан', node)
        found = self.p.find_method(class_name, attr)
        if found is not None:
            info, _ = found
            if info.method_kind(attr) == 'property':
                return self.call_method(owner, attr, [], {}, node)
            return Value(VOID, '', meta=('bound', owner, attr))
        t = self.c.field_type(class_name, attr)
        if self.incomplete(t):
            raise self.unknown(node, f'поле {class_name}.{attr}')
        value = Value(t, f'({owner.code}).{cname(attr)}', path=None)
        if is_int_like(t) and self.emit:
            value.cwidth = self.r.cint(t)
        return value

    # --- индексы и срезы -----------------------------------------------------------

    def expr_Subscript(self, node: ast.Subscript) -> Value:
        if (isinstance(node.value, ast.Call) and ast.unparse(node.value.func) == 'struct.unpack_from'
                and isinstance(node.slice, ast.Constant) and type(node.slice.value) is int):
            values = self.unpack_from(node.value)
            if not 0 <= node.slice.value < len(values):
                raise self.error('индекс результата unpack_from вне формата', node)
            return values[node.slice.value]
        container = self.expr(node.value)
        if isinstance(node.slice, ast.Slice):
            return self.slice_value(container, node.slice, node)
        mark = self.mark()
        index = self.expr(node.slice)
        self.fix_left([container], mark)
        return self.element(container, index, node)

    def normalize_index(self, container: Value, index: Value, node: ast.AST) -> str:
        """Индекс CPython: отрицательный — от конца; вне длины — отказ (проверяется на ПК)."""
        index = self.int_value(index, node)
        interval = self.interval_of(index) or TOP
        if interval.lo >= 0:
            return self.cast(index, U16, node) if interval.hi <= 65535 else f'P2C_INDEX({container.code}, {self.cast(index, I32, node)})'
        if interval.hi < 0 and isinstance(index.const, int):
            return f'({container.code}->length - {-index.const})'
        return f'P2C_INDEX({container.code}, {self.cast(index, I32, node)})'

    def element(self, container: Value, index: Value, node: ast.AST) -> Value:
        t = container.t
        if self.incomplete(t) or self.incomplete(index.t):
            raise self.unknown(node)
        if isinstance(t, OptT):
            container = Value(t.inner, container.code, path=container.path)
            t = t.inner
        if isinstance(t, TupleT):
            if not isinstance(index.const, int):
                # Индекс времени исполнения: выбор члена кортежа без выделения массива.
                items = self.c.join_all(t.items, node, self.plan.filename)
                if not self.emit:
                    return Value(items, 'p2c_tuple_item')
                holder = self.hoist(container)
                position = self.hoist(Value(IntT(-(1 << 31), (1 << 31) - 1),
                                            self.cast(self.int_value(index, node), I32, node), I32))
                result = self.temp(items)
                if is_int_like(items):
                    self.plan.temps[result] = ('cint', self.r.cint(items))
                self.line(f'switch ({position.code} < 0 ? {position.code} + {len(t.items)} : {position.code}) {{')
                for member, item in enumerate(t.items):
                    code = self.convert(Value(item, f'({holder.code}).v{member}',
                                              self.r.cint(item) if is_int_like(item) else None), items, node)
                    self.line(f'case {member}: {result} = {code}; break;')
                self.line('default: p2c_raise(P2C_E_INDEX);')
                self.line('}')
                value = Value(items, result)
                if is_int_like(items):
                    value.cwidth = self.r.cint(items)
                return value
            position = index.const
            if position < 0:
                position += len(t.items)
            if not 0 <= position < len(t.items):
                raise self.error('индекс кортежа вне длины', node)
            item = t.items[position]
            value = Value(item, f'({container.code}).v{position}')
            if is_int_like(item) and self.emit:
                value.cwidth = self.r.cint(item)
            return value
        if isinstance(t, (ListT, ArrayT)) or (isinstance(t, ObjT) and t.cls != '*' and
                                              self.p.list_base_of(t.cls) is not None):
            if isinstance(t, ObjT):
                elem = self.list_base_type(t.cls, node)
                container = Value(ListT(elem), f'((P2cList *){container.code})')
                t = container.t
            elem = t.elem
            if isinstance(elem, BottomT):
                raise self.unknown(node)
            position = self.normalize_index(container, index, node)
            ctype = self.ctype(elem) if self.emit else 'int'
            value = Value(elem, f'P2C_AT({container.code}, {ctype}, {position})')
            if is_int_like(elem) and self.emit:
                value.cwidth = self.r.cint(elem)
            return value
        if isinstance(t, DequeT):
            position = self.normalize_index(container, index, node)
            ctype = self.ctype(t.elem) if self.emit else 'int'
            value = Value(t.elem, f'P2C_DEQUE_AT({container.code}, {ctype}, {position})')
            if is_int_like(t.elem) and self.emit:
                value.cwidth = self.r.cint(t.elem)
            return value
        if isinstance(t, BytesT):
            position = self.normalize_index(container, index, node)
            return Value(IntT(0, 255), f'P2C_BYTE({container.code}, {position})', U8)
        if isinstance(t, DictT):
            return self.dict_lookup(container, index, None, node)
        if isinstance(t, StrT):
            position = self.normalize_index(container, index, node)
            return Value(StrT(1), f'p2c_str_char({container.code}, {position})')
        raise self.error(f'индексирование {describe(t)} не поддержано', node)

    def list_base_type(self, class_name: str, node: ast.AST) -> T:
        from .annotations import parse_annotation
        base = self.p.list_base_of(class_name)
        info = self.p.classes[class_name]
        declared = parse_annotation(self.c, base, info.module, info.filename)
        cell = self.c.field_cell(class_name, '<items>')
        return self.c.join(cell.t, declared) if not isinstance(cell.t, BottomT) else declared

    def slice_value(self, container: Value, slice_node: ast.Slice, node: ast.AST) -> Value:
        t = container.t
        if self.incomplete(t):
            raise self.unknown(node)
        if slice_node.step is not None:
            raise self.error('срез с шагом не поддержан', node)
        if isinstance(t, ObjT) and self.p.list_base_of(t.cls) is not None:
            container = Value(ListT(self.list_base_type(t.cls, node)), f'((P2cList *){container.code})')
            t = container.t
        start = self.expr(slice_node.lower) if slice_node.lower is not None else self.int_const(0)
        stop = self.expr(slice_node.upper) if slice_node.upper is not None else None
        start_code = self.cast(self.int_value(start, node), I32, node)
        stop_code = self.cast(self.int_value(stop, node), I32, node) if stop is not None else 'P2C_SLICE_END'
        if isinstance(t, (ListT, ArrayT)):
            result_t = ListT(t.elem) if isinstance(t, ListT) else ArrayT(t.elem)
            ctype = self.ctype(t.elem) if self.emit else 'int'
            self.plan.allocates = True
            kind = 'list' if isinstance(t, ListT) else 'array'
            return Value(result_t, f'p2c_{kind}_slice({self.container_class(result_t)}, {container.code}, '
                                   f'sizeof({ctype}), {start_code}, {stop_code})')
        if isinstance(t, BytesT):
            self.plan.allocates = True
            return Value(BytesT(t.mutable), f'p2c_buf_slice({container.code}, {start_code}, {stop_code}, '
                                            f'{1 if t.mutable else 0})')
        raise self.error(f'срез {describe(t)} не поддержан', node)

    # --- арифметика -----------------------------------------------------------

    def expr_BinOp(self, node: ast.BinOp) -> Value:
        left = self.expr(node.left)
        mark = self.mark()
        right = self.expr(node.right)
        self.fix_left([left], mark)
        return self.binop(left, node.op, right, node.right, node)

    def binop(self, left: Value, operator: ast.operator, right: Value, right_node: ast.expr | None,
              node: ast.AST) -> Value:
        op = type(operator).__name__
        if isinstance(left.t, BottomT) or isinstance(right.t, BottomT):
            raise self.unknown(node)
        if isinstance(left.t, (SetT,)) and op in ('Sub', 'BitOr', 'BitAnd'):
            return self.set_operation(left, op, right, node)
        if op == 'Mult' and isinstance(left.t, (ListT, TupleT, ArrayT)):
            return self.sequence_repeat(left, right, node)
        if op == 'Add' and isinstance(left.t, (ListT, TupleT, ArrayT)):
            return self.sequence_concat(left, right, node)
        if op == 'Div':
            raise self.error('истинное деление вне round() не поддержано', node)
        left = self.int_value(left, node)
        right = self.int_value(right, node)
        constant = right.const if isinstance(right.const, int) and not isinstance(right.const, bool) else None
        a = self.interval_of(left) or self.width(left).interval()
        b = self.interval_of(right) or self.width(right).interval()
        if op == 'FloorDiv' and constant is not None and constant > 0 and constant & (constant - 1) == 0:
            op, right, constant = 'RShift', self.int_const(constant.bit_length() - 1), constant.bit_length() - 1
            b = Interval.of(constant)
        if op == 'Mod' and constant is not None and constant > 0 and constant & (constant - 1) == 0:
            op, right, constant = 'BitAnd', self.int_const(constant - 1), constant - 1
            b = Interval.of(constant)
        result = binary(op, a, b, constant)
        folded = self.fold(op, left, right)
        if folded is not None:
            return self.int_const(folded)
        if op in ('Add', 'Sub', 'Mult', 'BitAnd', 'BitOr', 'BitXor'):
            symbol = {'Add': '+', 'Sub': '-', 'Mult': '*', 'BitAnd': '&', 'BitOr': '|', 'BitXor': '^'}[op]
            width = self.arithmetic_width(result, [left, right])
            code = f'{self.op_macro(width)}({left.code}, {symbol}, {right.code})'
            return Value(IntT(result.lo, result.hi), code, width)
        if op == 'LShift':
            if constant is None or not 0 <= constant < 32:
                return Value(IntT(result.lo, result.hi),
                             f'P2C_SHL({self.cast(left, I32, node)}, {self.cast(right, I32, node)})', I32)
            width = self.arithmetic_width(result, [left, right])
            code = f'{self.op_macro(width)}({left.code}, <<, {constant})'
            return Value(IntT(result.lo, result.hi), code, width)
        if op == 'RShift':
            if constant is None or constant < 0:
                return Value(IntT(result.lo, result.hi),
                             f'p2c_shr({self.cast(left, I32, node)}, {self.cast(right, I32, node)})', I32)
            width = (I16 if a.within(I16_RANGE.lo, I16_RANGE.hi)
                     else U16 if a.within(U16_RANGE.lo, U16_RANGE.hi) else I32)
            code = f'{self.op_macro(width)}({left.code}, >>, {min(constant, 31)})'
            return Value(IntT(result.lo, result.hi), code, width)
        if op == 'FloorDiv':
            return Value(IntT(result.lo, result.hi),
                         f'p2c_floordiv({self.cast(left, I32, node)}, {self.cast(right, I32, node)})', I32)
        if op == 'Mod':
            return Value(IntT(result.lo, result.hi),
                         f'p2c_mod({self.cast(left, I32, node)}, {self.cast(right, I32, node)})', I32)
        raise self.error(f'операция {op} не поддержана', node)

    @staticmethod
    def fold(op: str, left: Value, right: Value) -> int | None:
        a, b = left.const, right.const
        if not (type(a) in (int, bool) and type(b) in (int, bool)):
            return None
        try:
            result = {
                'Add': lambda: a + b, 'Sub': lambda: a - b, 'Mult': lambda: a * b,
                'BitAnd': lambda: a & b, 'BitOr': lambda: a | b, 'BitXor': lambda: a ^ b,
                'LShift': lambda: a << b, 'RShift': lambda: a >> b,
                'FloorDiv': lambda: a // b, 'Mod': lambda: a % b,
            }[op]()
        except (KeyError, ZeroDivisionError, ValueError):
            return None
        return result if -(1 << 31) <= result < (1 << 31) else None

    def expr_UnaryOp(self, node: ast.UnaryOp) -> Value:
        op = type(node.op).__name__
        if op == 'Not':
            code = self.condition(node.operand)
            if code in ('0', '1'):
                return self.bool_value('1' if code == '0' else '0', code == '0')
            return self.bool_value(f'(!{code})')
        operand = self.expr(node.operand)
        operand = self.int_value(operand, node)
        interval = self.interval_of(operand) or self.width(operand).interval()
        if isinstance(operand.const, int):
            value = {'USub': -operand.const, 'UAdd': operand.const, 'Invert': ~operand.const}[op]
            return self.int_const(value)
        if op == 'USub':
            result = Interval(-interval.hi, -interval.lo).clamp()
            width = self.arithmetic_width(result, [operand])
            return Value(IntT(result.lo, result.hi), f'{self.op_macro(width)}(0, -, {operand.code})', width)
        if op == 'UAdd':
            return operand
        if op == 'Invert':
            result = Interval(-interval.hi - 1, -interval.lo - 1).clamp()
            width = self.arithmetic_width(result, [operand])
            return Value(IntT(result.lo, result.hi), f'{self.op_macro(width)}(-1, -, {operand.code})', width)
        raise self.error(f'унарная операция {op} не поддержана', node)

    # --- логические операции ------------------------------------------------------

    def condition(self, node: ast.expr) -> str:
        """C-условие выражения в позиции проверки истинности (значения операндов не нужны)."""
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return f'(!{self.condition(node.operand)})'
        if not isinstance(node, ast.BoolOp):
            value = self.value_expr(node)
            if isinstance(value.const, bool):
                return '1' if value.const else '0'
            return self.truth(value, node)
        is_and = isinstance(node.op, ast.And)
        saved_present = set(self.present)
        parts: list[str] = []
        part_lines: list[list[str]] = []
        try:
            for position, item in enumerate(node.values):
                if position:
                    self.present |= self.narrowing(node.values[position - 1], is_and)
                start = self.mark()
                code = self.condition(item)
                lines = self.lines[start:]
                del self.lines[start:]
                # Постоянный операнд: короткое вычисление отбрасывает остаток или сам операнд.
                if code == ('0' if is_and else '1') and not lines:
                    if not parts:
                        return code
                    parts.append(code)
                    part_lines.append(lines)
                    break
                if code == ('1' if is_and else '0') and not lines:
                    continue
                parts.append(code)
                part_lines.append(lines)
        finally:
            self.present = saved_present
        if not parts:
            return '1' if is_and else '0'
        if not self.emit:
            return parts[0] if len(parts) == 1 and parts[0] in ('0', '1') else 'p2c_condition'
        if len(parts) == 1:
            self.lines.extend(part_lines[0])
            return parts[0]
        if not any(part_lines[1:]):
            self.lines.extend(part_lines[0])
            symbol = ' && ' if is_and else ' || '
            return '(' + symbol.join(parts) + ')'
        # Правые операнды с эффектами выполняются только после проверки левых.
        result = self.temp(BOOL)
        self.line(f'{result} = {0 if is_and else 1};')
        depth = 0
        for position, (code, lines) in enumerate(zip(parts, part_lines)):
            self.lines.extend('    ' * depth + line for line in lines)
            if position == len(parts) - 1:
                self.line('    ' * depth + f'{result} = {code};')
            else:
                self.line('    ' * depth + f'if ({"" if is_and else "!"}{code}) {{')
                depth += 1
        for level in range(depth, 0, -1):
            self.line('    ' * (level - 1) + '}')
        return result

    def expr_BoolOp(self, node: ast.BoolOp) -> Value:
        is_and = isinstance(node.op, ast.And)
        saved_present = set(self.present)
        first = self.value_expr(node.values[0])
        mark = self.mark()
        simple = isinstance(first.t, BoolT)
        rest_values = []
        if simple:
            saved_lines = len(self.lines)
            try:
                for position, item in enumerate(node.values[1:]):
                    for previous in node.values[:position + 1]:
                        self.present |= self.narrowing(previous, is_and)
                    value = self.value_expr(item)
                    rest_values.append(value)
                    if not isinstance(value.t, BoolT):
                        simple = False
            finally:
                self.present = saved_present
            if simple and len(self.lines) == saved_lines:
                symbol = ' && ' if is_and else ' || '
                codes = []
                for value in [first, *rest_values]:
                    code = self.truth(value, node)
                    if code == ('0' if is_and else '1'):
                        # Постоянный операнд решает результат: левые операнды без эффектов.
                        return self.bool_value(code)
                    if code == ('1' if is_and else '0'):
                        continue
                    codes.append(code)
                if not codes:
                    return self.bool_value('1' if is_and else '0')
                return self.bool_value(codes[0] if len(codes) == 1 else '(' + symbol.join(codes) + ')')
            if self.emit:
                del self.lines[saved_lines:]
        return self.boolop_general(node, first, is_and)

    def boolop_general(self, node: ast.BoolOp, first: Value, is_and: bool) -> Value:
        """`a or b` / `a and b` со значением операнда и вычислением по требованию."""
        if isinstance(first.t, BottomT):
            raise self.unknown(node)
        values_types = [first.t]
        # Анализ: форма результата — объединение форм операндов.
        if not self.emit:
            saved_present = set(self.present)
            try:
                for position, item in enumerate(node.values[1:]):
                    for previous in node.values[:position + 1]:
                        self.present |= self.narrowing(previous, is_and)
                    value = self.value_expr(item)
                    values_types.append(value.t)
            finally:
                self.present = saved_present
            result_t = self.or_result_type(values_types, is_and, node)
            return Value(result_t, 'p2c_boolop')
        saved_present = set(self.present)
        types = [first.t]
        for position, item in enumerate(node.values[1:]):
            self.present |= self.narrowing(node.values[position], is_and)
            types.append(self.static_expr_type(item))
        self.present = saved_present
        result_t = self.or_result_type(types, is_and, node)
        result = self.temp(result_t)
        if is_int_like(result_t):
            self.plan.temps[result] = ('cint', self.r.cint(result_t))
        # `a or b`: результат a только если a истинно (значит, не None); иначе вычисляется b.
        # `a and b`: результат a только если a ложно; иначе вычисляется b.
        current = self.hoist(first)
        opened = 0
        saved_present = set(self.present)
        for position, item in enumerate(node.values[1:]):
            condition = self.truth(current, node)
            self.line(f'if ({condition if not is_and else "!" + condition}) {{')
            self.line(f'    {result} = {self.convert(current, result_t, node)};')
            self.line('} else {')
            self.indent += 1
            opened += 1
            self.present |= self.narrowing(node.values[position], is_and)
            current = self.hoist(self.value_expr(item))
        self.line(f'{result} = {self.convert(current, result_t, node)};')
        self.present = saved_present
        for _ in range(opened):
            self.indent -= 1
            self.line('}')
        out = Value(result_t, result)
        if is_int_like(result_t):
            out.cwidth = self.r.cint(result_t)
        return out

    def or_result_type(self, items: list[T], is_and: bool, node: ast.AST) -> T:
        """Форма `a or b`: None/пустое у левого операнда не доходит до результата."""
        result = BOTTOM
        for position, item in enumerate(items):
            if not is_and and position < len(items) - 1 and isinstance(item, OptT):
                item = item.inner
            if isinstance(item, NoneT) and not is_and and position < len(items) - 1:
                continue
            result = self.c.join(result, item, node, self.plan.filename)
        return result

    def static_expr_type(self, node: ast.expr) -> T:
        """Форма выражения без генерации строк (повторный анализ в режиме analysis)."""
        saved = (self.emit, self.lines, self.temp_counter, dict(self.plan.temps))
        self.emit = False
        self.lines = []
        try:
            return self.value_expr(node).t
        finally:
            self.emit, self.lines, self.temp_counter, temps = saved
            self.plan.temps.clear()
            self.plan.temps.update(temps)

    # --- сравнения ------------------------------------------------------------

    def expr_Compare(self, node: ast.Compare) -> Value:
        operands = [node.left, *node.comparators]
        left = self.expr(node.left)
        if len(node.ops) == 1:
            code = self.compare_pair(left, node.ops[0], node.comparators[0], node)
            return code
        # Цепочка: каждый средний операнд вычисляется один раз, остановка на первом ложном.
        if not self.emit:
            for op, right_node in zip(node.ops, node.comparators):
                result = self.compare_pair(left, op, right_node, node)
                left = self.expr(right_node)
            return self.bool_value('p2c_chain')
        result = self.temp(BOOL)
        self.line(f'{result} = 0;')
        opened = 0
        for position, (op, right_node) in enumerate(zip(node.ops, node.comparators)):
            right = self.hoist(self.expr(right_node))
            pair = self.compare_values(left, op, right, node)
            if position == len(node.ops) - 1:
                self.line(f'{result} = {pair.code};')
            else:
                self.line(f'if ({pair.code}) {{')
                self.indent += 1
                opened += 1
            left = right
        for _ in range(opened):
            self.indent -= 1
            self.line('}')
        return self.bool_value(result)

    def compare_pair(self, left: Value, op: ast.cmpop, right_node: ast.expr, node: ast.AST) -> Value:
        name = type(op).__name__
        if name in ('Is', 'IsNot') and isinstance(right_node, ast.Constant) and right_node.value is None:
            return self.none_test(left, name == 'Is', node)
        mark = self.mark()
        right = self.expr(right_node)
        self.fix_left([left], mark)
        return self.compare_values(left, op, right, node)

    def none_test(self, value: Value, is_none: bool, node: ast.AST) -> Value:
        t = value.t
        if isinstance(t, BottomT):
            raise self.unknown(node)
        if isinstance(t, NoneT):
            return self.bool_value('1' if is_none else '0', is_none)
        if not isinstance(t, OptT):
            return self.bool_value('0' if is_none else '1', not is_none)
        inner = t.inner
        if is_pointer(inner):
            code = f'({value.code} == NULL)' if is_none else f'({value.code} != NULL)'
        elif isinstance(inner, FnT):
            code = f'({value.code}.id == 0)' if is_none else f'({value.code}.id != 0)'
        else:
            code = f'(({value.code}).has == 0)' if is_none else f'(({value.code}).has != 0)'
        return self.bool_value(code)

    def compare_values(self, left: Value, op: ast.cmpop, right: Value, node: ast.AST) -> Value:
        name = type(op).__name__
        if isinstance(left.t, BottomT) or isinstance(right.t, BottomT):
            raise self.unknown(node)
        if name in ('In', 'NotIn'):
            code = self.membership(left, right, node)
            return self.bool_value(code if name == 'In' else f'(!{code})')
        if name in ('Is', 'IsNot'):
            if isinstance(right.t, NoneT):
                return self.none_test(left, name == 'Is', node)
            if isinstance(left.t, NoneT):
                return self.none_test(right, name == 'Is', node)
            symbol = '==' if name == 'Is' else '!='
            if isinstance(left.t, BoolT) and isinstance(right.const, bool):
                return self.bool_value(f'({left.code} {symbol} {int(right.const)})')
            return self.bool_value(f'((void *){left.code} {symbol} (void *){right.code})')
        symbol = COMPARE_SYMBOLS.get(name)
        if symbol is None:
            raise self.error(f'сравнение {name} не поддержано', node)
        return self.bool_value(self.compare_code(left, symbol, right, node))

    def compare_code(self, left: Value, symbol: str, right: Value, node: ast.AST) -> str:
        lt, rt = left.t, right.t
        if symbol not in ('==', '!=') and (isinstance(lt, OptT) or isinstance(rt, OptT)):
            # Упорядочивание с None в CPython — TypeError: значение здесь всегда присутствует.
            if isinstance(lt, OptT) and is_int_like(lt.inner):
                left = self.int_value(left, node)
            if isinstance(rt, OptT) and is_int_like(rt.inner):
                right = self.int_value(right, node)
            lt, rt = left.t, right.t
        if isinstance(lt, OptT) or isinstance(rt, OptT) or isinstance(lt, NoneT) or isinstance(rt, NoneT):
            if symbol not in ('==', '!='):
                raise self.error('упорядочивание Optional не поддержано', node)
            return self.optional_equality(left, symbol, right, node)
        if is_int_like(lt) and is_int_like(rt):
            if isinstance(left.const, (int, bool)) and isinstance(right.const, (int, bool)):
                return '1' if eval(f'{int(left.const)} {symbol} {int(right.const)}') else '0'
            left = self.int_value(left, node)
            right = self.int_value(right, node)
            a = self.interval_of(left)
            b = self.interval_of(right)
            if a is not None and b is not None:
                # Интервалы решают сравнение для всех потоков значений.
                decided = {'<': (a.hi < b.lo, a.lo >= b.hi), '<=': (a.hi <= b.lo, a.lo > b.hi),
                           '>': (a.lo > b.hi, a.hi <= b.lo), '>=': (a.lo >= b.hi, a.hi < b.lo),
                           '==': (a.lo == a.hi == b.lo == b.hi, a.hi < b.lo or b.hi < a.lo),
                           '!=': (a.hi < b.lo or b.hi < a.lo, a.lo == a.hi == b.lo == b.hi)}[symbol]
                if decided[0]:
                    return '1'
                if decided[1]:
                    return '0'
            width = self.common_width([left, right])
            return f'({self.cast(left, width, node)} {symbol} {self.cast(right, width, node)})'
        if isinstance(lt, StrT) and isinstance(rt, StrT):
            if symbol not in ('==', '!='):
                raise self.error('упорядочивание строк не поддержано', node)
            return f'(p2c_str_eq({left.code}, {right.code}) {symbol} 1)'
        if isinstance(lt, ObjT) and isinstance(rt, ObjT) and symbol in ('==', '!='):
            if self.has_eq(lt.cls) or self.has_eq(rt.cls):
                raise self.error('== у dataclass-объектов не поддержано', node)
            return f'((void *){left.code} {symbol} (void *){right.code})'
        if isinstance(lt, TupleT) and isinstance(rt, TupleT):
            if len(lt.items) != len(rt.items):
                return '0' if symbol == '==' else ('1' if symbol == '!=' else self.tuple_order(left, symbol, right, node))
            return self.tuple_compare(left, symbol, right, node)
        if isinstance(lt, ValT) and isinstance(rt, ValT) and lt.cls == rt.cls and symbol in ('==', '!='):
            fields = self.value_fields(lt.cls)
            left = self.hoist(left)
            right = self.hoist(right)
            parts = [self.compare_code(self.value_attribute(left, name, node), '==',
                                       self.value_attribute(right, name, node), node) for name in fields]
            code = '(' + ' && '.join(parts or ['1']) + ')'
            return code if symbol == '==' else f'(!{code})'
        if isinstance(lt, BytesT) and isinstance(rt, BytesT) and symbol in ('==', '!='):
            return f'(p2c_buf_eq({left.code}, {right.code}) {symbol} 1)'
        raise self.error(f'сравнение {describe(lt)} {symbol} {describe(rt)} не поддержано', node)

    def value_fields(self, class_name: str) -> list[str]:
        import dataclasses
        return [item.name for item in dataclasses.fields(self.p.classes[class_name].python)]

    def has_eq(self, class_name: str) -> bool:
        if class_name == '*':
            return False
        for name in self.c.live_classes(class_name) or [class_name]:
            info = self.p.classes[name]
            if '__eq__' in info.python.__dict__ or any(
                    '__eq__' in base.__dict__ for base in info.python.__mro__[1:] if base is not object):
                return True
        return False

    def optional_equality(self, left: Value, symbol: str, right: Value, node: ast.AST) -> str:
        if isinstance(right.t, NoneT):
            test = self.none_test(left, True, node).code
            return test if symbol == '==' else f'(!{test})'
        if isinstance(left.t, NoneT):
            test = self.none_test(right, True, node).code
            return test if symbol == '==' else f'(!{test})'
        left = self.hoist(left)
        right = self.hoist(right)
        lt, rt = left.t, right.t
        left_has = self.none_test(left, False, node).code if isinstance(lt, OptT) else '1'
        right_has = self.none_test(right, False, node).code if isinstance(rt, OptT) else '1'
        inner_left = Value(lt.inner if isinstance(lt, OptT) else lt,
                           f'({left.code}).v' if isinstance(lt, OptT) and not is_pointer(lt.inner) else left.code)
        inner_right = Value(rt.inner if isinstance(rt, OptT) else rt,
                            f'({right.code}).v' if isinstance(rt, OptT) and not is_pointer(rt.inner) else right.code)
        if self.emit and is_int_like(inner_left.t):
            inner_left.cwidth = self.r.cint(inner_left.t)
        if self.emit and is_int_like(inner_right.t):
            inner_right.cwidth = self.r.cint(inner_right.t)
        inner = self.compare_code(inner_left, '==', inner_right, node)
        code = f'(({left_has} == {right_has}) && (!{left_has} || {inner}))'
        return code if symbol == '==' else f'(!{code})'

    def tuple_compare(self, left: Value, symbol: str, right: Value, node: ast.AST) -> str:
        left = self.hoist(left)
        right = self.hoist(right)
        if symbol in ('==', '!='):
            parts = []
            for index, (a, b) in enumerate(zip(left.t.items, right.t.items)):
                va = Value(a, f'({left.code}).v{index}', self.r.cint(a) if self.emit and is_int_like(a) else None)
                vb = Value(b, f'({right.code}).v{index}', self.r.cint(b) if self.emit and is_int_like(b) else None)
                parts.append(self.compare_code(va, '==', vb, node))
            code = '(' + ' && '.join(parts or ['1']) + ')'
            return code if symbol == '==' else f'(!{code})'
        return self.tuple_order(left, symbol, right, node)

    def tuple_order(self, left: Value, symbol: str, right: Value, node: ast.AST) -> str:
        raise self.error('упорядочивание кортежей вне sorted не поддержано', node)

    # --- принадлежность -----------------------------------------------------------

    def membership(self, item: Value, container: Value, node: ast.AST) -> str:
        t = container.t
        constant = container.const
        if isinstance(constant, (frozenset, set, tuple, list)) and all(
                type(element) in (int, bool) or isinstance(element, str) for element in constant):
            if isinstance(item.t, StrT) or all(isinstance(element, str) for element in constant):
                if not all(isinstance(element, str) for element in constant):
                    return '0'
                holder = self.hoist(item)
                parts = [f'p2c_str_eq({holder.code}, P2C_STR({self.c.intern(text)}))' for text in sorted(set(constant))]
                return '(' + ' || '.join(parts or ['0']) + ')'
            values = sorted({int(element) for element in constant})
            item = self.int_value(item, node)
            function = self.c.layout.membership_function(values) if self.emit else 'p2c_in'
            return f'{function}({self.cast(item, I32, node)})'
        if isinstance(t, TupleT):
            holder = self.hoist(item)
            container = self.hoist(container)
            parts = []
            for index, element in enumerate(t.items):
                element_value = Value(element, f'({container.code}).v{index}',
                                      self.r.cint(element) if self.emit and is_int_like(element) else None)
                parts.append(self.compare_code(holder, '==', element_value, node))
            return '(' + ' || '.join(parts or ['0']) + ')'
        if isinstance(t, SetT):
            return self.set_contains(container, item, node)
        if isinstance(t, DictT):
            return self.dict_contains(container, item, node)
        if isinstance(t, (ListT, ArrayT, DequeT)):
            return self.sequence_contains(container, item, node)
        if isinstance(t, OptT) and isinstance(t.inner, (SetT, DictT, ListT, ArrayT)):
            return self.membership(item, Value(t.inner, container.code, path=container.path), node)
        raise self.error(f'in для {describe(t)} не поддержан', node)

    # --- условное выражение -------------------------------------------------------

    def expr_IfExp(self, node: ast.IfExp) -> Value:
        condition = self.condition(node.test)
        if condition in ('0', '1'):
            return self.value_expr(node.body if condition == '1' else node.orelse)
        saved_present = set(self.present)
        if not self.emit:
            body_t = BOTTOM
            other_t = BOTTOM
            try:
                self.present = saved_present | self.narrowing(node.test, True)
                body_t = self.value_expr(node.body).t
            except Unknown:
                pass
            try:
                self.present = saved_present | self.narrowing(node.test, False)
                other_t = self.value_expr(node.orelse).t
            except Unknown:
                pass
            finally:
                self.present = saved_present
            if isinstance(body_t, BottomT) and isinstance(other_t, BottomT):
                raise Unknown()
            result_t = self.c.join(body_t, other_t, node, self.plan.filename)
            return Value(result_t, 'p2c_ifexp')
        self.present = saved_present | self.narrowing(node.test, True)
        body_t = self.static_expr_type(node.body)
        self.present = saved_present | self.narrowing(node.test, False)
        other_t = self.static_expr_type(node.orelse)
        self.present = saved_present
        result_t = self.c.join(body_t, other_t, node, self.plan.filename)
        condition_holder = self.temp(BOOL)
        self.line(f'{condition_holder} = {condition};')
        mark = self.mark()
        self.present = saved_present | self.narrowing(node.test, True)
        body = self.value_expr(node.body)
        body_code = self.convert(body, result_t, node)
        body_lines = self.lines[mark:]
        del self.lines[mark:]
        self.present = saved_present | self.narrowing(node.test, False)
        other = self.value_expr(node.orelse)
        other_code = self.convert(other, result_t, node)
        self.present = saved_present
        other_lines = self.lines[mark:]
        del self.lines[mark:]
        if not body_lines and not other_lines:
            value = Value(result_t, f'({condition_holder} ? {body_code} : {other_code})')
        else:
            result = self.temp(result_t)
            self.line(f'if ({condition_holder}) {{')
            self.lines.extend('    ' + item for item in body_lines)
            self.line(f'    {result} = {body_code};')
            self.line('} else {')
            self.lines.extend('    ' + item for item in other_lines)
            self.line(f'    {result} = {other_code};')
            self.line('}')
            value = Value(result_t, result)
        if is_int_like(result_t):
            value.cwidth = self.r.cint(result_t)
        return value

    # --- дисплеи ----------------------------------------------------------------

    def expr_Tuple(self, node: ast.Tuple) -> Value:
        values = []
        for item in node.elts:
            if isinstance(item, ast.Starred):
                raise self.error('распаковка * в кортеже не поддержана', node)
            mark = self.mark()
            value = self.expr(item)
            self.fix_left(values, mark)
            values.append(value)
        if any(isinstance(value.t, BottomT) for value in values):
            raise self.unknown(node)
        t = TupleT(tuple(self.exact_type(value) for value in values))
        constant = tuple(value.const for value in values)
        if all(item is not NO_CONST for item in constant):
            const = constant
        else:
            const = NO_CONST
        if not self.emit:
            return Value(t, 'p2c_tuple', const=const)
        name = self.temp(t)
        for index, (value, item_t) in enumerate(zip(values, t.items)):
            self.line(f'{name}.v{index} = {self.convert(value, item_t, node)};')
        return Value(t, name, const=const)

    def exact_type(self, value: Value) -> T:
        """Форма значения для хранения: целое по интервалу, None — отдельная форма."""
        return value.t

    def expr_List(self, node: ast.List) -> Value:
        elements: list[tuple[str, Value]] = []
        for item in node.elts:
            mark = self.mark()
            if isinstance(item, ast.Starred):
                value = self.expr(item.value)
                self.fix_left([value for _, value in elements], mark)
                elements.append(('star', value))
            else:
                value = self.expr(item)
                self.fix_left([value for _, value in elements], mark)
                elements.append(('item', value))
        types = []
        for kind, value in elements:
            if kind == 'star':
                inner = self.iteration_element_type(value.t, node)
                types.append(inner)
            else:
                types.append(value.t)
        elem = self.c.join_all(types, node, self.plan.filename)
        if any(isinstance(item, BottomT) for item in types):
            if not self.emit:
                raise Unknown()
        t = ListT(elem)
        return self.build_list(t, elements, node)

    def display_type(self, own: T, node: ast.AST) -> T:
        """Форма дисплея [..]/{..}: ячейка, в которую он попадает (элементы шире литерала)."""
        recorded = self.c.display_types.get(id(node))
        if recorded is None:
            return own
        try:
            return self.c.join(recorded, own, node, self.plan.filename)
        except TranslationError:
            return recorded

    def build_list(self, t: ListT, elements: list[tuple[str, Value]], node: ast.AST) -> Value:
        self.plan.allocates = True
        if not self.emit:
            return Value(t, 'p2c_list', display=node)
        t = self.display_type(t, node)
        if isinstance(t, ArrayT):
            t = ListT(t.elem)
        name = self.temp(t)
        ctype = self.ctype(t.elem)
        count = sum(1 for kind, _ in elements if kind == 'item')
        self.line(f'{name} = p2c_list_new({self.container_class(t)}, sizeof({ctype}), {count});')
        for kind, value in elements:
            if kind == 'item':
                self.line(f'P2C_LIST_APPEND({name}, {ctype}, {self.convert(value, t.elem, node)});')
            else:
                self.extend_from(Value(t, name), value, node)
        return Value(t, name)

    def expr_Dict(self, node: ast.Dict) -> Value:
        pairs = []
        for key_node, value_node in zip(node.keys, node.values):
            if key_node is None:
                raise self.error('распаковка ** в словаре не поддержана', node)
            key = self.expr(key_node)
            value = self.expr(value_node)
            pairs.append((key, value))
        key_t = self.c.join_all([key.t for key, _ in pairs], node, self.plan.filename)
        value_t = self.c.join_all([value.t for _, value in pairs], node, self.plan.filename)
        t = DictT(key_t, value_t)
        self.plan.allocates = True
        if not self.emit:
            return Value(t, 'p2c_dict', display=node)
        t = self.display_type(t, node)
        name = self.temp(t)
        self.line(f'{name} = {self.dict_new(t)};')
        for key, value in pairs:
            self.dict_store(Value(t, name), key, value, node)
        return Value(t, name)

    def expr_Set(self, node: ast.Set) -> Value:
        values = [self.expr(item) for item in node.elts]
        t = SetT(self.c.join_all([value.t for value in values], node, self.plan.filename))
        self.plan.allocates = True
        if not self.emit:
            return Value(t, 'p2c_set', display=node)
        t = self.display_type(t, node)
        name = self.temp(t)
        self.line(f'{name} = {self.set_new(t)};')
        for value in values:
            self.set_add(Value(t, name), value, node)
        return Value(t, name)

    def expr_JoinedStr(self, node: ast.JoinedStr) -> Value:
        """f-строка: форматирование целых во время исполнения (отладочный текст)."""
        parts = []
        for item in node.values:
            if isinstance(item, ast.Constant):
                parts.append(('text', item.value))
            elif isinstance(item, ast.FormattedValue):
                spec = ''
                if item.format_spec is not None:
                    if not all(isinstance(piece, ast.Constant) for piece in item.format_spec.values):
                        raise self.error('вложенный формат f-строки не поддержан', node)
                    spec = ''.join(piece.value for piece in item.format_spec.values)
                if item.conversion != -1:
                    raise self.error('преобразование !r/!s в f-строке не поддержано', node)
                value = self.value_expr(item.value)
                inner = value.t.inner if isinstance(value.t, OptT) else value.t
                if isinstance(inner, StrT):
                    if spec:
                        raise self.error('формат строки в f-строке не поддержан', node)
                    parts.append(('str', self.hoist(Value(STR, self.convert(value, STR, node)))))
                else:
                    parts.append(('value', self.hoist(self.int_value(value, node)), spec))
        self.plan.allocates = True
        if not self.emit:
            return Value(STR, 'p2c_fstring')
        builder = self.temp(STR)
        self.line(f'p2c_fmt_begin();')
        for part in parts:
            if part[0] == 'text':
                self.line(f'p2c_fmt_text(P2C_STR({self.c.intern(part[1])}));')
            elif part[0] == 'str':
                self.line(f'p2c_fmt_text({part[1].code});')
            else:
                _, value, spec = part
                self.line(f'p2c_fmt_int({self.cast(value, I32, node)}, P2C_STR({self.c.intern(spec)}));')
        self.line(f'{builder} = p2c_fmt_end();')
        return Value(STR, builder)
