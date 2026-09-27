"""C-модуль для Z80 (SDCC): общий заголовок, банки кода и межбанковые обёртки.

Функции программы раскладываются по банкам — страницам окна #C000, номер банка
равен номеру страницы (сегмент BANK<страница>). Внутри банка вызовы ближние;
функция, которую вызывают из другого банка или из резидента, получает обёртку
`имя__b` с __banked, и вызовы из других банков переименовываются на неё.
Диспетчеры вызываемых значений и функции принадлежности копируются в каждый
банк, где используются. Данные начального состояния — внешние символы,
адреса которых задаёт образ памяти (z80data).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .cgen import CModule
from .errors import TranslationError
from .fn_base import cname
from .ptypes import (
    ArrayT, BottomT, BytesT, DictT, IntT, ListT, SetT, TupleT, ValT, VoidT, is_int_like,
)

CALL_RE = re.compile(r'\b([A-Za-z_]\w*)\s*\(')
BANK_LIMIT = 14000


@dataclass
class Unit:
    name: str
    lines: list[str]
    size: int
    prototype: str = ''
    plan: object = None
    callees: set[str] = field(default_factory=set)
    extern_prototype: str = ''
    home_plan: str = ''


@dataclass
class Bank:
    page: int
    units: list[Unit] = field(default_factory=list)
    size: int = 0


def listing_sizes(listing_text: str, total: int | None = None) -> dict[str, int]:
    """Размеры функций по листингу SDCC (адреса меток; последняя — до конца области)."""
    labels = []
    for match in re.finditer(r'^\s+([0-9A-F]{8})\s+\d+\s+_([A-Za-z_]\w*)::?\s*$', listing_text, re.M):
        labels.append((int(match[1], 16), match[2]))
    labels.sort()
    sizes = {}
    for (address, name), (following, _) in zip(labels, labels[1:]):
        sizes[name] = following - address
    if labels and total is not None:
        sizes[labels[-1][1]] = total - labels[-1][0]
    return sizes


class Z80Module:
    def __init__(self, module: CModule, image, entries: list[tuple], bank_pages: list[int],
                 sizes: dict[str, int] | None = None, bank_limit: int = BANK_LIMIT,
                 previous: dict[str, int] | None = None) -> None:
        self.m = module
        self.c = module.c
        self.p = module.p
        self.r = module.r
        self.layout = module.layout
        self.image = image
        self.entries = entries
        self.bank_pages = list(bank_pages)
        self.sizes = sizes or {}
        self.bank_limit = bank_limit
        self.banks: list[Bank] = []
        self.home: dict[str, Bank] = {}
        # Раскладка прошлой сборки (единица -> номер банка по порядку): при том же наборе единиц
        # и без переполнения она сохраняется, и неизменённые банки не пересобираются.
        self.previous = previous or {}

    # --- заголовок --------------------------------------------------------------------

    def header(self, value_structs: list[str]) -> str:
        out = ['/* Сгенерировано транслятором p2c из rtype_port для Z80. Не править вручную. */',
               '#ifndef P2C_Z80_PROGRAM_H', '#define P2C_Z80_PROGRAM_H', '#include "p2c_runtime.h"',
               *self.c.native_prototypes, '']
        for name, number in sorted(self.layout.class_ids.items(), key=lambda item: item[1]):
            out.append(f'#define P2C_CLS_{name} {number}')
        for _key, (number, symbol, _t) in sorted(self.layout.container_classes.items(), key=lambda item: item[1][0]):
            out.append(f'#define {symbol} {number}')
        for name, number in sorted(self.layout.env_classes.items(), key=lambda item: item[1]):
            out.append(f'#define P2C_CLS_E_{name} {number}')
        for number in sorted(self.c.fn_targets):
            out.append(f'#define P2C_FN_{number} {number}')
        out.append('')
        for root in sorted(self.layout.roots):
            out.append(f'typedef struct P2cC_{root} P2cC_{root};')
        out.extend(value_structs)
        out.extend(self.m.root_struct_definitions())
        out.extend(self.m.env_definitions())
        out.extend(self.m.size_macros())
        out.append('')
        for _text, number in sorted(self.c.strings.items(), key=lambda item: item[1]):
            out.append(f'extern const P2cStr p2c_str_{number};')
        from .snapshot import DataEmitter
        initializers = DataEmitter(self.c, self.r, self.layout, lambda surface: 0)
        for number, symbol in sorted(self.layout.constant_symbols.items(), key=lambda item: item[1]):
            value, t = self.c.constants[number]
            if is_int_like(t):
                # Целые константы модулей — выражения времени компиляции, без чтения памяти.
                out.append(f'#define {symbol} (({self.r.ctype(t)}){initializers.initializer(t, value, symbol)})')
            elif isinstance(t, (ListT, ArrayT)):
                out.append(f'extern P2cList {symbol};')
            elif isinstance(t, (DictT, SetT)):
                out.append(f'extern P2cDict {symbol};')
            elif isinstance(t, BytesT):
                out.append(f'extern P2cBuf {symbol};')
            else:
                out.append(f'extern const {self.r.ctype(t)} {symbol};')
        for name in self.image_roots():
            class_name = type(self.image.root_values[name]).__name__
            out.append(f'extern P2cC_{self.p.root(class_name)} p2c_root_{name};')
        out.append('')
        return '\n'.join(out)

    def image_roots(self) -> list[str]:
        return list(self.image.root_values)

    def entry_signature(self, export_name: str, arguments: list) -> str:
        params = []
        for index, spec in enumerate(arguments):
            if spec == 'bool' or (isinstance(spec, tuple) and spec[0] == 'value'):
                params.append(f'uint8_t a{index}')
        return f'void {export_name}({", ".join(params) or "void"}) __banked'

    # --- единицы кода --------------------------------------------------------------------

    def plan_units(self) -> list[Unit]:
        units = []
        for plan in self.c.queue:
            if plan.kind == 'value_init':
                continue
            lines = ['static ' + line if index == 0 else line
                     for index, line in enumerate(self.m.function_definition(plan))]
            size = self.sizes.get(plan.c_name) or max(40, 11 * len(lines))
            lines.insert(0, self.m.function_comment(plan))    # комментарий на оценку размера не влияет
            unit = Unit(plan.c_name, lines, size, f'static {self.m.signature(plan)};', plan)
            unit.callees = self.referenced(lines)
            units.append(unit)
        return units

    @staticmethod
    def referenced(lines: list[str]) -> set[str]:
        names = set()
        for line in lines:
            names.update(CALL_RE.findall(line))
        return names

    def entry_units(self, root_symbols: dict[str, str]) -> list[Unit]:
        units = []
        converters = set()
        for export_name, root_name, class_name, method, arguments in self.entries:
            found = self.p.find_method(class_name, method)
            plan = self.c.plans[('method', found[0].name, method)]
            lines = []
            prelude = []
            call = [f'(P2cC_{self.p.root(class_name)} *)&{root_symbols[root_name]}']
            for index, (param, spec) in enumerate(zip(plan.params[1:], arguments)):
                if spec == 'bool':
                    call.append(f'(uint8_t)(a{index} != 0)')
                elif spec == 'target':
                    call.append('0')
                elif isinstance(spec, tuple) and spec[0] == 'value':
                    if spec[1] not in converters:
                        converters.add(spec[1])
                        lines.extend(self.m.input_converter(spec[1]))
                    prelude.append(f'    P2cV_{spec[1]} v{index};')
                    prelude.append(f'    v{index} = p2c_input_{spec[1]}(a{index});')
                    call.append(f'v{index}')
                else:
                    raise TranslationError(f'аргумент входа Z80 {spec}')
            signature = self.entry_signature(export_name, arguments)
            lines += [signature + ' {', *prelude, f'    {plan.c_name}({", ".join(call)});', '}']
            unit = Unit(export_name, lines, 60 + 11 * len(lines))
            unit.callees = self.referenced(lines)
            unit.home_plan = plan.c_name
            unit.extern_prototype = signature + ';'
            units.append(unit)
        return units

    def mark_units(self, part_lines: int = 300) -> list[Unit]:
        """Разметка сборщика частями по диапазонам номеров классов (целиком не входит в банк)."""
        cases = sorted(self.m.mark_cases(), key=lambda item: item[0])
        groups: list[list[tuple[int, list[str]]]] = [[]]
        count = 0
        for number, lines in cases:
            if groups[-1] and count + len(lines) > part_lines:
                groups.append([])
                count = 0
            groups[-1].append((number, lines))
            count += len(lines)
        units = []
        top = ['void p2c_mark_children__b(P2cObject *object) __banked {', '    uint8_t cls = object->cls;']
        for index, group in enumerate(groups):
            name = f'p2c_mark_part{index + 1}'
            lines = [f'void {name}(P2cObject *object) __banked {{', '    uint16_t i;', '    (void)i;',
                     '    switch (object->cls) {']
            for _number, case_lines in group:
                lines.extend(case_lines)
            lines += ['    default: break;', '    }', '}']
            unit = Unit(name, lines, self.sizes.get(name) or 30 * len(lines))
            unit.callees = self.referenced(lines)
            unit.extern_prototype = f'void {name}(P2cObject *object) __banked;'
            units.append(unit)
            top.append(f'    if (cls <= {group[-1][0]}) {{ {name}(object); return; }}')
        top.append('}')
        head = Unit('p2c_mark_children__b', top, 60 + 12 * len(top))
        head.callees = self.referenced(top)
        return [head] + units

    # --- раскладка по банкам --------------------------------------------------------------

    def new_bank(self) -> Bank:
        if len(self.banks) >= len(self.bank_pages):
            raise TranslationError(f'не хватает страниц банков: нужно больше {len(self.bank_pages)}')
        bank = Bank(self.bank_pages[len(self.banks)])
        self.banks.append(bank)
        return bank

    def bank_layout(self) -> dict[str, int]:
        return {name: self.banks.index(bank) for name, bank in self.home.items()}

    def place_previous(self, units: list[Unit], helper_closure: dict[str, set[str]],
                       helper_sizes: dict[str, int]) -> bool:
        if not self.previous or {unit.name for unit in units} != set(self.previous):
            return False
        count = max(self.previous.values()) + 1
        if count > len(self.bank_pages):
            return False
        sizes = [0] * count
        helpers: list[set[str]] = [set() for _ in range(count)]
        for unit in units:
            index = self.previous[unit.name]
            needed = set()
            for name in unit.callees:
                needed |= helper_closure.get(name, set())
            sizes[index] += (unit.size + sum(helper_sizes.get(name, 200) for name in needed - helpers[index]) +
                             (40 if unit.plan is not None else 0))
            helpers[index] |= needed
        if max(sizes) > self.bank_limit:
            return False
        self.banks = [Bank(self.bank_pages[index], size=sizes[index]) for index in range(count)]
        for unit in units:
            bank = self.banks[self.previous[unit.name]]
            bank.units.append(unit)
            self.home[unit.name] = bank
        return True

    def place(self, units: list[Unit], helper_closure: dict[str, set[str]], helper_sizes: dict[str, int]) -> None:
        """Жадная раскладка по порядку очереди; копии вспомогательных функций и обёртки учитываются."""
        if self.place_previous(units, helper_closure, helper_sizes):
            return
        bank = self.new_bank()
        bank_helpers: set[str] = set()
        for unit in units:
            helpers = set()
            for name in unit.callees:
                helpers |= helper_closure.get(name, set())
            extra = sum(helper_sizes.get(name, 200) for name in helpers - bank_helpers)
            increment = unit.size + extra + (40 if unit.plan is not None else 0)
            if bank.units and bank.size + increment > self.bank_limit:
                bank = self.new_bank()
                bank_helpers = set()
                extra = sum(helper_sizes.get(name, 200) for name in helpers)
                increment = unit.size + extra + (40 if unit.plan is not None else 0)
            bank.units.append(unit)
            bank.size += increment
            bank_helpers |= helpers
            self.home[unit.name] = bank

    # --- генерация ---------------------------------------------------------------------------

    def generate(self, value_structs: list[str], root_symbols: dict[str, str]) -> dict[str, str]:
        dispatchers = {dispatcher.c_name: dispatcher for dispatcher in self.layout.dispatchers.values()}
        memberships = {name: values for values, name in self.layout.memberships.items()}
        helper_code: dict[str, tuple[str, list[str]]] = {}
        for name, dispatcher in dispatchers.items():
            prototype, lines = self.m.dispatcher_code(dispatcher)
            helper_code[name] = (prototype, lines)
        for name, values in memberships.items():
            lines = CModule.membership_code(values, name)
            helper_code[name] = (lines[0].rstrip(' {') + ';', lines)

        units = self.plan_units()
        entry_units = self.entry_units(root_symbols)
        mark_units = self.mark_units()
        # Точки входа — в банке своего метода; разметка сборщика — отдельными единицами в конце.
        by_name = {unit.name: unit for unit in units}
        ordered: list[Unit] = []
        for unit in units:
            ordered.append(unit)
            for entry in entry_units:
                if entry.home_plan == unit.name:
                    ordered.append(entry)
        ordered.extend(mark_units)
        closure: dict[str, set[str]] = {}
        for name in helper_code:
            seen = {name}
            pending = [name]
            while pending:
                for callee in self.referenced(helper_code[pending.pop()][1]):
                    if callee in helper_code and callee not in seen:
                        seen.add(callee)
                        pending.append(callee)
            closure[name] = seen
        self.place(ordered, closure, {name: self.sizes.get(name, 200) for name in helper_code})

        plan_names = set(by_name)
        # Вспомогательные функции банка: диспетчеры и принадлежности (с их вызовами).
        bank_helpers: dict[int, list[str]] = {}
        for bank in self.banks:
            needed: list[str] = []
            pending = set()
            for unit in bank.units:
                pending |= {name for name in unit.callees if name in helper_code}
            while pending:
                name = pending.pop()
                if name in needed:
                    continue
                needed.append(name)
                pending |= {callee for callee in self.referenced(helper_code[name][1])
                            if callee in helper_code and callee not in needed}
            bank_helpers[bank.page] = sorted(needed)

        # Межбанковые вызовы: вызываемые из чужого банка функции получают обёртки.
        wrapped: set[str] = set()
        for bank in self.banks:
            names = set()
            for unit in bank.units:
                names |= unit.callees
            for helper in bank_helpers[bank.page]:
                names |= self.referenced(helper_code[helper][1])
            for name in names:
                if name in plan_names and self.home[name] is not bank:
                    wrapped.add(name)

        files: dict[str, str] = {}
        header = self.header(value_structs)
        wrapper_prototypes = []
        for name in sorted(wrapped):
            wrapper_prototypes.append(self.wrapper_head(by_name[name].plan) + ';')
        entry_prototypes = [unit.extern_prototype for unit in entry_units + mark_units if unit.extern_prototype]
        header += '\n'.join(wrapper_prototypes + entry_prototypes +
                            ['void p2c_mark_children__b(P2cObject *object) __banked;', '', '#endif', ''])
        files['p2c_z80_program.h'] = header

        for bank in self.banks:
            lines = ['/* Сгенерировано транслятором p2c: банк кода на странице '
                     f'#{bank.page:02X}. */', '#include "p2c_z80_program.h"', '']
            local = {unit.name for unit in bank.units}

            shims: dict[str, list[str]] = {}

            def rename(text: str) -> str:
                def replace(match: re.Match) -> str:
                    name = match[1]
                    if name in plan_names and name not in local:
                        plan = by_name[name].plan
                        if self.returns_struct(plan):
                            if name not in shims:
                                shims[name] = self.struct_shim(plan)
                            return match[0].replace(name, name + '__s', 1)
                        return match[0].replace(name, name + '__b', 1)
                    return match[0]
                return CALL_RE.sub(replace, text)

            for unit in bank.units:
                if unit.prototype:
                    lines.append(unit.prototype)
            for helper in bank_helpers[bank.page]:
                lines.append(helper_code[helper][0])
            lines.append('')
            body: list[str] = []
            for helper in bank_helpers[bank.page]:
                body.extend(rename(line) for line in helper_code[helper][1])
                body.append('')
            for unit in bank.units:
                body.extend(rename(line) for line in unit.lines)
                body.append('')
            for unit in bank.units:
                if unit.name in wrapped:
                    body.extend(self.wrapper(unit.plan))
                    body.append('')
            # Переходники структурного результата: ближняя функция зовёт банковую обёртку с указателем.
            for name in sorted(shims):
                lines.append(shims[name][0].rstrip(' {') + ';')
            for name in sorted(shims):
                body.extend(shims[name])
                body.append('')
            files[f'bank_{bank.page:02x}.c'] = '\n'.join(lines + [''] + body) + '\n'
        return files

    def layout_check(self) -> str:
        """Статические проверки: смещения полей SDCC совпадают с раскладкой образа памяти."""
        from .z80layout import BUF_HEADER, DEQUE_HEADER, DICT_HEADER, FN_SIZE, LIST_HEADER, STR_HEADER, Z80Layout
        z = Z80Layout(self.c, self.r, self.layout)
        lines = ['/* Сгенерировано p2c: проверка раскладки структур для образа памяти Z80. */',
                 '#include "p2c_z80_program.h"']

        def check(condition: str) -> None:
            lines.append(f'_Static_assert({condition}, "{condition}");')

        for struct, size in (('P2cList', LIST_HEADER), ('P2cDeque', DEQUE_HEADER), ('P2cDict', DICT_HEADER),
                             ('P2cBuf', BUF_HEADER), ('P2cStr', STR_HEADER), ('P2cFn', FN_SIZE),
                             ('P2cRect', 16), ('P2cImage', 2), ('P2cHandle', 2)):
            check(f'sizeof({struct}) == {size}')
        for root, layout in sorted(self.layout.roots.items()):
            presence, slots, total = z.root_layout(root)
            if presence >= 0:
                check(f'offsetof(struct P2cC_{root}, presence) == {presence}')
            for index, offset in slots.items():
                check(f'offsetof(struct P2cC_{root}, s{index}) == {offset}')
            check(f'sizeof(struct P2cC_{root}) == {total}')
        for name, t in self.r.order:
            if isinstance(t, TupleT):
                for index, (offset, _size, _item) in enumerate(z.tuple_members(t)):
                    check(f'offsetof({name}, v{index}) == {offset}')
                check(f'sizeof({name}) == {z.sizeof(t)}')
            else:
                check(f'offsetof({name}, v) == 1')
                check(f'sizeof({name}) == {z.sizeof(t)}')
        for class_name, info in sorted(self.p.classes.items()):
            if not info.frozen or not self.m.value_class_used(class_name):
                continue
            for member, offset, _size, _t in z.value_members(class_name):
                check(f'offsetof(P2cV_{class_name}, {cname(member)}) == {offset}')
            check(f'sizeof(P2cV_{class_name}) == {z.sizeof(ValT(class_name))}')
        return '\n'.join(lines) + '\n'

    def returns_struct(self, plan) -> bool:
        ret_c = self.m.return_ctype(plan)
        return ret_c.startswith(('P2cT', 'P2cN', 'P2cV_')) or ret_c in ('P2cRect', 'P2cFn')

    def call_arguments(self, plan) -> list[str]:
        arguments = []
        if plan.kind in ('nested', 'lambda') and plan.captures:
            arguments.append('p2c_direct' if self.layout.env_is_direct(plan) else 'p2c_env')
        arguments.extend(cname(param.name) for param in plan.params)
        return arguments

    def wrapper_head(self, plan) -> str:
        """Заголовок межбанковой обёртки. SDCC 4.6 читает скрытый указатель структурного
        результата __banked-функции без учёта байта банка в стеке, поэтому структура
        возвращается через явный параметр-указатель."""
        signature = self.m.signature(plan)
        name = plan.c_name
        if self.returns_struct(plan):
            ret_c = self.m.return_ctype(plan)
            head = signature.replace(f'{ret_c} {name}(', f'void {name}__b({ret_c} *p2c_out, ', 1)
            return head.replace(', void)', ')') + ' __banked'
        return signature.replace(f' {name}(', f' {name}__b(', 1) + ' __banked'

    def wrapper(self, plan) -> list[str]:
        """Межбанковая обёртка: параметры передаются дальше, результат — через временную."""
        name = plan.c_name
        head = self.wrapper_head(plan) + ' {'
        arguments = self.call_arguments(plan)
        ret_c = self.m.return_ctype(plan)
        if ret_c == 'void':
            return [head, f'    {name}({", ".join(arguments)});', '}']
        if self.returns_struct(plan):
            return [head, f'    {ret_c} r;', f'    r = {name}({", ".join(arguments)});', '    *p2c_out = r;', '}']
        return [head, f'    {ret_c} r;', f'    r = {name}({", ".join(arguments)});', '    return r;', '}']

    def struct_shim(self, plan) -> list[str]:
        """Ближний переходник в банке вызывающего: обычный структурный возврат поверх обёртки."""
        name = plan.c_name
        signature = self.m.signature(plan)
        head = 'static ' + signature.replace(f' {name}(', f' {name}__s(', 1) + ' {'
        ret_c = self.m.return_ctype(plan)
        arguments = ['&r'] + self.call_arguments(plan)
        return [head, f'    {ret_c} r;', f'    {name}__b({", ".join(arguments)});', '    return r;', '}']
