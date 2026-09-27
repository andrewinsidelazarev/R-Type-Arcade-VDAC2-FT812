"""Методы контейнеров, строк, struct, цели вывода и модульных функций."""
from __future__ import annotations

import ast
import struct as struct_module

from .compiler import describe, int_empty
from .fn_base import NO_CONST, Unknown, Value, cname
from .intervals import TOP, Interval
from .ptypes import (
    BOOL, BOTTOM, I16, I32, IMAGE, INT_TOP, NONE, STR, U16, U8, VOID, ArrayT, BoolT, BottomT,
    BytesT, DequeT, DictT, FnT, FontT, ImageT, IntT, ListT, NoneT, ObjT, OptT, SetT, StrT, T,
    TargetT, TupleT, ValT, VoidT, ExtT, contains_bottom, is_int_like, is_pointer,
)


class ContainerMixin:
    def call_builtin_method(self, owner: Value, attr: str, node: ast.Call) -> Value:
        t = owner.t
        if self.incomplete(t):
            self.arguments_only(node)
            raise self.unknown(node)
        if isinstance(t, OptT):
            owner = Value(t.inner, owner.code, path=owner.path)
            t = t.inner
        if isinstance(t, ListT):
            return self.list_method(owner, attr, node)
        if isinstance(t, ArrayT):
            return self.array_method(owner, attr, node)
        if isinstance(t, DequeT):
            return self.deque_method(owner, attr, node)
        if isinstance(t, DictT):
            return self.dict_method(owner, attr, node)
        if isinstance(t, SetT):
            return self.set_method(owner, attr, node)
        if isinstance(t, StrT):
            return self.str_method(owner, attr, node)
        if isinstance(t, BytesT):
            return self.bytes_method(owner, attr, node)
        if isinstance(t, TargetT):
            return self.target_method(owner, attr, node)
        if isinstance(t, FontT):
            return self.font_method(owner, attr, node)
        if isinstance(t, ImageT):
            return self.image_method(owner, attr, node)
        if isinstance(t, ValT) and t.cls == 'Rect':
            return self.rect_method(owner, attr, node)
        if isinstance(t, (IntT, BoolT)):
            if attr == 'bit_count' and not node.args:
                value = self.int_value(owner, node)
                interval = self.interval_of(value) or TOP
                if interval.lo >= 0:
                    return Value(IntT(0, max(1, interval.hi.bit_length())),
                                 f'p2c_bit_count((uint32_t){self.cast(value, I32, node)})', U8)
                return Value(IntT(0, 32), f'p2c_bit_count_signed({self.cast(value, I32, node)})', U8)
            raise self.error(f'int.{attr} не поддержан', node)
        if isinstance(t, ExtT):
            extern = self.c.externs.get(t.name, {}).get(attr)
            if extern is None:
                raise self.error(f'метод платформы {t.name}.{attr} не объявлен', node)
            positional, _ = self.arguments(node)
            return self.call_extern(extern, positional, node)
        raise self.error(f'метод {attr} у {describe(t)} не поддержан', node)

    # --- список ------------------------------------------------------------------

    def record_list_store(self, owner: Value, element_t: T, node: ast.AST) -> None:
        """Анализ: форма элемента уточняет форму ячейки, из которой пришёл список."""
        if self.emit or isinstance(element_t, BottomT):
            return
        container_t = owner.t
        joined = self.c.join(container_t.elem, element_t, node, self.plan.filename)
        if joined == container_t.elem and not self.c.iteration >= 8:
            if joined == container_t.elem:
                return
        new_t = type(container_t)(joined)
        self.refine_path(owner, new_t, node)

    def list_method(self, owner: Value, attr: str, node: ast.Call) -> Value:
        t = owner.t
        positional, keywords = self.arguments(node)
        if keywords:
            raise self.error(f'list.{attr} с именованными аргументами', node)
        self.plan.writes = True
        elem_c = self.ctype(t.elem) if self.emit and not contains_bottom(t) else 'int'
        if attr == 'append':
            (value,) = positional
            self.record_list_store(owner, value.t, node)
            if not self.emit:
                return Value(VOID, '')
            holder = self.hoist(owner)
            element = self.hoist(Value(t.elem, self.convert(value, t.elem, node),
                                       self.r.cint(t.elem) if is_int_like(t.elem) else None))
            self.plan.allocates = True
            return Value(VOID, f'P2C_LIST_APPEND({holder.code}, {elem_c}, {element.code})')
        if attr == 'extend':
            (value,) = positional
            if not self.emit:
                try:
                    self.record_list_store(owner, self.iteration_element_type(value.t, node), node)
                except Unknown:
                    pass
                return Value(VOID, '')
            self.plan.allocates = True
            self.extend_from(owner, value, node)
            return Value(VOID, '')
        if attr == 'clear':
            return Value(VOID, f'p2c_list_clear({owner.code})')
        if attr == 'pop':
            if not self.emit:
                return Value(t.elem, 'p2c_pop')
            holder = self.hoist(owner)
            if positional:
                index = self.normalize_index(holder, positional[0], node)
            else:
                index = f'P2C_INDEX({holder.code}, -1)'
            result = self.temp(t.elem)
            self.line(f'{result} = P2C_AT({holder.code}, {elem_c}, {index});')
            self.line(f'p2c_list_delete({holder.code}, sizeof({elem_c}), {index}, 1);')
            value = Value(t.elem, result)
            if is_int_like(t.elem):
                value.cwidth = self.r.cint(t.elem)
            return value
        if attr == 'remove':
            (value,) = positional
            if not self.emit:
                return Value(VOID, '')
            holder = self.hoist(owner)
            index = self.sequence_index_of(holder, value, node)
            self.line(f'if ({index} < 0) p2c_raise(P2C_E_VALUE);')
            self.line(f'p2c_list_delete({holder.code}, sizeof({elem_c}), (uint16_t){index}, 1);')
            return Value(VOID, '')
        if attr == 'insert':
            index, value = positional
            self.record_list_store(owner, value.t, node)
            if not self.emit:
                return Value(VOID, '')
            holder = self.hoist(owner)
            element = self.hoist(Value(t.elem, self.convert(value, t.elem, node),
                                       self.r.cint(t.elem) if is_int_like(t.elem) else None))
            self.plan.allocates = True
            position = self.cast(self.int_value(index, node), I32, node)
            self.line(f'P2C_LIST_INSERT({holder.code}, {elem_c}, {position}, {element.code});')
            return Value(VOID, '')
        if attr == 'index':
            (value,) = positional
            if not self.emit:
                return Value(IntT(0, 65535), 'p2c_index')
            holder = self.hoist(owner)
            index = self.sequence_index_of(holder, value, node)
            self.line(f'if ({index} < 0) p2c_raise(P2C_E_VALUE);')
            return Value(IntT(0, 65535), f'((uint16_t){index})', U16)
        if attr == 'copy':
            return self.collect_from_value(owner, 'list', node)
        raise self.error(f'list.{attr} не поддержан', node)

    def array_method(self, owner: Value, attr: str, node: ast.Call) -> Value:
        if attr in ('index', 'count'):
            positional, _ = self.arguments(node)
            (value,) = positional
            if not self.emit:
                return Value(IntT(0, 65535), 'p2c_index')
            holder = self.hoist(owner)
            index = self.sequence_index_of(holder, value, node)
            self.line(f'if ({index} < 0) p2c_raise(P2C_E_VALUE);')
            return Value(IntT(0, 65535), f'((uint16_t){index})', U16)
        raise self.error(f'tuple.{attr} не поддержан', node)

    def sequence_index_of(self, holder: Value, value: Value, node: ast.AST) -> str:
        t = holder.t
        index = self.temp(IntT(-1, 65535), 'i')
        self.plan.temps[index] = ('cint', I32)
        probe = self.hoist(value)
        self.line(f'for ({index} = 0; {index} < (int32_t){holder.code}->length; {index}++) {{')
        self.indent += 1
        element = Value(t.elem, f'P2C_AT({holder.code}, {self.ctype(t.elem)}, {index})',
                        self.r.cint(t.elem) if is_int_like(t.elem) else None)
        self.line(f'if ({self.compare_code(element, "==", probe, node)}) break;')
        self.indent -= 1
        self.line('}')
        self.line(f'if ({index} >= (int32_t){holder.code}->length) {index} = -1;')
        return index

    def sequence_contains(self, container: Value, item: Value, node: ast.AST) -> str:
        if not self.emit:
            return 'p2c_contains'
        holder = self.hoist(container)
        if isinstance(holder.t, DequeT):
            raise self.error('in для deque не поддержан', node)
        index = self.sequence_index_of(holder, item, node)
        return f'({index} >= 0)'

    def extend_from(self, owner: Value, source: Value, node: ast.AST) -> None:
        t = owner.t
        holder = self.hoist(owner)
        loop = self.open_value_loop(source, node, 'extend')
        element = self.hoist(Value(t.elem, self.convert(loop.element, t.elem, node),
                                   self.r.cint(t.elem) if is_int_like(t.elem) else None))
        self.line(f'P2C_LIST_APPEND({holder.code}, {self.ctype(t.elem)}, {element.code});')
        self.close_loop(loop)

    def sequence_repeat(self, left: Value, right: Value, node: ast.AST) -> Value:
        """[x] * n и (x,) * n: новый список/кортеж повторений."""
        count = self.int_value(right, node)
        t = left.t
        if isinstance(t, TupleT):
            elem = self.c.join_all(t.items, node, self.plan.filename)
            result_t = ArrayT(elem)
        else:
            elem = t.elem
            result_t = ListT(elem) if isinstance(t, ListT) else ArrayT(elem)
        self.plan.allocates = True
        if not self.emit:
            return Value(result_t, 'p2c_repeat', display=node)
        source_elem = elem
        result_t = self.display_type(result_t, node)
        elem = result_t.elem
        source = self.hoist(left)
        times = self.hoist(Value(count.t, self.cast(count, U16, node), U16))
        result = self.temp(result_t)
        elem_c = self.ctype(elem)
        index = self.temp(U16, 'i')
        inner = self.temp(U16, 'j')
        self.line(f'{result} = p2c_list_new({self.container_class(result_t)}, sizeof({elem_c}), 0);')
        if not isinstance(t, TupleT) and self.r.normalized(source_elem) != self.r.normalized(elem):
            # Элементы исходного списка другой ширины: поэлементное преобразование в теле цикла.
            self.line(f'for ({index} = 0; {index} < {times.code}; {index}++) {{')
            self.line(f'    for ({inner} = 0; {inner} < {source.code}->length; {inner}++) {{')
            self.indent += 2
            element = Value(source_elem, f'P2C_AT({source.code}, {self.ctype(source_elem)}, {inner})',
                            self.r.cint(source_elem) if is_int_like(source_elem) else None)
            converted = self.hoist(Value(elem, self.convert(element, elem, node),
                                         self.r.cint(elem) if is_int_like(elem) else None))
            self.line(f'P2C_LIST_APPEND({result}, {elem_c}, {converted.code});')
            self.indent -= 2
            self.line('    }')
            self.line('}')
            return Value(result_t, result)
        if isinstance(t, TupleT):
            items = [self.convert(Value(item, f'({source.code}).v{position}',
                                        self.r.cint(item) if is_int_like(item) else None), elem, node)
                     for position, item in enumerate(t.items)]
            self.line(f'for ({index} = 0; {index} < {times.code}; {index}++) {{')
            for item in items:
                self.line(f'    P2C_LIST_APPEND({result}, {elem_c}, {item});')
            self.line('}')
        else:
            self.line(f'for ({index} = 0; {index} < {times.code}; {index}++) '
                      f'for ({inner} = 0; {inner} < {source.code}->length; {inner}++) '
                      f'P2C_LIST_APPEND({result}, {elem_c}, P2C_AT({source.code}, {elem_c}, {inner}));')
        return Value(result_t, result)

    def sequence_concat(self, left: Value, right: Value, node: ast.AST) -> Value:
        lt, rt = left.t, right.t
        items = []
        for t in (lt, rt):
            if isinstance(t, TupleT):
                items.extend(t.items)
            elif isinstance(t, (ListT, ArrayT)):
                items.append(t.elem)
            else:
                raise self.error(f'+ для {describe(lt)} и {describe(rt)} не поддержан', node)
        if isinstance(lt, TupleT) and isinstance(rt, TupleT):
            result_t = TupleT(lt.items + rt.items)
            if not self.emit:
                return Value(result_t, 'p2c_concat')
            a = self.hoist(left)
            b = self.hoist(right)
            result = self.temp(result_t)
            position = 0
            for source, t in ((a, lt), (b, rt)):
                for index, item in enumerate(t.items):
                    self.line(f'{result}.v{position} = ({source.code}).v{index};')
                    position += 1
            return Value(result_t, result)
        elem = self.c.join_all(items, node, self.plan.filename)
        result_t = ListT(elem) if isinstance(lt, ListT) else ArrayT(elem)
        self.plan.allocates = True
        if not self.emit:
            return Value(result_t, 'p2c_concat')
        result = self.temp(result_t)
        self.line(f'{result} = p2c_list_new({self.container_class(result_t)}, sizeof({self.ctype(elem)}), 0);')
        self.extend_from(Value(result_t, result), left, node)
        self.extend_from(Value(result_t, result), right, node)
        return Value(result_t, result)

    # --- deque ------------------------------------------------------------------

    def deque_method(self, owner: Value, attr: str, node: ast.Call) -> Value:
        t = owner.t
        positional, _ = self.arguments(node)
        self.plan.writes = True
        elem_c = self.ctype(t.elem) if self.emit else 'int'
        if attr == 'append':
            (value,) = positional
            self.record_list_store(owner, value.t, node)
            if not self.emit:
                return Value(VOID, '')
            self.plan.allocates = True
            element = self.hoist(Value(t.elem, self.convert(value, t.elem, node),
                                       self.r.cint(t.elem) if is_int_like(t.elem) else None))
            return Value(VOID, f'P2C_DEQUE_PUSH({owner.code}, {elem_c}, {element.code})')
        if attr == 'popleft':
            if not self.emit:
                return Value(t.elem, 'p2c_popleft')
            result = self.temp(t.elem)
            holder = self.hoist(owner)
            self.line(f'if ({holder.code}->length == 0) p2c_raise(P2C_E_INDEX);')
            self.line(f'{result} = P2C_DEQUE_AT({holder.code}, {elem_c}, 0); p2c_deque_popleft({holder.code});')
            value = Value(t.elem, result)
            if is_int_like(t.elem):
                value.cwidth = self.r.cint(t.elem)
            return value
        if attr == 'clear':
            return Value(VOID, f'p2c_deque_clear({owner.code})')
        raise self.error(f'deque.{attr} не поддержан', node)

    # --- словарь ----------------------------------------------------------------

    def dict_new(self, t: DictT) -> str:
        return (f'p2c_dict_new({self.container_class(t)}, sizeof({self.ctype(t.k)}), '
                f'sizeof({self.ctype(t.v)}), 0)')

    def set_new(self, t: SetT) -> str:
        return f'p2c_dict_new({self.container_class(t)}, sizeof({self.ctype(t.elem)}), 0, 0)'

    def key_code(self, key: Value, key_t: T, node: ast.AST) -> str:
        """Ключ словаря/множества во временной переменной (сравнение по байтам)."""
        if not (is_int_like(key_t) or isinstance(key_t, (StrT, ObjT))):
            raise self.error(f'ключ словаря {describe(key_t)} не поддержан', node)
        holder = self.temp(key_t)
        if is_int_like(key_t):
            self.plan.temps[holder] = ('cint', self.r.cint(key_t))
        self.line(f'{holder} = {self.convert(key, key_t, node)};')
        return holder

    def probe_code(self, key: Value, key_t: T, node: ast.AST) -> tuple[str, str]:
        """Ключ поиска: значение вне C-типа ключей не может присутствовать (условие диапазона)."""
        if is_int_like(key_t) and is_int_like(key.t if not isinstance(key.t, OptT) else key.t.inner):
            probe = self.int_value(key, node)
            interval = self.interval_of(probe) or TOP
            cint = self.r.cint(key_t)
            if not interval.within(cint.minimum, cint.maximum):
                raw = self.hoist(Value(IntT(interval.lo, interval.hi), self.cast(probe, I32, node), I32))
                holder = self.temp(key_t)
                self.plan.temps[holder] = ('cint', cint)
                self.line(f'{holder} = ({cint.c()}){raw.code};')
                return holder, f'({raw.code} >= {cint.minimum}L && {raw.code} <= {cint.maximum}L)'
        return self.key_code(key, key_t, node), '1'

    def dict_lookup(self, owner: Value, key: Value, default: Value | None, node: ast.AST) -> Value:
        t = owner.t
        if isinstance(owner.const, dict) and isinstance(key.const, (int, str)) and default is None:
            if key.const not in owner.const:
                raise self.error(f'ключ {key.const!r} отсутствует в константном словаре', node)
            return self.global_value('dict', owner.const[key.const], node)
        result_t = t.v if default is None else self.c.join(t.v, default.t, node, self.plan.filename)
        if not self.emit:
            if isinstance(key.t, BottomT):
                raise Unknown()
            return Value(result_t, 'p2c_dict_get')
        holder = self.hoist(owner)
        key_holder, guard = self.probe_code(key, t.k, node)
        slot = self.temp(IntT(-1, 65535), 'i')
        self.plan.temps[slot] = ('cint', I32)
        self.line(f'{slot} = {guard} ? p2c_dict_find({holder.code}, &{key_holder}) : -1;')
        value_code = f'P2C_DICT_VALUE({holder.code}, {self.ctype(t.k)}, {self.ctype(t.v)}, {slot})'
        stored = Value(t.v, value_code, self.r.cint(t.v) if is_int_like(t.v) else None)
        result = self.temp(result_t)
        if default is None:
            self.line(f'if ({slot} < 0) p2c_raise(P2C_E_KEY);')
            self.line(f'{result} = {self.convert(stored, result_t, node)};')
        else:
            self.branch_assign(f'{slot} >= 0', result, lambda: self.convert(stored, result_t, node),
                               lambda: self.convert(default, result_t, node))
        value = Value(result_t, result)
        if is_int_like(result_t):
            value.cwidth = self.r.cint(result_t)
        return value

    def dict_contains(self, owner: Value, key: Value, node: ast.AST) -> str:
        if isinstance(owner.const, dict) and isinstance(key.const, (int, str)):
            return '1' if key.const in owner.const else '0'
        if not self.emit:
            return 'p2c_dict_contains'
        holder = self.hoist(owner)
        key_holder, guard = self.probe_code(key, owner.t.k, node)
        return f'({guard} && p2c_dict_find({holder.code}, &{key_holder}) >= 0)'

    def dict_store(self, owner: Value, key: Value, value: Value, node: ast.AST) -> None:
        t = owner.t
        if not self.emit:
            if isinstance(key.t, BottomT) or isinstance(value.t, BottomT):
                return
            new_t = DictT(self.c.join(t.k, key.t, node, self.plan.filename),
                          self.c.join(t.v, value.t, node, self.plan.filename))
            if new_t != t:
                self.refine_path(owner, new_t, node)
            return
        self.plan.allocates = True
        holder = self.hoist(owner)
        key_holder = self.key_code(key, t.k, node)
        value_holder = self.temp(t.v)
        if is_int_like(t.v):
            self.plan.temps[value_holder] = ('cint', self.r.cint(t.v))
        self.line(f'{value_holder} = {self.convert(value, t.v, node)};')
        self.line(f'p2c_dict_set({holder.code}, &{key_holder}, &{value_holder});')

    def dict_method(self, owner: Value, attr: str, node: ast.Call) -> Value:
        t = owner.t
        if attr in ('items', 'values', 'keys'):
            raise self.error(f'dict.{attr}() вне цикла/tuple()/list() не поддержан', node)
        positional, _ = self.arguments(node)
        if attr == 'get':
            key = positional[0]
            default = positional[1] if len(positional) > 1 else Value(NONE, 'NULL', const=None)
            return self.dict_lookup(owner, key, default, node)
        if attr == 'pop':
            self.plan.writes = True
            key = positional[0]
            default = positional[1] if len(positional) > 1 else None
            value = self.dict_lookup(owner, key, default, node)
            if self.emit:
                holder = self.hoist(owner)
                key_holder, guard = self.probe_code(key, t.k, node)
                self.line(f'if ({guard}) p2c_dict_delete({holder.code}, &{key_holder});')
            return value
        if attr == 'clear':
            self.plan.writes = True
            return Value(VOID, f'p2c_dict_clear({owner.code})')
        if attr == 'setdefault':
            raise self.error('dict.setdefault не поддержан', node)
        raise self.error(f'dict.{attr} не поддержан', node)

    # --- множество --------------------------------------------------------------

    def set_add(self, owner: Value, value: Value, node: ast.AST) -> None:
        t = owner.t
        if not self.emit:
            if not isinstance(value.t, BottomT):
                new_t = SetT(self.c.join(t.elem, value.t, node, self.plan.filename))
                if new_t != t:
                    self.refine_path(owner, new_t, node)
            return
        self.plan.allocates = True
        holder = self.hoist(owner)
        key_holder = self.key_code(value, t.elem, node)
        self.line(f'p2c_dict_set({holder.code}, &{key_holder}, NULL);')

    def set_contains(self, owner: Value, value: Value, node: ast.AST) -> str:
        if not self.emit:
            return 'p2c_set_contains'
        holder = self.hoist(owner)
        key_holder, guard = self.probe_code(value, owner.t.elem, node)
        return f'({guard} && p2c_dict_find({holder.code}, &{key_holder}) >= 0)'

    def set_method(self, owner: Value, attr: str, node: ast.Call) -> Value:
        positional, _ = self.arguments(node)
        self.plan.writes = True
        if attr == 'add':
            self.set_add(owner, positional[0], node)
            return Value(VOID, '')
        if attr in ('remove', 'discard'):
            if not self.emit:
                return Value(VOID, '')
            holder = self.hoist(owner)
            key_holder = self.key_code(positional[0], owner.t.elem, node)
            if attr == 'remove':
                self.line(f'if (p2c_dict_find({holder.code}, &{key_holder}) < 0) p2c_raise(P2C_E_KEY);')
            self.line(f'p2c_dict_delete({holder.code}, &{key_holder});')
            return Value(VOID, '')
        if attr == 'clear':
            return Value(VOID, f'p2c_dict_clear({owner.code})')
        raise self.error(f'set.{attr} не поддержан', node)

    def set_operation(self, left: Value, op: str, right: Value, node: ast.AST) -> Value:
        t = left.t
        if not isinstance(right.t, SetT):
            raise self.error('операция множества с не-множеством', node)
        elem = self.c.join(t.elem, right.t.elem, node, self.plan.filename)
        result_t = SetT(elem)
        self.plan.allocates = True
        if not self.emit:
            return Value(result_t, 'p2c_setop')
        a = self.hoist(left)
        b = self.hoist(right)
        result = self.temp(result_t)
        self.line(f'{result} = {self.set_new(result_t)};')
        loop = self.open_value_loop(a, node, 'set')
        key = self.key_code(loop.element, elem, node)
        found = f'(p2c_dict_find({b.code}, &{key}) >= 0)'
        if op == 'Sub':
            self.line(f'if (!{found}) p2c_dict_set({result}, &{key}, NULL);')
        elif op == 'BitAnd':
            self.line(f'if ({found}) p2c_dict_set({result}, &{key}, NULL);')
        else:
            self.line(f'p2c_dict_set({result}, &{key}, NULL);')
        self.close_loop(loop)
        if op == 'BitOr':
            loop = self.open_value_loop(b, node, 'set')
            key = self.key_code(loop.element, elem, node)
            self.line(f'p2c_dict_set({result}, &{key}, NULL);')
            self.close_loop(loop)
        return Value(result_t, result)

    # --- строки и байты ------------------------------------------------------------

    def str_method(self, owner: Value, attr: str, node: ast.Call) -> Value:
        positional, _ = self.arguments(node)
        if attr == 'replace' and len(positional) == 2:
            if isinstance(owner.const, str) and all(isinstance(value.const, str) for value in positional):
                return self.string_constant(owner.const.replace(positional[0].const, positional[1].const))
            self.plan.allocates = True
            return Value(STR, f'p2c_str_replace({owner.code}, {positional[0].code}, {positional[1].code})')
        raise self.error(f'str.{attr} не поддержан', node)

    def bytes_method(self, owner: Value, attr: str, node: ast.Call) -> Value:
        raise self.error(f'bytes.{attr} не поддержан', node)

    # --- цель вывода, шрифт, изображение, Rect ----------------------------------------

    def target_method(self, owner: Value, attr: str, node: ast.Call) -> Value:
        self.plan.writes = True
        if attr == 'blit':
            if len(node.args) != 2 or node.keywords:
                raise self.error('blit(изображение, (x, y))', node)
            position = node.args[1]
            if not isinstance(position, ast.Tuple) or len(position.elts) != 2:
                raise self.error('позиция blit должна быть кортежем (x, y)', node)
            image = self.value_expr(node.args[0])
            mark = self.mark()
            x = self.value_expr(position.elts[0])
            self.fix_left([image], mark)
            mark = self.mark()
            y = self.value_expr(position.elts[1])
            self.fix_left([image, x], mark)
            if not isinstance(image.t, ImageT):
                if isinstance(image.t, BottomT):
                    raise self.unknown(node)
                raise self.error(f'blit ожидает изображение, есть {describe(image.t)}', node)
            x = self.int_value(x, node)
            y = self.int_value(y, node)
            return Value(VOID, f'p2c_blit({image.code}, {self.cast(x, I32, node)}, {self.cast(y, I32, node)})')
        if attr == 'fill':
            if len(node.args) != 1 or node.keywords:
                raise self.error('fill(цвет)', node)
            color = node.args[0]
            if not (isinstance(color, ast.Constant) and color.value == 'black'):
                raise self.error('fill поддержан только для "black"', node)
            return Value(VOID, 'p2c_fill_black()')
        if attr in ('get_width', 'get_height'):
            return Value(IntT(0, 4096), f'p2c_target_{attr}()', I16)
        raise self.error(f'метод цели вывода {attr} не поддержан', node)

    def font_method(self, owner: Value, attr: str, node: ast.Call) -> Value:
        if attr != 'render' or len(node.args) != 3:
            raise self.error(f'метод шрифта {attr} не поддержан', node)
        text = self.value_expr(node.args[0])
        antialias = self.value_expr(node.args[1])
        color = node.args[2]
        if not isinstance(color, ast.Tuple) or not all(isinstance(item, ast.Constant) for item in color.elts):
            raise self.error('цвет текста должен быть константным кортежем', node)
        rgb = [item.value for item in color.elts]
        packed = (rgb[0] << 16) | (rgb[1] << 8) | rgb[2]
        self.plan.writes = True
        if not self.emit:
            return Value(IMAGE, 'p2c_text')
        name = self.temp(IMAGE)
        self.line(f'{name} = p2c_text_image({text.code}, {self.truth(antialias, node)}, {packed}UL);')
        return Value(IMAGE, name)

    def image_method(self, owner: Value, attr: str, node: ast.Call) -> Value:
        if attr in ('get_width', 'get_height') and not node.args:
            return Value(IntT(0, 4096), f'p2c_image_{attr}({owner.code})', I16)
        raise self.error(f'метод изображения {attr} не поддержан', node)

    def rect_method(self, owner: Value, attr: str, node: ast.Call) -> Value:
        if attr == 'colliderect':
            positional, _ = self.arguments(node)
            (other,) = positional
            if not (isinstance(other.t, ValT) and other.t.cls == 'Rect'):
                raise self.error('colliderect ожидает Rect', node)
            return self.bool_value(f'p2c_rect_collide({owner.code}, {other.code})')
        raise self.error(f'Rect.{attr} не поддержан', node)

    # --- модульные функции: struct, pygame -------------------------------------------

    def call_module_attribute(self, module: str, attr: str, node: ast.Call) -> Value:
        full = f'{module}.{attr}'
        if full == 'struct.unpack_from':
            # Результат — кортеж полей формата, прочитанных сразу (как в CPython).
            values = self.unpack_from(node)
            t = TupleT(tuple(value.t for value in values))
            if not self.emit:
                return Value(t, 'p2c_unpack')
            name = self.temp(t)
            for index, value in enumerate(values):
                self.line(f'{name}.v{index} = {value.code};')
            return Value(t, name)
        if full == 'struct.pack_into':
            self.pack_into(node)
            return Value(VOID, '')
        if full == 'pygame.rect.Rect' or full == 'pygame.Rect' or (module == 'pygame' and attr == 'Rect'):
            positional, _ = self.arguments(node)
            if len(positional) != 4:
                raise self.error('pygame.Rect(x, y, w, h)', node)
            t = ValT('Rect')
            if not self.emit:
                return Value(t, 'p2c_rect')
            name = self.temp(t)
            for member, value in zip(('x', 'y', 'w', 'h'), positional):
                self.line(f'{name}.{member} = {self.store_int(I32, self.int_value(value, node), node)};')
            return Value(t, name)
        raise self.error(f'вызов {full} не поддержан', node)

    def struct_format(self, node: ast.AST, format_node: ast.expr) -> list[tuple[str, int]]:
        if not (isinstance(format_node, ast.Constant) and isinstance(format_node.value, str)):
            raise self.error('формат struct должен быть литералом', node)
        text = format_node.value
        if not text.startswith('<'):
            raise self.error('поддержан только явный little-endian формат', node)
        fields = []
        for char in text[1:]:
            kinds = {'H': ('u16', 2), 'h': ('i16', 2), 'B': ('u8', 1), 'b': ('i8', 1)}
            if char not in kinds:
                raise self.error(f'поле формата {char!r} не поддержано', node)
            fields.append(kinds[char])
        if struct_module.calcsize(text) != sum(size for _, size in fields):
            raise self.error('размер формата не совпал с CPython', node)
        return fields

    @staticmethod
    def field_kind_type(kind: str) -> IntT:
        return {'u16': IntT(0, 65535), 'i16': IntT(-32768, 32767), 'u8': IntT(0, 255), 'i8': IntT(-128, 127)}[kind]

    def unpack_from(self, node: ast.Call) -> list[Value]:
        if len(node.args) != 3:
            raise self.error('unpack_from(format, buffer, offset)', node)
        fields = self.struct_format(node, node.args[0])
        buffer = self.value_expr(node.args[1])
        mark = self.mark()
        offset = self.int_value(self.value_expr(node.args[2]), node)
        self.fix_left([buffer], mark)
        if isinstance(buffer.t, BottomT):
            raise self.unknown(node)
        if not isinstance(buffer.t, BytesT):
            raise self.error('unpack_from ожидает bytes/bytearray', node)
        total = sum(size for _, size in fields)
        if not self.emit:
            return [Value(self.field_kind_type(kind), 'p2c_field') for kind, _ in fields]
        base = self.temp(IntT(0, 65535), 'o')
        self.plan.temps[base] = ('cint', I32)
        self.line(f'{base} = p2c_buf_require({buffer.code}, {self.cast(offset, I32, node)}, {total});')
        values = []
        position = 0
        from .ptypes import U8 as C_U8, I8 as C_I8, U16 as C_U16, I16 as C_I16
        widths = {'u16': C_U16, 'i16': C_I16, 'u8': C_U8, 'i8': C_I8}
        for kind, size in fields:
            captured = self.temp(self.field_kind_type(kind))
            self.plan.temps[captured] = ('cint', widths[kind])
            self.line(f'{captured} = P2C_BUF_{kind.upper()}LE({buffer.code}, {base} + {position});')
            values.append(Value(self.field_kind_type(kind), captured, widths[kind]))
            position += size
        return values

    def pack_into(self, node: ast.Call) -> None:
        fields = self.struct_format(node, node.args[0])
        if len(node.args) != 3 + len(fields):
            raise self.error('число значений pack_into не совпадает с форматом', node)
        self.plan.writes = True
        positional = [self.value_expr(item) for item in node.args[1:]]
        buffer, offset, values = positional[0], positional[1], positional[2:]
        if isinstance(buffer.t, BottomT):
            raise self.unknown(node)
        if not isinstance(buffer.t, BytesT) or not buffer.t.mutable:
            raise self.error('pack_into ожидает bytearray', node)
        offset = self.int_value(offset, node)
        values = [self.int_value(value, node) for value in values]
        if not self.emit:
            return
        total = sum(size for _, size in fields)
        codes = []
        for (kind, _), value in zip(fields, values):
            name = self.temp(INT_TOP)
            self.plan.temps[name] = ('cint', I32)
            self.line(f'{name} = {self.cast(value, I32, node)};')
            self.line(f'p2c_require_{kind}({name});')
            codes.append(name)
        base = self.temp(IntT(0, 65535), 'o')
        self.plan.temps[base] = ('cint', I32)
        self.line(f'{base} = p2c_buf_require({buffer.code}, {self.cast(offset, I32, node)}, {total});')
        position = 0
        for (kind, size), code in zip(fields, codes):
            self.line(f'P2C_BUF_SET_{kind.upper()}LE({buffer.code}, {base} + {position}, {code});')
            position += size

    def int_from_bytes(self, node: ast.Call) -> Value:
        raise self.error('int.from_bytes не поддержан', node)
