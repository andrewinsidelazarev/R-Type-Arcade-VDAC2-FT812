"""Инструкции: присваивания, ветвления, циклы, возвраты, исключения, удаление."""
from __future__ import annotations

import ast
import linecache

from .compiler import describe, int_empty
from .errors import TranslationError
from .fn_base import NO_CONST, Unknown, Value, cname
from .intervals import TOP, Interval
from .ptypes import (
    BOOL, BOTTOM, I16, I32, INT_TOP, NONE, U16, U8, VOID, ArrayT, BoolT, BottomT, BytesT, DequeT,
    DictT, FnT, ImageT, IntT, ListT, NoneT, ObjT, OptT, SetT, StrT, T, TupleT, ValT, VoidT, contains_bottom,
    is_int_like, is_pointer,
)


def source_text(filename: str, node: ast.stmt) -> str:
    """Первая строка исходника Python инструкции — для комментария сгенерированного C: без концов комментария C,
    без триграфов (??/ в конце строки склеил бы её со следующей), не длиннее 100 знаков."""
    text = linecache.getline(filename, node.lineno).strip()
    text = text.replace('*/', '* /').replace('/*', '/ *').replace('??', '? ?').replace('\\', '\\ ')
    return text if len(text) <= 100 else text[:97] + '...'


