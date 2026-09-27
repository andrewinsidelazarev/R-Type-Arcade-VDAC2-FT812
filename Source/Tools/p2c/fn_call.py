"""Вызовы: функции, методы с виртуальной диспетчеризацией, конструкторы, вызываемые значения."""
from __future__ import annotations

import ast

from .compiler import INT_EMPTY, Param, Plan, describe, int_empty
from .fn_base import NO_CONST, Unknown, Value, cname
from .intervals import BOOL_RANGE, TOP, Interval
from .ptypes import (
    BOOL, BOTTOM, I16, I32, IMAGE, INT_TOP, NONE, STR, U16, U8, VOID, ArrayT, BoolT, BottomT,
    BytesT, DequeT, DictT, FnT, FontT, ImageT, IntT, ListT, NoneT, ObjT, OptT, SetT, StrT, T,
    TargetT, TupleT, ValT, VoidT, contains_bottom, is_int_like, is_pointer,
)


class CallMixin:
    def expr_Call(self, node: ast.Call) -> Value:
        func = node.func
        if isinstance(func, ast.Attribute):
            owner = self.expr(func.value)
            target = self.attribute_for_call(owner, func.attr, func)
        else:
            target = self.expr(func)
        return self.call_value(target, node)

    def attribute_for_call(self, owner: Value, attr: str, node: ast.AST) -> Value:
        """Атрибут в позиции вызова: метод не вызывается как свойство."""
        if owner.meta is None and isinstance(owner.t, (ObjT, OptT)):
            t = owner.t.inner if isinstance(owner.t, OptT) else owner.t
            if isinstance(t, ObjT) and t.cls != '*':
                if not self.has_instance_field(t.cls, attr):
                    found = self.p.find_method(t.cls, attr)
                    if found is None:
                        for live in self.c.live_classes(t.cls):
                            found = self.p.find_method(live, attr)
                            if found is not None:
                                break
                    if found is not None and found[0].method_kind(attr) != 'property':
                        return Value(VOID, '', meta=('bound', Value(t, owner.code, path=owner.path), attr))
                    if found is None and self.p.list_base_of(t.cls) is not None:
                        return Value(VOID, '', meta=('listbase_method', Value(t, owner.code, path=owner.path),
                                                     attr))
        return self.attribute(owner, attr, node)

    def call_value(self, target: Value, node: ast.Call) -> Value:
        meta = target.meta
        if meta is None:
            if isinstance(target.t, (FnT, OptT)):
                return self.call_callable(target, node)
            if isinstance(target.t, BottomT):
                self.arguments_only(node)
                raise self.unknown(node)
            raise self.error(f'вызов значения {describe(target.t)} не поддержан', node)
        kind = meta[0]
        if kind == 'builtin':
            return self.call_builtin(meta[1], node)
        if kind == 'function':
            plan = self.c.request_function(meta[1], meta[2], node, self.plan.filename)
            positional, keywords = self.arguments(node)
            return self.call_plan(plan, positional, keywords, node)
        if kind == 'class':
            return self.construct(meta[1], node)
        if kind == 'bound':
            owner, attr = meta[1], meta[2]
            positional, keywords = self.arguments(node, [owner])
            return self.call_method(positional[0], attr, positional[1:], keywords, node)
        if kind == 'method':
            return self.call_builtin_method(meta[1], meta[2], node)
        if kind == 'listbase_method':
            return self.call_builtin_method(self.as_list_base(meta[1], node), meta[2], node)
        if kind == 'super_method':
            return self.call_super(meta[1], meta[2], meta[3], node)
        if kind == 'classmethod_ref':
            return self.call_class_method(meta[1], meta[2], meta[3], node)
        if kind == 'modattr':
            return self.call_module_attribute(meta[1], meta[2], node)
        if kind == 'nested':
            plan = self.c.request_nested(self.plan, meta[1])
            positional, keywords = self.arguments(node)
            return self.call_plan(plan, positional, keywords, node, env=self.nested_env(plan, node))
        if kind == 'pytype' and meta[1].__name__ == 'deque' and meta[1].__module__ == 'collections':
            if len(node.args) != 1 or node.keywords:
                raise self.error('deque(итерируемое) без maxlen', node)
            source = node.args[0]
            if not isinstance(source, ast.GeneratorExp):
                source = self.synthetic_generator(node, source)
            return self.collect(source, 'deque', node)
        if kind == 'pytype_attr':
            if meta[1] is int and meta[2] == 'from_bytes':
                return self.int_from_bytes(node)
        raise self.error(f'вызов {ast.unparse(node.func)[:60]} не поддержан', node)

    def as_list_base(self, owner: Value, node: ast.AST) -> Value:
        elem = self.list_base_type(owner.t.cls, node)
        return Value(ListT(elem), f'((P2cList *){owner.code})', path=owner.path)

    # --- аргументы и привязка ---------------------------------------------------

    def arguments(self, node: ast.Call, earlier: list[Value] | None = None) -> tuple[list[Value], dict]:
        """Аргументы слева направо; ранние чтения фиксируются перед эффектами поздних."""
        values = list(earlier or [])
        keywords: dict[str, Value] = {}
        order: list[Value] = list(values)
        for item in node.args:
            mark = self.mark()
            if isinstance(item, ast.Starred):
                value = self.value_expr(item.value)
                self.fix_left(order, mark)
                if isinstance(value.t, BottomT):
                    raise self.unknown(item)
                if not isinstance(value.t, (TupleT, OptT)):
                    raise self.error('*аргумент должен быть кортежем известной длины', item)
                tuple_t = value.t.inner if isinstance(value.t, OptT) else value.t
                holder = self.hoist(Value(tuple_t, value.code if isinstance(value.t, TupleT)
                                          else f'P2C_UNWRAP({value.code})'))
                for index, element in enumerate(tuple_t.items):
                    part = Value(element, f'({holder.code}).v{index}')
                    if is_int_like(element) and self.emit:
                        part.cwidth = self.r.cint(element)
                    values.append(part)
                    order.append(part)
                continue
            value = self.value_expr(item)
            self.fix_left(order, mark)
            values.append(value)
            order.append(value)
        for keyword in node.keywords:
            if keyword.arg is None:
                raise self.error('**аргументы не поддержаны', node)
            mark = self.mark()
            value = self.value_expr(keyword.value)
            self.fix_left(order, mark)
            keywords[keyword.arg] = value
            order.append(value)
        return values, keywords

    def arguments_only(self, node: ast.Call) -> None:
        try:
            self.arguments(node)
        except Unknown:
            pass

    def bind(self, plan: Plan, positional: list[Value], keywords: dict[str, Value], node: ast.AST) -> list[Value]:
        params = plan.params
        if len(positional) > len([param for param in params if not param.keyword_only]):
            raise self.error(f'{plan.name}: лишние позиционные аргументы', node)
        bound: list[Value | None] = [None] * len(params)
        for index, value in enumerate(positional):
            bound[index] = value
        for name, value in keywords.items():
            for index, param in enumerate(params):
                if param.name == name:
                    if bound[index] is not None:
                        raise self.error(f'{plan.name}: аргумент {name} задан дважды', node)
                    bound[index] = value
                    break
            else:
                raise self.error(f'{plan.name}: нет параметра {name}', node)
        for index, param in enumerate(params):
            if bound[index] is None:
                if param.default is None:
                    raise self.error(f'{plan.name}: не задан аргумент {param.name}', node)
                bound[index] = self.default_value(plan, param.default)
        return bound

    def default_value(self, plan: Plan, node: ast.expr) -> Value:
        """Умолчание параметра: константа модуля функции (вычисляется при определении)."""
        if isinstance(node, ast.Constant):
            return self.expr_Constant(node)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub) and isinstance(node.operand, ast.Constant):
            return self.int_const(-node.operand.value)
        module = self.p.modules[plan.module].python
        if isinstance(node, ast.Name) and hasattr(module, node.id):
            return self.global_value(node.id, getattr(module, node.id), node)
        if isinstance(node, ast.Tuple):
            values = [self.default_value(plan, item) for item in node.elts]
            t = TupleT(tuple(value.t for value in values))
            if not self.emit:
                return Value(t, 'p2c_default', const=tuple(value.const for value in values))
            name = self.temp(t)
            for index, value in enumerate(values):
                self.line(f'{name}.v{index} = {self.convert(value, t.items[index], node)};')
            return Value(t, name, const=tuple(value.const for value in values))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ('list', 'dict', 'set') \
                and not node.args:
            return self.call_builtin(node.func.id, node)
        if isinstance(node, ast.Attribute):
            try:
                value = eval(ast.unparse(node), vars(module))
            except Exception as error:
                raise self.error(f'умолчание {ast.unparse(node)} не вычисляется: {error}', node)
            return self.global_value(ast.unparse(node), value, node)
        raise self.error(f'умолчание {ast.unparse(node)} не поддержано', node)

    # --- вызов функции транслятора -----------------------------------------------

    def call_plan(self, plan: Plan, positional: list[Value], keywords: dict, node: ast.AST,
                  env: str | None = None, prefix: list[str] | None = None) -> Value:
        values = self.bind(plan, positional, keywords, node)
        self.plan.callees.add(plan.key)
        codes = list(prefix or [])
        if env is not None:
            codes.append(env)
        for position, (param, value) in enumerate(zip(plan.params, values)):
            if position == 0 and plan.kind in ('method', 'property') and isinstance(param.declared, ObjT):
                # self метода: класс реализации (диспетчеризация гарантирует подкласс).
                param.t = param.declared
                if self.emit:
                    codes.append(self.convert(value, param.declared, node))
                continue
            if not self.emit:
                if not isinstance(value.t, BottomT):
                    param.t = self.c.grow(param.t, self.flow_type(value, param.declared, node), node,
                                          self.plan.filename)
                    self.note_flow(value, param.t)
                continue
            target = self.resolved(param.t, param.declared)
            codes.append(self.struct_argument(self.convert(value, target, node), target))
        if not self.emit:
            ret = plan.ret if not isinstance(plan.ret, BottomT) else (plan.ret_declared if self.strict else BOTTOM)
            if ret is None or isinstance(ret, BottomT):
                if plan.ret_declared is not None and isinstance(plan.ret_declared, VoidT):
                    return Value(VOID, 'p2c_call')
                raise Unknown()
            return Value(ret, 'p2c_call')
        call = f'{plan.c_name}({", ".join(codes)})'
        return self.call_result(plan, call)

    def call_result(self, plan: Plan, call: str) -> Value:
        ret = self.resolved(plan.ret, plan.ret_declared)
        if ret is None or isinstance(ret, (VoidT, NoneT)) or (isinstance(ret, BottomT) and
                                                             isinstance(plan.ret_declared, VoidT)):
            return Value(VOID, call)
        if isinstance(ret, BottomT):
            raise self.error(f'результат {plan.name} не выведен', plan.node)
        width = self.r.cint(ret) if is_int_like(ret) else None
        if plan.pure:
            return Value(ret, call, width)
        name = self.temp(ret)
        if width is not None:
            self.plan.temps[name] = ('cint', width)
        self.line(f'{name} = {call};')
        return Value(ret, name, width)

    def flow_type(self, value: Value, declared: T | None, node: ast.AST) -> T:
        """Форма потока в ячейку: объявленный контейнер уточняет пустые литералы."""
        t = value.t
        if declared is not None and contains_bottom(t) and not isinstance(declared, BottomT):
            try:
                return self.c.join(declared, t, node, self.plan.filename)
            except Exception:
                return t
        return t

    # --- методы объектов ----------------------------------------------------------

    def call_method(self, owner: Value, attr: str, positional: list[Value], keywords: dict,
                    node: ast.AST) -> Value:
        t = owner.t
        if isinstance(t, OptT):
            owner = Value(t.inner, owner.code if is_pointer(t.inner) else f'P2C_UNWRAP({owner.code})', path=owner.path)
            t = owner.t
        if isinstance(t, ValT):
            found = self.p.find_method(t.cls, attr)
            if found is None:
                raise self.error(f'нет метода {t.cls}.{attr}', node)
            plan = self.c.request_method(found[0].name, attr, node, self.plan.filename)
            if plan.kind == 'staticmethod':
                return self.call_plan(plan, positional, keywords, node)
            return self.call_plan(plan, [owner, *positional], keywords, node)
        if not isinstance(t, ObjT):
            raise self.error(f'метод {attr} у {describe(t)} не поддержан', node)
        extern = self.c.extern_methods.get((t.cls, attr))
        if extern is not None:
            return self.call_extern(extern, positional, node)
        implementations = self.method_implementations(t.cls, attr, node)
        if not implementations:
            if self.emit:
                raise self.error(f'нет реализаций {t.cls}.{attr} у созданных классов', node)
            raise Unknown()
        plans = []
        for impl_class, classes in implementations.items():
            plan = self.c.request_method(impl_class, attr, node, self.plan.filename)
            plans.append((plan, classes))
        first_plan = plans[0][0]
        if first_plan.kind == 'staticmethod':
            if len(plans) != 1:
                raise self.error(f'виртуальный staticmethod {attr} не поддержан', node)
            return self.call_plan(first_plan, positional, keywords, node)
        if len(plans) == 1:
            return self.call_plan(first_plan, [owner, *positional], keywords, node)
        return self.virtual_call(owner, attr, plans, positional, keywords, node)

    def method_implementations(self, class_name: str, attr: str, node: ast.AST) -> dict[str, list[str]]:
        """Реализация метода для каждого созданного класса формы ObjT(class_name)."""
        result: dict[str, list[str]] = {}
        classes = self.c.live_classes(class_name)
        for name in classes:
            found = self.p.find_method(name, attr)
            if found is None:
                continue
            result.setdefault(found[0].name, []).append(name)
        return result

    def virtual_call(self, owner: Value, attr: str, plans: list, positional: list[Value], keywords: dict,
                     node: ast.AST) -> Value:
        """Вызов по номеру класса: переход к реализации каждого созданного класса."""
        if not self.emit:
            result = BOTTOM
            known = False
            for plan, _classes in plans:
                try:
                    value = self.call_plan(plan, [owner, *positional], keywords, node)
                    if not isinstance(value.t, VoidT):
                        result = self.c.join(result, value.t, node, self.plan.filename)
                    known = True
                except Unknown:
                    pass
            if isinstance(result, BottomT):
                if known and all(isinstance(self.resolved(plan.ret, plan.ret_declared), VoidT) or
                                 isinstance(plan.ret_declared, VoidT) for plan, _ in plans):
                    return Value(VOID, 'p2c_vcall')
                raise Unknown()
            return Value(result, 'p2c_vcall')
        holder = self.hoist(owner)
        rets = [self.resolved(plan.ret, plan.ret_declared) for plan, _ in plans]
        voids = all(isinstance(ret, (VoidT, NoneT)) or ret is None for ret in rets)
        result_t = VOID if voids else self.c.join_all([ret for ret in rets if not isinstance(ret, VoidT)],
                                                      node, self.plan.filename)
        result = None if voids else self.temp(result_t)
        argument_holders = [self.hoist(value) for value in positional]
        keyword_holders = {name: self.hoist(value) for name, value in keywords.items()}
        self.line(f'switch (P2C_CLS({holder.code})) {{')
        for plan, classes in plans:
            for class_name in classes:
                self.line(f'case {self.c.layout.class_id_symbol(class_name)}:')
            self.indent += 1
            value = self.call_plan(plan, [holder, *argument_holders], keyword_holders, node)
            if result is not None:
                self.line(f'{result} = {self.convert(value, result_t, node)};')
            elif value.code and not self.stable(value.code):
                self.line(f'{value.code};')
            self.line('break;')
            self.indent -= 1
        self.line('default: p2c_raise(P2C_E_DISPATCH);')
        self.line('}')
        if result is None:
            return Value(VOID, '')
        value = Value(result_t, result)
        if is_int_like(result_t):
            value.cwidth = self.r.cint(result_t)
        return value

    def call_super(self, class_name: str, self_value: Value, attr: str, node: ast.Call) -> Value:
        """super().метод(...): реализация по MRO начиная с базы класса-владельца."""
        info = self.p.classes[class_name]
        if not info.bases:
            if info.list_base is not None and attr in ('append', '__init__', 'extend', 'clear'):
                if attr == '__init__':
                    return Value(VOID, '')
                list_value = self.as_list_base(self_value, node)
                return self.call_builtin_method(list_value, attr, node)
            raise self.error(f'super().{attr} без базы пакета', node)
        base = info.bases[0]
        found = self.p.find_method(base, attr)
        if found is None:
            if attr == '__init__':
                if node.args or node.keywords:
                    raise self.error('super().__init__ object с аргументами', node)
                return Value(VOID, '')
            if self.p.list_base_of(base) is not None:
                return self.call_builtin_method(self.as_list_base(self_value, node), attr, node)
            raise self.error(f'нет {base}.{attr} для super()', node)
        plan = self.c.request_method(found[0].name, attr, node, self.plan.filename)
        positional, keywords = self.arguments(node, [self_value])
        return self.call_plan(plan, positional, keywords, node)

    def call_class_method(self, class_name: str, impl_class: str, attr: str, node: ast.Call) -> Value:
        info = self.p.classes[impl_class]
        kind = info.method_kind(attr)
        if kind == 'staticmethod':
            plan = self.c.request_method(impl_class, attr, node, self.plan.filename)
            positional, keywords = self.arguments(node)
            return self.call_plan(plan, positional, keywords, node)
        if kind == 'classmethod':
            plan = self.c.request_method(impl_class, attr, node, self.plan.filename, cls=class_name)
            positional, keywords = self.arguments(node)
            return self.call_plan(plan, positional, keywords, node)
        # Явный вызов метода через класс: Class.method(obj, ...).
        plan = self.c.request_method(impl_class, attr, node, self.plan.filename)
        positional, keywords = self.arguments(node)
        return self.call_plan(plan, positional, keywords, node)

    def call_extern(self, extern, positional: list[Value], node: ast.AST) -> Value:
        self.plan.writes = True
        codes = []
        for param_t, value in zip(extern.params, positional):
            if isinstance(value.t, BottomT):
                raise self.unknown(node)
            codes.append(self.convert(value, param_t if not int_empty(param_t) else INT_TOP, node)
                         if self.emit else value.code)
        call = f'{extern.c_name}({", ".join(codes)})'
        if isinstance(extern.ret, VoidT):
            return Value(VOID, call)
        if not self.emit:
            return Value(extern.ret, call)
        name = self.temp(extern.ret)
        self.line(f'{name} = {call};')
        value = Value(extern.ret, name)
        if is_int_like(extern.ret):
            value.cwidth = self.r.cint(extern.ret)
        return value

    # --- конструкторы -------------------------------------------------------------

    def construct(self, class_name: str, node: ast.Call) -> Value:
        info = self.p.classes[class_name]
        self.plan.writes = True
        if info.frozen:
            return self.construct_value(class_name, node)
        self.c.note_instantiated(class_name)
        self.plan.allocates = True
        found = self.p.find_method(class_name, '__init__')
        t = ObjT(class_name)
        if not self.emit:
            obj = Value(t, 'p2c_new')
        else:
            obj = Value(t, self.temp(t))
            self.line(f'{obj.code} = {self.c.layout.new_object_code(class_name)};')
        if found is None:
            if node.args or node.keywords:
                raise self.error(f'{class_name}() без __init__ с аргументами', node)
            return obj
        plan = self.c.request_method(found[0].name, '__init__', node, self.plan.filename)
        positional, keywords = self.arguments(node, [obj])
        value = self.call_plan(plan, positional, keywords, node)
        if self.emit and value.code and not self.stable(value.code):
            self.line(f'{value.code};')
        return obj

    def construct_value(self, class_name: str, node: ast.Call) -> Value:
        """Неизменяемый dataclass: структура по значению из аргументов __init__."""
        info = self.p.classes[class_name]
        found = self.p.find_method(class_name, '__init__')
        if found is None or found[1] is not found[0].synthesized.get('__init__'):
            raise self.error(f'{class_name}: неизменяемый класс со своим __init__ не поддержан', node)
        plan = self.c.request_method(found[0].name, '__init__', node, self.plan.filename)
        positional, keywords = self.arguments(node)
        placeholder = Value(ValT(class_name), 'p2c_self')
        values = self.bind(plan, [placeholder, *positional], keywords, node)[1:]
        t = ValT(class_name)
        if not self.emit:
            for param, value in zip(plan.params[1:], values):
                if isinstance(value.t, BottomT):
                    raise Unknown()
                cell = self.c.field_cell(class_name, param.name)
                cell.classes.add(class_name)
                cell.t = self.c.grow(cell.t, self.flow_type(value, cell.declared, node), node, self.plan.filename)
            return Value(t, 'p2c_value')
        name = self.temp(t)
        for param, value in zip(plan.params[1:], values):
            field_t = self.c.field_type(class_name, param.name)
            self.line(f'{name}.{cname(param.name)} = {self.convert(value, field_t, node)};')
        return Value(t, name)

    # --- вызываемые значения -----------------------------------------------------

    def call_callable(self, target: Value, node: ast.Call) -> Value:
        t = target.t
        if isinstance(t, OptT):
            t = t.inner
        if not isinstance(t, FnT):
            raise self.error(f'вызов {describe(target.t)}', node)
        self.plan.writes = True
        positional, keywords = self.arguments(node)
        if keywords:
            raise self.error('именованные аргументы вызываемого значения не поддержаны', node)
        if not t.ids:
            raise self.unknown(node, 'вызываемое значение без известных целей')
        results = []
        for number in sorted(t.ids):
            key, plan = self.c.fn_targets[number]
            if plan is None:
                extern = self.c.extern_by_key(key)
                results.append(extern.ret)
                continue
            self.plan.callees.add(plan.key)
            params = plan.params[1:] if key[0] in ('bound',) else plan.params
            if len(params) != len(positional):
                raise self.error(f'вызываемое значение: {plan.name} ожидает {len(params)} аргументов', node)
            if not self.emit:
                for param, value in zip(params, positional):
                    if not isinstance(value.t, BottomT):
                        param.t = self.c.grow(param.t, value.t, node, self.plan.filename)
            results.append(self.resolved(plan.ret, plan.ret_declared))
        if not self.emit:
            known = [item for item in results if item is not None and not isinstance(item, BottomT)]
            if any(isinstance(item, VoidT) for item in known) or not known:
                if not known and any(item is None or isinstance(item, BottomT) for item in results):
                    raise Unknown()
                return Value(VOID, 'p2c_fcall')
            return Value(self.c.join_all(known, node, self.plan.filename), 'p2c_fcall')
        dispatcher = self.c.layout.dispatcher(t.ids, len(positional))
        holder = self.hoist(Value(t, target.code if isinstance(target.t, FnT) else target.code))
        codes = [holder.code]
        for position, value in enumerate(positional):
            codes.append(self.struct_argument(self.convert(value, dispatcher.params[position], node),
                                              dispatcher.params[position]))
        call = f'{dispatcher.c_name}({", ".join(codes)})'
        if isinstance(dispatcher.ret, VoidT):
            return Value(VOID, call)
        name = self.temp(dispatcher.ret)
        self.line(f'{name} = {call};')
        value = Value(dispatcher.ret, name)
        if is_int_like(dispatcher.ret):
            value.cwidth = self.r.cint(dispatcher.ret)
        return value

    def expr_Lambda(self, node: ast.Lambda) -> Value:
        plan = self.c.request_lambda(self.plan, node)
        return self.function_value(plan, node)

    def function_value(self, plan: Plan, node: ast.AST) -> Value:
        """Создание вызываемого значения (лямбда или вложенная функция как значение)."""
        number = self.c.fn_value(('plan', plan.key), plan)
        plan.fn_id = number
        t = FnT(tuple(param.t for param in plan.params), plan.ret, frozenset({number}))
        if not self.emit:
            return Value(t, 'p2c_fn')
        env = self.escaping_env(plan, node)
        return Value(t, self.fn_make(t, self.c.layout.fn_id_symbol(number), env))

    def bound_method_value(self, owner: Value, attr: str, node: ast.AST) -> Value:
        t = owner.t
        if isinstance(t, OptT):
            t = t.inner
        if not isinstance(t, ObjT):
            raise self.error(f'связанный метод у {describe(t)}', node)
        implementations = self.method_implementations(t.cls, attr, node)
        extern = self.c.extern_methods.get((t.cls, attr))
        if extern is not None:
            number = self.c.fn_value(('extern_method', t.cls, attr), None)
            ft = FnT(extern.params, extern.ret, frozenset({number}))
            return Value(ft, self.fn_make(ft, self.c.layout.fn_id_symbol(number), owner.code)
                         if self.emit else 'p2c_fn')
        if not implementations:
            raise self.unknown(node, f'связанный метод {t.cls}.{attr}')
        ids = []
        plans = []
        for impl_class, classes in implementations.items():
            plan = self.c.request_method(impl_class, attr, node, self.plan.filename)
            number = self.c.fn_value(('bound', plan.key), plan)
            plan.fn_id = number
            ids.append((number, classes))
            plans.append(plan)
            plan.params[0].t = self.c.grow(plan.params[0].t, t, node, self.plan.filename) if not self.emit else plan.params[0].t
        params = tuple(param.t for param in plans[0].params[1:])
        ret = plans[0].ret
        ft = FnT(params, ret, frozenset(number for number, _ in ids))
        if not self.emit:
            return Value(ft, 'p2c_fn')
        holder = self.hoist(owner)
        if len(ids) == 1:
            return Value(ft, self.fn_make(ft, self.c.layout.fn_id_symbol(ids[0][0]), holder.code))
        result = self.temp(ft)
        self.line(f'switch (P2C_CLS({holder.code})) {{')
        for number, classes in ids:
            for class_name in classes:
                self.line(f'case {self.c.layout.class_id_symbol(class_name)}:')
            self.line(f'    P2C_FN_SET({result}, {self.c.layout.fn_id_symbol(number)}, {holder.code}); break;')
        self.line('default: p2c_raise(P2C_E_DISPATCH);')
        self.line('}')
        return Value(ft, result)

    # --- окружение вложенных функций -----------------------------------------------

    def nested_env(self, plan: Plan, node: ast.AST) -> str | None:
        """Окружение прямого вызова вложенной функции: структура на стеке C."""
        if not plan.captures:
            return None
        if not self.emit:
            return 'p2c_env'
        if self.c.layout.env_is_direct(plan):
            capture = plan.captures[0]
            source = self.expr(ast.Name(id=capture.name, ctx=ast.Load(), lineno=getattr(node, 'lineno', 0),
                                        col_offset=0))
            return self.convert(source, capture.t, node)
        env = self.temp(('env', plan.c_name))
        for capture in plan.captures:
            source = self.expr(ast.Name(id=capture.name, ctx=ast.Load(), lineno=getattr(node, 'lineno', 0),
                                        col_offset=0))
            if capture.by_pointer:
                if not source.code.replace('_', 'a').isalnum():
                    raise self.error(f'захват {capture.name} по ссылке требует локальной переменной', node)
                self.line(f'{env}.{cname(capture.name)} = &{source.code};')
            else:
                self.line(f'{env}.{cname(capture.name)} = {self.convert(source, capture.t, node)};')
        return f'&{env}'

    def escaping_env(self, plan: Plan, node: ast.AST) -> str:
        """Окружение вызываемого значения: объект кучи (или единственный захваченный объект)."""
        if not plan.captures:
            return 'NULL'
        if any(capture.by_pointer for capture in plan.captures):
            raise self.error(f'{plan.name}: захват изменяемой переменной вызываемым значением не поддержан', node)
        if self.c.layout.env_is_direct(plan):
            capture = plan.captures[0]
            source = self.expr(ast.Name(id=capture.name, ctx=ast.Load(), lineno=getattr(node, 'lineno', 0),
                                        col_offset=0))
            return f'(void *){source.code}'
        self.plan.allocates = True
        env = self.temp(('envptr', plan.c_name))
        self.line(f'{env} = {self.c.layout.new_env_code(plan)};')
        for capture in plan.captures:
            source = self.expr(ast.Name(id=capture.name, ctx=ast.Load(), lineno=getattr(node, 'lineno', 0),
                                        col_offset=0))
            self.line(f'{env}->{cname(capture.name)} = {self.convert(source, capture.t, node)};')
        return f'(void *){env}'
