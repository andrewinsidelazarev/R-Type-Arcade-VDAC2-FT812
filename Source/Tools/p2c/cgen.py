"""Сборка C-модуля: типы, раскладка, данные снимка, функции, диспетчеры, разметка сборщика."""
from __future__ import annotations

import dataclasses

from .compiler import Compiler, Plan, int_empty
from .crepr import CRepr
from .emitter import FunctionEmitter
from .errors import TranslationError
from .fn_base import cname
from .layout import Layout
from .ptypes import (
    ArrayT, BoolT, BottomT, BytesT, CInt, DequeT, DictT, ExtT, FnT, FontT, I32, ImageT, IntT, ListT,
    NoneT, ObjT, OptT, SetT, StrT, T, TargetT, TupleT, ValT, VoidT, has_references, is_int_like,
    is_pointer,
)
from .snapshot import DataEmitter


class CModule:
    def __init__(self, compiler: Compiler, image_id, roots: dict[str, object], entries: list[tuple]) -> None:
        self.c = compiler
        self.p = compiler.program
        self.r = CRepr(compiler)
        self.layout = Layout(compiler, self.r)
        compiler.layout = self.layout
        self.image_id = image_id
        self.roots = roots
        self.entries = entries
        self.value_structs: list[str] = []

    # --- генерация функций ---------------------------------------------------------

    def emit_functions(self) -> None:
        for plan in list(self.c.queue):
            if plan.kind == 'value_init':
                continue
            FunctionEmitter(self.c, plan, True, self.r).run()

    def resolved(self, value: T, declared: T | None) -> T:
        if isinstance(value, BottomT) and declared is not None:
            value = declared
        if isinstance(value, IntT) and int_empty(value):
            value = IntT(-(1 << 31), (1 << 31) - 1)
        return value

    def return_ctype(self, plan: Plan) -> str:
        ret = plan.ret if not isinstance(plan.ret, BottomT) else plan.ret_declared
        if isinstance(plan.ret_declared, VoidT) or ret is None or isinstance(ret, (VoidT, NoneT, BottomT)):
            return 'void'
        return self.r.ctype(self.resolved(ret, None))

    def signature(self, plan: Plan) -> str:
        parts = []
        if plan.kind in ('nested', 'lambda') and plan.captures:
            if self.layout.env_is_direct(plan):
                parts.append(f'{self.r.ctype(plan.captures[0].t)} p2c_direct')
            else:
                self.layout.env_symbol(plan)
                parts.append(f'P2cE_{plan.c_name} *p2c_env')
        for param in plan.params:
            t = self.resolved(param.t, param.declared)
            if isinstance(t, BottomT):
                raise TranslationError(f'{plan.c_name}: форма параметра {param.name} не выведена')
            parts.append(f'{self.r.ctype(t)} {cname(param.name)}')
        return f'{self.return_ctype(plan)} {plan.c_name}({", ".join(parts) or "void"})'

    def local_declarations(self, plan: Plan) -> list[str]:
        lines = []
        params = {param.name for param in plan.params}
        for key, t in sorted(plan.locals.items()):
            if key in params or key.startswith(('p2c_collect', 'p2c_reduce', 'p2c_sortkey')):
                continue
            t = self.resolved(t, None)
            if isinstance(t, BottomT):
                continue
            name = cname(key) if not key.startswith('p2c_') else key
            lines.append(f'    {self.r.ctype(t)} {name};')
        for name, t in plan.temps.items():
            lines.append('    ' + self.temp_declaration(name, t) + ';')
        return lines

    def temp_declaration(self, name: str, t) -> str:
        if isinstance(t, tuple):
            kind = t[0]
            if kind == 'cint':
                return f'{t[1].c()} {name}'
            if kind == 'carray':
                return f'{self.r.ctype(t[1])} {name}[{t[2]}]'
            if kind == 'keys':
                return f'{self.r.ctype(t[1])} *{name}'
            if kind == 'env':
                return f'P2cE_{t[1]} {name}'
            if kind == 'envptr':
                return f'P2cE_{t[1]} *{name}'
            raise TranslationError(f'временная {name}: {t}')
        t = self.resolved(t, None)
        return f'{self.r.ctype(t)} {name}'

    def function_comment(self, plan: Plan) -> str:
        """Комментарий перед функцией: что переведено и откуда (вид, имя Python, файл:строка)."""
        kinds = {'function': 'Функция', 'method': 'Метод', 'property': 'Свойство', 'staticmethod': 'Статический метод',
                 'classmethod': 'Метод класса', 'lambda': 'Лямбда', 'nested': 'Вложенная функция'}
        title = kinds.get(plan.kind, plan.kind)
        name = f'{plan.owner}.{plan.name}' if plan.owner else f'{plan.module}.{plan.name}'
        where = plan.filename.replace(chr(92), '/').rsplit('/', 1)[-1]
        line = getattr(plan.node, 'lineno', 0)
        return f'/* {title} {name} — {where}:{line}. */'

    def function_definition(self, plan: Plan) -> list[str]:
        lines = [f'{self.signature(plan)} {{']
        lines.extend(self.local_declarations(plan))
        lines.extend('    ' + line for line in plan.tables)
        lines.extend(plan.lines)
        lines.append('}')
        return lines

    # --- типы ----------------------------------------------------------------------

    def collect_value_types(self) -> None:
        """Регистрация производных типов всех ячеек до вывода объявлений."""
        for cell in self.c.fields.values():
            if cell.used and not isinstance(cell.t, BottomT):
                self.r.ctype(cell.t)
        for plan in self.c.queue:
            for param in plan.params:
                t = self.resolved(param.t, param.declared)
                if not isinstance(t, BottomT):
                    self.r.ctype(t)
            for t in plan.locals.values():
                if not isinstance(t, BottomT):
                    self.r.ctype(self.resolved(t, None))

    def value_struct_definitions(self) -> list[str]:
        """Структуры кортежей, Optional и неизменяемых dataclass в порядке зависимостей."""
        emitted: set[str] = set()
        lines: list[str] = []
        frozen = sorted(name for name, info in self.p.classes.items() if info.frozen and self.value_class_used(name))

        def ensure(t: T) -> None:
            if isinstance(t, TupleT):
                name = self.r.tuple_name(t)
                if name in emitted:
                    return
                for item in self.r.normalized(t).items:
                    ensure(item)
                emitted.add(name)
                members = ' '.join(f'{self.r.ctype(item)} v{index};'
                                   for index, item in enumerate(self.r.normalized(t).items))
                lines.append(f'typedef struct {{ {members or "uint8_t unused;"} }} {name};')
            elif isinstance(t, OptT) and not (is_pointer(t.inner) or isinstance(t.inner, FnT)):
                name = self.r.opt_name(t)
                if name in emitted:
                    return
                ensure(t.inner)
                emitted.add(name)
                inner_c = self.r.ctype(self.r.normalized(t).inner)
                lines.append(f'typedef struct {{ uint8_t has; {inner_c} v; }} {name};')
            elif isinstance(t, ValT) and t.cls != 'Rect':
                name = f'P2cV_{t.cls}'
                if name in emitted:
                    return
                info = self.p.classes[t.cls]
                members = []
                for item in dataclasses.fields(info.python):
                    field_t = self.c.field_type(t.cls, item.name)
                    if isinstance(field_t, BottomT):
                        continue
                    ensure(field_t)
                    members.append(f'{self.r.ctype(field_t)} {cname(item.name)};')
                emitted.add(name)
                lines.append(f'typedef struct {{ {" ".join(members) or "uint8_t unused;"} }} {name};')
            elif isinstance(t, (ListT, ArrayT, DequeT, SetT)):
                ensure(t.elem)
            elif isinstance(t, DictT):
                ensure(t.k)
                ensure(t.v)

        for name in frozen:
            ensure(ValT(name))
        for _, t in list(self.r.order):
            ensure(t)
        for cell in self.c.fields.values():
            if cell.used and not isinstance(cell.t, BottomT):
                ensure(cell.t)
        for plan in self.c.queue:
            for param in plan.params:
                t = self.resolved(param.t, param.declared)
                if not isinstance(t, BottomT):
                    ensure(t)
            for t in list(plan.locals.values()) + [item for item in plan.temps.values() if isinstance(item, T)]:
                t = self.resolved(t, None)
                if not isinstance(t, BottomT):
                    ensure(t)
            ret = plan.ret if not isinstance(plan.ret, BottomT) else plan.ret_declared
            if ret is not None and not isinstance(ret, BottomT):
                ensure(ret)
        for dispatcher in self.layout.dispatchers.values():
            for item in dispatcher.params:
                ensure(item)
            ensure(dispatcher.ret)
        for _, t in list(self.r.order):
            ensure(t)
        return lines

    def value_class_used(self, name: str) -> bool:
        return any(cell.root == self.p.root(name) and cell.used for cell in self.c.fields.values())

    def root_struct_definitions(self) -> list[str]:
        """Структуры корневых классов: слот sN хранит атрибуты классов иерархии одного C-типа (у разных подклассов слот
        может означать разные атрибуты) — перед структурой комментарий «слот: атрибуты»."""
        lines = []
        for root, layout in sorted(self.layout.roots.items()):
            members = []
            if layout.list_based:
                members.append('P2cList list;')
            else:
                members.append('uint8_t cls; uint8_t gc;')
            if layout.presence_bits:
                members.append('uint16_t presence;')
            for index, ctype in enumerate(layout.slots):
                members.append(f'{ctype} s{index};')
            meaning = {}
            for attr, slot in sorted(layout.attribute_slot.items()):
                meaning.setdefault(slot, []).append(attr)
            if meaning:
                slots = '; '.join(f's{slot} — {", ".join(names)}' for slot, names in sorted(meaning.items()))
                lines.append(f'/* Класс {root}: {slots}. */')
            lines.append(f'struct P2cC_{root} {{ ' + ' '.join(members) + ' };')
        return lines

    def size_macros(self) -> list[str]:
        lines = []
        for name in sorted(self.c.instantiated):
            root = self.p.root(name)
            layout = self.layout.roots.get(root)
            slots = sorted(layout.class_slots.get(name, set())) if layout else []
            if slots:
                last = slots[-1]
                lines.append(f'#define P2C_SIZE_{name} (offsetof(P2cC_{root}, s{last}) + '
                             f'sizeof(((P2cC_{root} *)0)->s{last}))')
            else:
                lines.append(f'#define P2C_SIZE_{name} sizeof(P2cC_{root})')
        return lines

    def env_definitions(self) -> list[str]:
        lines = []
        for plan in self.c.queue:
            if plan.kind not in ('nested', 'lambda') or not plan.captures or self.layout.env_is_direct(plan):
                continue
            self.layout.env_symbol(plan)
            members = ['uint8_t cls; uint8_t gc;']
            for capture in plan.captures:
                t = self.resolved(capture.t, None)
                pointer = ' *' if capture.by_pointer else ' '
                members.append(f'{self.r.ctype(t)}{pointer}{cname(capture.name)};')
            lines.append(f'typedef struct {{ {" ".join(members)} }} P2cE_{plan.c_name};')
        return lines

    def list_items_type(self, class_name: str) -> T:
        """Форма элементов класса-наследника list: потоки или аннотация базы."""
        from .annotations import parse_annotation
        cell = self.c.field_cell(class_name, '<items>')
        if not isinstance(cell.t, BottomT):
            return cell.t
        info = self.p.classes[class_name]
        return parse_annotation(self.c, self.p.list_base_of(class_name), info.module, info.filename)

    # --- разметка сборщика -------------------------------------------------------------

    def mark_statements(self, t: T, expr: str, depth: int = 0) -> list[str]:
        if not has_references(t) and not isinstance(t, ValT):
            return []
        if is_pointer(t):
            return [f'p2c_mark((P2cObject *){expr});']
        if isinstance(t, OptT):
            if is_pointer(t.inner):
                return [f'p2c_mark((P2cObject *){expr});']
            if isinstance(t.inner, FnT):
                return [f'p2c_mark((P2cObject *)({expr}).env);']
            inner = self.mark_statements(t.inner, f'({expr}).v', depth + 1)
            return [f'if (({expr}).has) {{ ' + ' '.join(inner) + ' }'] if inner else []
        if isinstance(t, FnT):
            return [f'p2c_mark((P2cObject *)({expr}).env);']
        if isinstance(t, TupleT):
            result = []
            for index, item in enumerate(t.items):
                result.extend(self.mark_statements(item, f'({expr}).v{index}', depth + 1))
            return result
        if isinstance(t, ValT) and t.cls != 'Rect':
            result = []
            for item in dataclasses.fields(self.p.classes[t.cls].python):
                field_t = self.c.field_type(t.cls, item.name)
                if not isinstance(field_t, BottomT):
                    result.extend(self.mark_statements(field_t, f'({expr}).{cname(item.name)}', depth + 1))
            return result
        return []

    def mark_function(self) -> list[str]:
        lines = ['void p2c_mark_children(P2cObject *object) {', '    uint16_t i;', '    (void)i;',
                 '    switch (object->cls) {']
        for _number, case_lines in self.mark_cases():
            lines.extend(case_lines)
        lines.append('    default: break;')
        lines.append('    }')
        lines.append('}')
        return lines

    def mark_cases(self) -> list[tuple[int, list[str]]]:
        """Ветви разметки детей по номеру класса: (номер, строки case … break)."""
        cases: list[tuple[int, list[str]]] = []
        lines: list[str] = []
        for name in sorted(self.c.instantiated, key=lambda item: self.layout.class_ids[item]):
            lines = []
            root = self.p.root(name)
            layout = self.layout.roots.get(root)
            statements = []
            if layout is not None:
                for attr, slot in sorted(layout.attribute_slot.items(), key=lambda item: item[1]):
                    if slot not in layout.class_slots.get(name, set()):
                        continue
                    field_t = self.c.field_type(name, attr)
                    statements.extend(self.mark_statements(field_t, f'((P2cC_{root} *)object)->s{slot}'))
                if layout.list_based:
                    elem = self.list_items_type(name)
                    statements.append('p2c_mark_block(((P2cList *)object)->data);')
                    inner = self.mark_statements(elem, f'P2C_AT((P2cList *)object, {self.r.ctype(elem)}, i)')
                    if inner:
                        statements.append('for (i = 0; i < ((P2cList *)object)->length; i++) { ' +
                                          ' '.join(inner) + ' }')
            lines.append(f'    case {self.layout.class_id_symbol(name)}:')
            for statement in statements:
                lines.append(f'        {statement}')
            lines.append('        break;')
            cases.append((self.layout.class_ids[name], lines))

        def element_marks(signature, accessor) -> list[str]:
            if signature == 'raw':
                return []
            if signature == 'ptr':
                return [f'p2c_mark((P2cObject *){accessor("void *")});']
            return self.mark_statements(signature, accessor(self.r.ctype(signature)))

        for key, (number, symbol, _key) in sorted(self.layout.container_classes.items(), key=lambda item: item[1][0]):
            lines = [f'    case {symbol}:']
            kind = key[0]
            if kind == 'list':
                lines.append('        p2c_mark_block(((P2cList *)object)->data);')
                inner = element_marks(key[1], lambda ctype: f'P2C_AT((P2cList *)object, {ctype}, i)')
                if inner:
                    lines.append('        for (i = 0; i < ((P2cList *)object)->length; i++) { ' +
                                 ' '.join(inner) + ' }')
            elif kind == 'deque':
                lines.append('        p2c_mark_block(((P2cDeque *)object)->data);')
                inner = element_marks(key[1], lambda ctype: f'P2C_DEQUE_AT((P2cDeque *)object, {ctype}, i)')
                if inner:
                    lines.append('        for (i = 0; i < ((P2cDeque *)object)->length; i++) { ' +
                                 ' '.join(inner) + ' }')
            else:
                lines.append('        p2c_mark_block(((P2cDict *)object)->live);')
                lines.append('        p2c_mark_block(((P2cDict *)object)->keys);')
                lines.append('        p2c_mark_block(((P2cDict *)object)->values);')
                inner = element_marks(key[1], lambda ctype: f'P2C_DICT_KEY((P2cDict *)object, {ctype}, i)')
                inner += element_marks(key[2], lambda ctype: f'P2C_DICT_VALUE((P2cDict *)object, int, {ctype}, i)')
                if inner:
                    lines.append('        for (i = 0; i < ((P2cDict *)object)->used; i++) '
                                 'if (P2C_DICT_LIVE((P2cDict *)object, i)) { ' + ' '.join(inner) + ' }')
            lines.append('        break;')
            cases.append((number, lines))
        for plan in self.c.queue:
            if plan.c_name in self.layout.env_classes:
                lines = [f'    case P2C_CLS_E_{plan.c_name}:']
                for capture in plan.captures:
                    if not capture.by_pointer:
                        for statement in self.mark_statements(self.resolved(capture.t, None),
                                                              f'((P2cE_{plan.c_name} *)object)->{cname(capture.name)}'):
                            lines.append(f'        {statement}')
                lines.append('        break;')
                cases.append((self.layout.env_classes[plan.c_name], lines))
        cases.append((253, ['    case P2C_CLS_BUF: p2c_mark_block(((P2cBuf *)object)->data); break;']))
        return cases

    # --- диспетчеры и множества ------------------------------------------------------------

    def convert_code(self, source: T, target: T, code: str) -> str:
        if is_int_like(target) and is_int_like(source):
            target_c = self.r.cint(target)
            source_c = self.r.cint(source)
            if source_c == target_c:
                return code
            if source_c.minimum >= target_c.minimum and source_c.maximum <= target_c.maximum:
                return f'(({target_c.c()}){code})'
            return f'P2C_TO_{target_c.key().upper()}({code})'
        if isinstance(target, ObjT) and isinstance(source, ObjT):
            return f'(({self.r.ctype(target)}){code})'
        return code

    def dispatcher_definitions(self) -> tuple[list[str], list[str]]:
        prototypes = []
        lines = []
        for dispatcher in self.layout.dispatchers.values():
            prototype, body = self.dispatcher_code(dispatcher)
            prototypes.append(prototype)
            lines.extend(body)
        return prototypes, lines

    def dispatcher_code(self, dispatcher) -> tuple[str, list[str]]:
        """Прототип и тело диспетчера вызываемых значений одного набора номеров."""
        params = ', '.join(['P2cFn f'] + [f'{self.r.ctype(item)} a{index}'
                                           for index, item in enumerate(dispatcher.params)])
        ret_c = 'void' if isinstance(dispatcher.ret, VoidT) else self.r.ctype(dispatcher.ret)
        prototype = f'static {ret_c} {dispatcher.c_name}({params});'
        lines = [f'static {ret_c} {dispatcher.c_name}({params}) {{']
        if not isinstance(dispatcher.ret, VoidT):
            lines.append(f'    {ret_c} r;')
            lines.append('    memset(&r, 0, sizeof r);')
        lines.append('    switch (f.id) {')
        for number in dispatcher.ids:
            key, plan = self.c.fn_targets[number]
            arguments = []
            if plan is None:
                extern = self.c.extern_by_key(key)
                for index, (param_t, arg_t) in enumerate(zip(extern.params, dispatcher.params)):
                    arguments.append(self.convert_code(arg_t, self.resolved(param_t, None), f'a{index}'))
                call = f'{extern.c_name}({", ".join(arguments)})'
                target_ret = extern.ret
            else:
                if key[0] == 'bound':
                    self_t = self.resolved(plan.params[0].t, plan.params[0].declared)
                    arguments.append(f'({self.r.ctype(self_t)})f.env')
                    plan_params = plan.params[1:]
                else:
                    plan_params = plan.params
                    if plan.kind in ('nested', 'lambda') and plan.captures:
                        if self.layout.env_is_direct(plan):
                            arguments.append(f'({self.r.ctype(plan.captures[0].t)})f.env')
                        else:
                            arguments.append(f'(P2cE_{plan.c_name} *)f.env')
                for index, (param, arg_t) in enumerate(zip(plan_params, dispatcher.params)):
                    arguments.append(self.convert_code(arg_t, self.resolved(param.t, param.declared), f'a{index}'))
                call = f'{plan.c_name}({", ".join(arguments)})'
                target_ret = plan.ret if not isinstance(plan.ret, BottomT) else plan.ret_declared
            if isinstance(dispatcher.ret, VoidT):
                lines.append(f'    case {self.layout.fn_id_symbol(number)}: {call}; return;')
            else:
                lines.append(f'    case {self.layout.fn_id_symbol(number)}: r = '
                             f'{self.convert_code(self.resolved(target_ret, None), dispatcher.ret, call)}; return r;')
        lines.append('    default: p2c_raise(P2C_E_DISPATCH);')
        lines.append('    }')
        if not isinstance(dispatcher.ret, VoidT):
            lines.append('    return r;')
        lines.append('}')
        return prototype, lines

    def membership_definitions(self) -> list[str]:
        lines = []
        for values, name in self.layout.memberships.items():
            lines.extend(self.membership_code(values, name))
        return lines

    @staticmethod
    def membership_code(values, name: str) -> list[str]:
        lines = [f'static uint8_t {name}(int32_t v) {{', '    switch (v) {']
        for value in values:
            lines.append(f'    case {value}L:')
        lines.extend(['        return 1;', '    default:', '        return 0;', '    }', '}'])
        return lines

    # --- модуль ----------------------------------------------------------------------

    def build(self) -> str:
        self.emit_functions()
        # Повторная генерация: диспетчеры и контейнерные классы регистрируются во время первой.
        self.collect_value_types()
        data = DataEmitter(self.c, self.r, self.layout, self.image_id)
        root_symbols = {name: data.object_symbol(value, name) for name, value in self.roots.items()}
        constant_lines = data.constants()
        string_lines = data.strings()
        value_structs = self.value_struct_definitions()
        dispatcher_prototypes, dispatcher_lines = self.dispatcher_definitions()
        for plan in self.c.queue:
            if plan.kind in ('nested', 'lambda') and plan.captures and not self.layout.env_is_direct(plan):
                self.layout.env_symbol(plan)
        out = ['/* Сгенерировано транслятором p2c из rtype_port. Не править вручную. */',
               '#include "p2c_runtime.h"', '']
        for name, number in sorted(self.layout.class_ids.items(), key=lambda item: item[1]):
            out.append(f'#define P2C_CLS_{name} {number}')
        for key, (number, symbol, _t) in sorted(self.layout.container_classes.items(), key=lambda item: item[1][0]):
            out.append(f'#define {symbol} {number}')
        for name, number in sorted(self.layout.env_classes.items(), key=lambda item: item[1]):
            out.append(f'#define P2C_CLS_E_{name} {number}')
        for number in sorted(self.c.fn_targets):
            out.append(f'#define P2C_FN_{number} {number}')
        out.append('')
        for root in sorted(self.layout.roots):
            out.append(f'typedef struct P2cC_{root} P2cC_{root};')
        out.extend(value_structs)
        out.extend(self.root_struct_definitions())
        out.extend(self.env_definitions())
        out.extend(self.size_macros())
        out.append('')
        out.extend(string_lines)
        out.extend(data.declarations)
        for plan in self.c.queue:
            if plan.kind != 'value_init':
                out.append(f'static {self.signature(plan)};')
        out.extend(dispatcher_prototypes)
        out.extend(self.membership_definitions())
        out.extend(data.definitions)
        out.extend(constant_lines)
        out.append('')
        for plan in self.c.queue:
            if plan.kind != 'value_init':
                out.append(self.function_comment(plan))
                out.extend('static ' + line if index == 0 else line
                           for index, line in enumerate(self.function_definition(plan)))
                out.append('')
        out.extend(dispatcher_lines)
        out.extend(self.mark_function())
        out.extend(data.static_objects())
        out.append('P2cObject *const p2c_roots[] = {')
        for name, symbol in root_symbols.items():
            out.append(f'    (P2cObject *)&{symbol},')
        out.append('};')
        out.append(f'const uint16_t p2c_root_count = {len(root_symbols)};')
        for entry in self.entries:
            out.extend(self.entry_wrapper(entry, root_symbols))
        out.extend(self.field_table())
        messages = ', '.join(f'"{message.replace(chr(92), "/").replace(chr(34), chr(39))}"'
                             for message in self.c.raise_messages) or '""'
        out.append(f'const char *const p2c_raise_messages[] = {{ "", {messages} }};')
        places = ', '.join(f'"{where}"' for where, _ in sorted(self.c.line_numbers.items(), key=lambda item: item[1]))
        out.append(f'const char *const p2c_line_names[] = {{ "", {places or chr(34) * 2} }};')
        self.data = data
        return '\n'.join(out) + '\n'

    # --- таблица полей для сверки состояния на ПК --------------------------------------

    def descriptor(self, t: T) -> str:
        """Описание представления значения для чтения памяти C из Python."""
        if isinstance(t, BoolT):
            return 'b'
        if isinstance(t, IntT):
            return self.r.cint(self.resolved(t, None)).key()
        if isinstance(t, StrT):
            return 's'
        if isinstance(t, ObjT):
            return 'o'
        if isinstance(t, ValT):
            return 'R' if t.cls == 'Rect' else f'V:P2cV_{t.cls}'
        if isinstance(t, TupleT):
            return f'T:{self.r.tuple_name(t)}'
        if isinstance(t, (ListT, ArrayT)):
            return f'L{{{self.descriptor(t.elem)}}}{self.elem_size_name(t.elem)}'
        if isinstance(t, DequeT):
            return f'Q{{{self.descriptor(t.elem)}}}{self.elem_size_name(t.elem)}'
        if isinstance(t, SetT):
            return f'S{{{self.descriptor(t.elem)}}}'
        if isinstance(t, DictT):
            return f'D{{{self.descriptor(t.k)}}}{{{self.descriptor(t.v)}}}'
        if isinstance(t, BytesT):
            return 'B'
        if isinstance(t, OptT):
            if is_pointer(t.inner) or isinstance(t.inner, FnT):
                return self.descriptor(t.inner)
            return f'N:{self.r.opt_name(t)}'
        if isinstance(t, FnT):
            return 'F'
        if isinstance(t, ImageT):
            return 'I'
        if isinstance(t, NoneT):
            return 'z'
        return 'H'

    def elem_size_name(self, t: T) -> str:
        return ''

    def field_table(self) -> list[str]:
        rows = []

        def row(owner: str, name: str, offset: str, size: str, desc: str) -> None:
            rows.append(f'    {{"{owner}", "{name}", (uint32_t)({offset}), (uint32_t)({size}), "{desc}"}},')

        for class_name in sorted(self.c.instantiated):
            root = self.p.root(class_name)
            layout = self.layout.roots.get(root)
            if layout is None:
                continue
            for attr, slot in sorted(layout.attribute_slot.items(), key=lambda item: item[1]):
                if slot not in layout.class_slots.get(class_name, set()):
                    continue
                field_t = self.c.field_type(class_name, attr)
                row(class_name, attr, f'offsetof(P2cC_{root}, s{slot})', f'sizeof(((P2cC_{root} *)0)->s{slot})',
                    self.descriptor(field_t))
        for name, t in list(self.r.order):
            if isinstance(t, TupleT):
                for index, item in enumerate(t.items):
                    row(name, f'v{index}', f'offsetof({name}, v{index})', f'sizeof((({name} *)0)->v{index})',
                        self.descriptor(item))
                row(name, '', '0', f'sizeof({name})', '')
            elif isinstance(t, OptT):
                row(name, 'has', f'offsetof({name}, has)', '1', 'b')
                row(name, 'v', f'offsetof({name}, v)', f'sizeof((({name} *)0)->v)', self.descriptor(t.inner))
                row(name, '', '0', f'sizeof({name})', '')
        for class_name, info in sorted(self.p.classes.items()):
            if not info.frozen or not self.value_class_used(class_name):
                continue
            struct = f'P2cV_{class_name}'
            for item in dataclasses.fields(info.python):
                field_t = self.c.field_type(class_name, item.name)
                if isinstance(field_t, BottomT):
                    continue
                row(struct, item.name, f'offsetof({struct}, {cname(item.name)})',
                    f'sizeof((({struct} *)0)->{cname(item.name)})', self.descriptor(field_t))
            row(struct, '', '0', f'sizeof({struct})', '')
        runtime = {
            'P2cObject': ['cls', 'gc'],
            'P2cList': ['length', 'capacity', 'data'],
            'P2cDeque': ['length', 'capacity', 'head', 'data'],
            'P2cDict': ['length', 'used', 'capacity', 'key_size', 'value_size', 'live', 'keys', 'values'],
            'P2cBuf': ['length', 'capacity', 'data', 'page'],
            'P2cStr': ['length', 'data'],
            'P2cFn': ['id', 'env'],
            'P2cRect': ['x', 'y', 'w', 'h'],
        }
        for struct, members in runtime.items():
            for member in members:
                row(struct, member, f'offsetof({struct}, {member})', f'sizeof((({struct} *)0)->{member})', '')
            row(struct, '', '0', f'sizeof({struct})', '')
        lines = ['typedef struct { const char *owner; const char *name; uint32_t offset; uint32_t size; '
                 'const char *desc; } P2cFieldInfo;',
                 'P2C_EXPORT const P2cFieldInfo p2c_field_table[] = {']
        lines.extend(rows or ['    {"", "", 0, 0, ""},'])
        lines.append('};')
        lines.append(f'P2C_EXPORT const uint32_t p2c_field_table_count = {len(rows)};')
        names = ['""'] * 256
        for class_name, number in self.layout.class_ids.items():
            names[number] = f'"{class_name}"'
        lines.append('P2C_EXPORT const char *const p2c_class_names[256] = { ' + ', '.join(names) + ' };')
        lines.append('P2C_EXPORT void *p2c_root_pointer(int32_t index) { return (void *)p2c_roots[index]; }')
        return lines

    def input_converter(self, value_class: str) -> list[str]:
        """Значение-аргумент входа из битов: поля bool dataclass по порядку объявления."""
        info = self.p.classes[value_class]
        lines = [f'static P2cV_{value_class} p2c_input_{value_class}(int32_t bits) {{',
                 f'    P2cV_{value_class} r;', '    memset(&r, 0, sizeof r);']
        for index, item in enumerate(dataclasses.fields(info.python)):
            field_t = self.c.field_type(value_class, item.name)
            if not isinstance(field_t, BoolT):
                raise TranslationError(f'{value_class}.{item.name}: вход поддержан только для bool')
            lines.append(f'    r.{cname(item.name)} = (uint8_t)((bits >> {index}) & 1);')
        lines.append('    return r;')
        lines.append('}')
        return lines

    def entry_wrapper(self, entry: tuple, root_symbols: dict[str, str]) -> list[str]:
        """Экспортируемая точка входа: метод объекта-корня с целыми аргументами."""
        export_name, root_name, class_name, method, arguments = entry
        found = self.p.find_method(class_name, method)
        plan = self.c.plans[('method', found[0].name, method)]
        prelude = []
        for spec in arguments:
            if isinstance(spec, tuple) and spec[0] == 'value':
                prelude.extend(self.input_converter(spec[1]))
        params = []
        call = [f'(P2cC_{self.p.root(class_name)} *)&{root_symbols[root_name]}']
        for index, (param, spec) in enumerate(zip(plan.params[1:], arguments)):
            t = self.resolved(param.t, param.declared)
            if spec == 'int':
                params.append(f'int32_t a{index}')
                call.append(self.convert_code(IntT(-(1 << 31), (1 << 31) - 1), t, f'a{index}'))
            elif spec == 'bool':
                params.append(f'int32_t a{index}')
                call.append(f'(uint8_t)(a{index} != 0)')
            elif spec == 'target':
                call.append('0')
            elif isinstance(spec, tuple) and spec[0] == 'value':
                params.append(f'int32_t a{index}')
                value_class = spec[1]
                call.append(f'p2c_input_{value_class}(a{index})')
            else:
                raise TranslationError(f'аргумент входа {spec}')
        return prelude + [f'P2C_EXPORT void {export_name}({", ".join(params) or "void"}) {{',
                          f'    if (setjmp(p2c_fault_jump)) return;',
                          f'    {plan.c_name}({", ".join(call)});',
                          '}']