class StmtMixin:
    def run(self) -> None:
        node = self.plan.node
        if not self.emit:
            self.plan.errors = []
        else:
            self.plan.tables = []
            native = self.c.native_bodies.get(self.plan.key)
            if native is not None:
                self.plan.lines = list(native(self))
                return
        if isinstance(node, ast.Lambda):
            self.lambda_body(node)
        else:
            body = node.body
            if (body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                body = body[1:]
            self.statements(body)
        if self.emit:
            self.plan.lines = self.lines

    def lambda_body(self, node: ast.Lambda) -> None:
        try:
            value = self.value_expr(node.body)
        except Unknown:
            return
        self.return_value(value, node)

    def statements(self, nodes: list[ast.stmt]) -> None:
        for node in nodes:
            method = getattr(self, 'stmt_' + type(node).__name__, None)
            if method is None:
                raise self.error(f'инструкция {type(node).__name__} не поддержана', node)
            if self.emit:
                where = f'{self.plan.filename.replace(chr(92), "/").rsplit("/", 1)[-1]}:{node.lineno}'
                self.line(f'P2C_LINE({self.c.line_index(where)}); /* {where} — {source_text(self.plan.filename, node)} */')
            if self.emit:
                method(node)
                continue
            try:
                method(node)
            except Unknown:
                if self.c.pessimistic and self.c.debug_unknown == self.plan.c_name:
                    import traceback
                    print(f'[неизвестно] {self.plan.c_name} строка {node.lineno}:',
                          ''.join(traceback.format_exc().splitlines(True)[-6:]), flush=True)
                continue
            except TranslationError as error:
                # Ошибка может исчезнуть в следующих проходах (ветвь окажется недостижимой).
                if not self.plan.errors:
                    self.plan.errors.append(error)
                continue

    def stmt_Pass(self, node: ast.Pass) -> None:
        return

    def stmt_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Вложенная функция: план создаётся при вызове или использовании как значения."""
        if node.decorator_list:
            raise self.error('декоратор вложенной функции не поддержан', node)

    def stmt_Expr(self, node: ast.Expr) -> None:
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            return
        value = self.expr(node.value)
        if value.meta is not None:
            return
        if value.code and not self.stable(value.code):
            self.line(f'{value.code};')

    # --- присваивания --------------------------------------------------------------

    def refine_path(self, owner: Value, new_t: T, node: ast.AST) -> None:
        """Уточнить форму ячейки, из которой пришло значение контейнера."""
        cell = owner.cell
        if cell is None:
            return
        kind = cell[0]
        if kind == 'local':
            current = self.plan.locals.get(cell[1], BOTTOM)
            self.plan.locals[cell[1]] = self.c.grow(current, new_t, node, self.plan.filename)
        elif kind == 'param':
            param = self.param(cell[1])
            param.t = self.c.grow(param.t, new_t, node, self.plan.filename)
        elif kind == 'field':
            self.c.store_field(cell[1], cell[2], new_t, node, self.plan.filename)

    def stmt_Assign(self, node: ast.Assign) -> None:
        if (isinstance(node.value, ast.Call) and ast.unparse(node.value.func) == 'struct.unpack_from' and
                len(node.targets) == 1 and isinstance(node.targets[0], (ast.Tuple, ast.List))):
            values = self.unpack_from(node.value)
            names = node.targets[0].elts
            if len(values) != len(names):
                raise self.error('распаковка unpack_from: число полей не совпадает', node)
            for name_node, value in zip(names, values):
                self.assign_target(name_node, value, node)
            return
        if isinstance(node.value, ast.GeneratorExp):
            # Распаковка генератора: элементы вычисляются до присваиваний, как в CPython.
            value = self.collect(node.value, 'array', node)
        else:
            value = self.value_expr(node.value)
        if isinstance(value.t, VoidT):
            raise self.error('присваивание результата без значения', node)
        if len(node.targets) > 1 or not isinstance(node.targets[0], ast.Name):
            value = self.hoist(value)
        for target in node.targets:
            self.assign_target(target, value, node)

    def stmt_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is None:
            return
        from .annotations import parse_annotation
        declared = parse_annotation(self.c, node.annotation, self.plan.module, self.plan.filename)
        value = self.value_expr(node.value)
        if not self.emit and isinstance(node.target, ast.Name) and not isinstance(declared, BottomT):
            key = self.local_key(node.target.id)
            current = self.plan.locals.get(key, BOTTOM)
            try:
                shaped = self.c.join(declared, value.t, node, self.plan.filename) if contains_bottom(value.t) \
                    else value.t
            except Exception:
                shaped = value.t
            self.plan.locals[key] = self.c.grow(current, self.shape_only(shaped, value.t), node, self.plan.filename)
        self.assign_target(node.target, value, node, declared)

    def shape_only(self, shaped: T, actual: T) -> T:
        """Объявленная форма пустого литерала без искусственных интервалов."""
        return shaped

    def assign_target(self, target: ast.expr, value: Value, node: ast.AST, declared: T | None = None) -> None:
        if isinstance(target, ast.Name):
            self.assign_name(target.id, value, node, declared)
            return
        if isinstance(target, ast.Attribute):
            self.assign_attribute(target, value, node, declared)
            return
        if isinstance(target, ast.Subscript):
            self.assign_subscript(target, value, node)
            return
        if isinstance(target, (ast.Tuple, ast.List)):
            self.unpack(target, value, node)
            return
        raise self.error(f'цель присваивания {ast.unparse(target)} не поддержана', target)

    def assign_name(self, name: str, value: Value, node: ast.AST, declared: T | None = None) -> None:
        key = self.local_key(name)
        if name in self.capture_names:
            raise self.error(f'присваивание захваченной переменной {name} не поддержано', node)
        is_param = key in self.param_names and not any(name in scope for scope in self.scopes)
        flow = self.flow_type(value, declared, node) if declared is not None else value.t
        if not self.emit:
            if isinstance(flow, BottomT):
                raise Unknown()
            if is_param:
                param = self.param(name)
                param.t = self.c.grow(param.t, flow, node, self.plan.filename)
                self.note_flow(value, param.t)
            else:
                current = self.plan.locals.get(key, BOTTOM)
                self.plan.locals[key] = self.c.grow(current, flow, node, self.plan.filename)
                self.note_flow(value, self.plan.locals[key])
            self.kill_refinement(key)
            self.kill_present(name)
            return
        if is_param:
            param = self.param(name)
            target_t = self.resolved(param.t, param.declared)
        else:
            target_t = self.plan.locals.get(key, BOTTOM)
        if isinstance(target_t, BottomT):
            raise self.error(f'форма переменной {name} не выведена', node)
        self.kill_refinement(key)
        self.kill_present(name)
        code = self.convert(value, target_t, node)
        c_name = cname(key) if key == name else key
        self.line(f'{c_name} = {code};')

    def bind_target(self, target: ast.expr, value: Value, node: ast.AST) -> None:
        """Цель цикла или включения."""
        if isinstance(target, ast.Name):
            self.assign_name(target.id, value, node)
            return
        if isinstance(target, (ast.Tuple, ast.List)):
            self.unpack(target, value, node)
            return
        raise self.error('цель цикла должна быть именем или кортежем', target)

    def assign_attribute(self, target: ast.Attribute, value: Value, node: ast.AST,
                         declared: T | None = None) -> None:
        self.plan.writes = True
        mark = self.mark()
        owner = self.value_expr(target.value)
        self.fix_left([value], mark)
        t = owner.t
        if self.incomplete(t):
            raise self.unknown(node)
        if isinstance(t, OptT):
            owner = Value(t.inner, owner.code, path=owner.path)
            t = t.inner
        path = self.path_text(target)
        if path is not None:
            self.kill_present(path)
        if isinstance(t, ObjT):
            if t.cls == '*':
                self.any_setattr(self.hoist(owner), target.attr, value, node)
                return
            if not self.emit:
                flow = self.flow_type(value, declared, node) if declared is not None else value.t
                if isinstance(flow, BottomT):
                    raise Unknown()
                cell = self.c.store_field(t.cls, target.attr, flow, node, self.plan.filename)
                self.note_flow(value, cell.t)
                return
            field_t = self.c.field_type(t.cls, target.attr)
            code = self.convert(value, field_t, node)
            presence = self.c.layout.presence_set(owner.code, t.cls, target.attr)
            if presence:
                owner = self.hoist(owner)
            self.line(f'{self.c.layout.field_code(owner.code, t.cls, target.attr)} = {code}; {presence}'.rstrip())
            return
        raise self.error(f'запись атрибута {target.attr} у {describe(t)} не поддержана', node)

    def assign_subscript(self, target: ast.Subscript, value: Value, node: ast.AST) -> None:
        self.plan.writes = True
        mark = self.mark()
        container = self.value_expr(target.value)
        self.fix_left([value], mark)
        t = container.t
        if self.incomplete(t):
            raise self.unknown(node)
        if isinstance(t, ObjT) and t.cls != '*' and self.p.list_base_of(t.cls) is not None:
            container = self.as_list_base(container, node)
            t = container.t
        if isinstance(target.slice, ast.Slice):
            self.assign_slice(container, target.slice, value, node)
            return
        index_mark = self.mark()
        index = self.value_expr(target.slice)
        self.fix_left([container, value], index_mark)
        if isinstance(t, DictT):
            self.dict_store(container, index, value, node)
            return
        if isinstance(t, (ListT, DequeT)):
            if not self.emit:
                if not isinstance(value.t, BottomT):
                    new_t = type(t)(self.c.join(t.elem, value.t, node, self.plan.filename))
                    if new_t != t:
                        self.refine_path(container, new_t, node)
                return
            position = self.normalize_index(container, index, node)
            accessor = 'P2C_PUT' if isinstance(t, ListT) else 'P2C_DEQUE_PUT'
            self.line(f'{accessor}({container.code}, {self.ctype(t.elem)}, {position}, '
                      f'{self.convert(value, t.elem, node)});')
            return
        if isinstance(t, BytesT):
            if not t.mutable:
                raise self.error('запись в bytes', node)
            if not self.emit:
                return
            value = self.int_value(value, node)
            interval = self.interval_of(value) or TOP
            position = self.normalize_index(container, index, node)
            if interval.within(0, 255):
                self.line(f'P2C_BYTE_PUT({container.code}, {position}, {self.cast(value, U8, node)});')
            else:
                self.line(f'P2C_BYTE_PUT({container.code}, {position}, p2c_byte_value({self.cast(value, I32, node)}));')
            return
        raise self.error(f'запись элемента {describe(t)} не поддержана', node)

    def assign_slice(self, container: Value, slice_node: ast.Slice, value: Value, node: ast.AST) -> None:
        t = container.t
        if slice_node.lower is not None or slice_node.upper is not None or slice_node.step is not None:
            raise self.error('присваивание срезу поддержано только для [:]', node)
        if isinstance(t, BytesT):
            if not isinstance(value.t, BytesT):
                raise self.error('bytearray[:] = не bytes', node)
            if self.emit:
                self.line(f'p2c_buf_assign({container.code}, {value.code});')
            return
        if isinstance(t, ListT):
            if not self.emit:
                try:
                    element = self.iteration_element_type(value.t, node)
                    new_t = ListT(self.c.join(t.elem, element, node, self.plan.filename))
                    if new_t != t:
                        self.refine_path(container, new_t, node)
                except Unknown:
                    pass
                return
            holder = self.hoist(container)
            copy = self.collect_from_value(value, 'list', node)
            self.line(f'p2c_list_clear({holder.code});')
            self.extend_from(holder, copy, node)
            return
        raise self.error(f'присваивание срезу {describe(t)} не поддержано', node)

    def unpack(self, target: ast.Tuple | ast.List, value: Value, node: ast.AST) -> None:
        names = target.elts
        t = value.t
        if self.incomplete(t):
            raise self.unknown(node)
        if isinstance(t, OptT) and isinstance(t.inner, TupleT):
            value = Value(t.inner, f'P2C_UNWRAP({value.code})')
            t = t.inner
        if any(isinstance(item, ast.Starred) for item in names):
            raise self.error('распаковка со * не поддержана', node)
        if isinstance(t, TupleT):
            if len(t.items) != len(names):
                raise self.error('число элементов распаковки не совпадает', node)
            holder = self.hoist(value)
            parts = []
            for index, item in enumerate(t.items):
                part = Value(item, f'({holder.code}).v{index}')
                if is_int_like(item) and self.emit:
                    part.cwidth = self.r.cint(item)
                parts.append(self.hoist(part))
            for name_node, part in zip(names, parts):
                self.assign_target(name_node, part, node)
            return
        if isinstance(t, (ArrayT, ListT)):
            holder = self.hoist(value)
            if self.emit:
                self.line(f'if ({holder.code}->length != {len(names)}) p2c_raise(P2C_E_VALUE);')
            parts = []
            for index in range(len(names)):
                part = Value(t.elem, f'P2C_AT({holder.code}, {self.ctype(t.elem) if self.emit else "int"}, {index})')
                if is_int_like(t.elem) and self.emit:
                    part.cwidth = self.r.cint(t.elem)
                parts.append(self.hoist(part))
            for name_node, part in zip(names, parts):
                self.assign_target(name_node, part, node)
            return
        raise self.error(f'распаковка {describe(t)} не поддержана', node)

    def stmt_AugAssign(self, node: ast.AugAssign) -> None:
        target = node.target
        if isinstance(target, ast.Name):
            current = self.expr(target)
            mark = self.mark()
            right = self.value_expr(node.value)
            self.fix_left([current], mark)
            result = self.binop(current, node.op, right, node.value, node)
            self.assign_name(target.id, result, node)
            return
        if isinstance(target, ast.Attribute):
            self.plan.writes = True
            owner = self.value_expr(target.value)
            owner = self.hoist(owner)
            current = self.attribute(owner, target.attr, target)
            mark = self.mark()
            right = self.value_expr(node.value)
            self.fix_left([current], mark)
            result = self.binop(current, node.op, right, node.value, node)
            self.store_attribute_value(owner, target.attr, result, node)
            return
        if isinstance(target, ast.Subscript):
            self.plan.writes = True
            container = self.hoist(self.value_expr(target.value))
            if isinstance(target.slice, ast.Slice):
                raise self.error('составное присваивание срезу не поддержано', node)
            index = self.value_expr(target.slice)
            index = self.hoist(index)
            current = self.element(container, index, node)
            mark = self.mark()
            right = self.value_expr(node.value)
            self.fix_left([current], mark)
            result = self.binop(current, node.op, right, node.value, node)
            self.store_subscript_value(container, index, result, node)
            return
        raise self.error('цель составного присваивания не поддержана', node)

    def store_attribute_value(self, owner: Value, attr: str, value: Value, node: ast.AST) -> None:
        t = owner.t
        if isinstance(t, OptT):
            owner = Value(t.inner, owner.code)
            t = t.inner
        if not isinstance(t, ObjT) or t.cls == '*':
            raise self.error(f'составное присваивание атрибута у {describe(t)}', node)
        if not self.emit:
            if isinstance(value.t, BottomT):
                raise Unknown()
            self.c.store_field(t.cls, attr, value.t, node, self.plan.filename)
            return
        field_t = self.c.field_type(t.cls, attr)
        self.line(f'{self.c.layout.field_code(owner.code, t.cls, attr)} = {self.convert(value, field_t, node)};')

    def store_subscript_value(self, container: Value, index: Value, value: Value, node: ast.AST) -> None:
        t = container.t
        if isinstance(t, DictT):
            self.dict_store(container, index, value, node)
            return
        if isinstance(t, ObjT) and self.p.list_base_of(t.cls) is not None:
            container = self.as_list_base(container, node)
            t = container.t
        if isinstance(t, ListT):
            if not self.emit:
                if not isinstance(value.t, BottomT):
                    new_t = ListT(self.c.join(t.elem, value.t, node, self.plan.filename))
                    if new_t != t:
                        self.refine_path(container, new_t, node)
                return
            position = self.normalize_index(container, index, node)
            self.line(f'P2C_PUT({container.code}, {self.ctype(t.elem)}, {position}, '
                      f'{self.convert(value, t.elem, node)});')
            return
        if isinstance(t, BytesT):
            if not self.emit:
                return
            value = self.int_value(value, node)
            interval = self.interval_of(value) or TOP
            position = self.normalize_index(container, index, node)
            if interval.within(0, 255):
                self.line(f'P2C_BYTE_PUT({container.code}, {position}, {self.cast(value, U8, node)});')
            else:
                self.line(f'P2C_BYTE_PUT({container.code}, {position}, p2c_byte_value({self.cast(value, I32, node)}));')
            return
        raise self.error(f'составное присваивание элементу {describe(t)} не поддержано', node)

    # --- удаление -------------------------------------------------------------------

    def stmt_Delete(self, node: ast.Delete) -> None:
        for target in node.targets:
            if isinstance(target, ast.Name):
                continue
            if not isinstance(target, ast.Subscript):
                raise self.error(f'del {ast.unparse(target)} не поддержан', node)
            self.plan.writes = True
            container = self.value_expr(target.value)
            t = container.t
            if self.incomplete(t):
                raise self.unknown(node)
            if isinstance(t, ObjT) and self.p.list_base_of(t.cls) is not None:
                container = self.as_list_base(container, node)
                t = container.t
            if isinstance(t, ListT):
                if not self.emit:
                    continue
                holder = self.hoist(container)
                elem_c = self.ctype(t.elem)
                if isinstance(target.slice, ast.Slice):
                    if target.slice.step is not None:
                        raise self.error('del среза с шагом не поддержан', node)
                    lower = self.value_expr(target.slice.lower) if target.slice.lower is not None else self.int_const(0)
                    upper = self.value_expr(target.slice.upper) if target.slice.upper is not None else None
                    upper_code = self.cast(self.int_value(upper, node), I32, node) if upper is not None else 'P2C_SLICE_END'
                    self.line(f'p2c_list_delete_slice({holder.code}, sizeof({elem_c}), '
                              f'{self.cast(self.int_value(lower, node), I32, node)}, {upper_code});')
                else:
                    index = self.normalize_index(holder, self.value_expr(target.slice), node)
                    self.line(f'p2c_list_delete({holder.code}, sizeof({elem_c}), {index}, 1);')
                continue
            if isinstance(t, DictT):
                if not self.emit:
                    continue
                holder = self.hoist(container)
                key = self.key_code(self.value_expr(target.slice), t.k, node)
                self.line(f'if (p2c_dict_find({holder.code}, &{key}) < 0) p2c_raise(P2C_E_KEY);')
                self.line(f'p2c_dict_delete({holder.code}, &{key});')
                continue
            raise self.error(f'del у {describe(t)} не поддержан', node)

    # --- ветвления и циклы --------------------------------------------------------------

    def stmt_If(self, node: ast.If) -> None:
        try:
            condition = self.condition(node.test)
        except Unknown:
            self.analyze_blocks([node.body, node.orelse])
            return
        if condition in ('0', '1'):
            # Постоянное условие: недостижимая ветвь не анализируется и не транслируется.
            taken = node.body if condition == '1' else node.orelse
            self.present |= self.narrowing(node.test, condition == '1')
            self.statements(taken)
            return
        snapshot = [dict(scope) for scope in self.refinements]
        saved_present = set(self.present)
        self.line(f'if ({condition}) {{')
        self.indent += 1
        self.refinements.append(self.condition_refinements(node.test, True))
        self.present = saved_present | self.narrowing(node.test, True)
        self.statements(node.body)
        after_body = set(self.present)
        self.refinements.pop()
        body_terminates = self.terminates(node.body)
        if body_terminates:
            self.refinements = [dict(scope) for scope in snapshot]
        self.indent -= 1
        self.present = saved_present | self.narrowing(node.test, False)
        if node.orelse:
            self.line('} else {')
            self.indent += 1
            self.refinements.append(self.condition_refinements(node.test, False))
            self.statements(node.orelse)
            self.refinements.pop()
            if self.terminates(node.orelse):
                self.refinements = [dict(scope) for scope in snapshot]
            self.indent -= 1
        after_else = set(self.present)
        self.line('}')
        if body_terminates:
            self.present = after_else
            for key, interval in self.condition_refinements(node.test, False).items():
                self.refinements[-1][key] = interval
        elif node.orelse and self.terminates(node.orelse):
            self.present = after_body
            for key, interval in self.condition_refinements(node.test, True).items():
                self.refinements[-1][key] = interval
        else:
            self.present = after_body & after_else

    def analyze_blocks(self, blocks: list[list[ast.stmt]]) -> None:
        """Анализ ветвей при ещё не выведенном условии: формы присваиваний не зависят от него."""
        for block in blocks:
            if block:
                self.refinements.append({})
                self.statements(block)
                self.refinements.pop()

    @staticmethod
    def terminates(body: list[ast.stmt]) -> bool:
        return bool(body) and isinstance(body[-1], (ast.Return, ast.Raise, ast.Continue, ast.Break))

    def stmt_While(self, node: ast.While) -> None:
        if node.orelse:
            raise self.error('while … else не поддержан', node)
        self.kill_assigned_in(node.body)
        saved_present = set(self.present)
        self.line('for (;;) {')
        self.indent += 1
        self.loop_finally.append(len(self.finally_stack))
        try:
            try:
                self.line(f'if (!{self.condition(node.test)}) break;')
                self.refinements.append(self.condition_refinements(node.test, True))
                self.present |= self.narrowing(node.test, True)
            except Unknown:
                self.refinements.append({})
            self.statements(node.body)
            self.refinements.pop()
        finally:
            self.loop_finally.pop()
        self.indent -= 1
        self.line('}')
        self.present = saved_present

    def stmt_For(self, node: ast.For) -> None:
        if node.orelse:
            raise self.error('for … else не поддержан', node)
        self.kill_assigned_in(node.body)
        try:
            loop = self.open_loop(node.iter, node)
        except Unknown:
            self.analyze_blocks([node.body])
            return
        saved_present = set(self.present)
        for name in self.target_names(node.target):
            self.kill_refinement(self.local_key(name))
        try:
            self.bind_target(node.target, loop.element, node)
        except Unknown:
            pass
        refinements = {}
        if isinstance(node.target, ast.Name) and isinstance(loop.element.t, IntT) and \
                isinstance(node.iter, ast.Call) and isinstance(node.iter.func, ast.Name) and \
                node.iter.func.id == 'range' and not int_empty(loop.element.t):
            refinements[self.local_key(node.target.id)] = loop.element.t.interval
        self.refinements.append(refinements)
        self.loop_finally.append(len(self.finally_stack))
        try:
            self.statements(node.body)
        finally:
            self.loop_finally.pop()
            self.refinements.pop()
        self.close_loop(loop)
        self.present = saved_present

    def stmt_Break(self, node: ast.Break) -> None:
        self.run_loop_finally(node)
        self.line('break;')

    def stmt_Continue(self, node: ast.Continue) -> None:
        self.run_loop_finally(node)
        self.line('continue;')

    def run_loop_finally(self, node: ast.AST) -> None:
        if not self.loop_finally:
            return
        depth = self.loop_finally[-1]
        for block in reversed(self.finally_stack[depth:]):
            self.emit_finally(block)

    def emit_finally(self, block: list[ast.stmt]) -> None:
        saved = self.finally_stack
        self.finally_stack = []
        try:
            self.statements(block)
        finally:
            self.finally_stack = saved

    # --- возврат и исключения -------------------------------------------------------------

    def stmt_Return(self, node: ast.Return) -> None:
        if node.value is None:
            if self.finally_stack:
                for block in reversed(self.finally_stack):
                    self.emit_finally(block)
            if not self.emit:
                self.plan.ret = self.c.grow(self.plan.ret, NONE if not isinstance(self.plan.ret_declared, VoidT)
                                            else VOID, node, self.plan.filename) \
                    if not isinstance(self.plan.ret_declared, VoidT) else self.plan.ret
            self.line('return;' if self.void_function() else f'return {self.none_code(self.return_type())};')
            return
        value = self.value_expr(node.value)
        self.return_value(value, node)

    def void_function(self) -> bool:
        ret = self.return_type()
        return ret is None or isinstance(ret, (VoidT, NoneT, BottomT))

    def return_type(self) -> T | None:
        plan = self.plan
        if isinstance(plan.ret, BottomT):
            return plan.ret_declared
        if isinstance(plan.ret_declared, VoidT):
            return plan.ret_declared
        return plan.ret

    def return_value(self, value: Value, node: ast.AST) -> None:
        plan = self.plan
        if not self.emit:
            if isinstance(value.t, BottomT):
                raise Unknown()
            if isinstance(value.t, VoidT):
                return
            flow = self.flow_type(value, plan.ret_declared, node) if plan.ret_declared is not None else value.t
            plan.ret = self.c.grow(plan.ret, flow, node, plan.filename)
            self.note_flow(value, plan.ret)
            return
        ret = self.return_type()
        if ret is None or isinstance(ret, (VoidT, NoneT)):
            if value.code and not self.stable(value.code):
                self.line(f'{value.code};')
            for block in reversed(self.finally_stack):
                self.emit_finally(block)
            self.line('return;')
            return
        code = self.convert(value, ret, node)
        struct_result = not (is_int_like(ret) or is_pointer(ret) or isinstance(ret, (ImageT, OptT)) and
                             (not isinstance(ret, OptT) or is_pointer(ret.inner)))
        if self.finally_stack or (struct_result and not code.replace('_', 'a').isalnum()):
            # Структура возвращается из временной переменной: SDCC ломается на `return f(...)`.
            holder = self.temp(ret)
            if is_int_like(ret):
                self.plan.temps[holder] = ('cint', self.r.cint(ret))
            self.line(f'{holder} = {code};')
            for block in reversed(self.finally_stack):
                self.emit_finally(block)
            code = holder
        self.line(f'return {code};')

    def stmt_Raise(self, node: ast.Raise) -> None:
        text = ast.unparse(node.exc) if node.exc is not None else 'raise'
        index = self.c.raise_index(f'{self.plan.filename.replace(chr(92), "/").rsplit("/", 1)[-1]}:'
                                   f'{node.lineno}: {text[:120]}')
        self.line(f'p2c_raise({index}); /* {text[:60].replace("*/", "")} */')

    def stmt_Assert(self, node: ast.Assert) -> None:
        condition = self.condition(node.test)
        index = self.c.raise_index(f'{self.plan.filename.replace(chr(92), "/").rsplit("/", 1)[-1]}:'
                                   f'{node.lineno}: assert {ast.unparse(node.test)[:100]}')
        self.line(f'if (!{condition}) p2c_raise({index});')
        self.present |= self.narrowing(node.test, True)

    def stmt_Try(self, node: ast.Try) -> None:
        if node.orelse:
            raise self.error('try … else не поддержан', node)
        for handler in node.handlers:
            if not self.terminates(handler.body) or not isinstance(handler.body[-1], ast.Raise):
                raise self.error('except поддержан только с повторным исключением (отказом)', handler)
        if node.finalbody:
            self.finally_stack.append(node.finalbody)
            try:
                self.statements(node.body)
            finally:
                self.finally_stack.pop()
            if not self.terminates(node.body):
                self.statements(node.finalbody)
            return
        self.statements(node.body)

    def stmt_With(self, node: ast.With) -> None:
        raise self.error('with не поддержан', node)

    def stmt_Global(self, node: ast.Global) -> None:
        raise self.error('global не поддержан', node)

    def stmt_Nonlocal(self, node: ast.Nonlocal) -> None:
        raise self.error('nonlocal не поддержан', node)
