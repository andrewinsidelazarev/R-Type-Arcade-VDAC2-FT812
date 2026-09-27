"""Раскладка классов и производные C-объявления после анализа.

Номера классов назначаются обходом иерархий в прямом порядке: подклассы
занимают непрерывные диапазоны. Атрибуты одной иерархии размещаются в
слотах корневой структуры: атрибуты, не встречающиеся вместе ни в одном
классе, делят слот одного C-типа (раскраска), поэтому доступ к полю через
базовый тип — постоянное смещение без перехода по номеру класса.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field

from .compiler import Compiler, Plan, int_empty
from .errors import TranslationError
from .ptypes import (
    ArrayT, BoolT, BottomT, BytesT, DequeT, DictT, ExtT, FnT, FontT, I32, ImageT, IntT, ListT, NoneT,
    ObjT, OptT, SetT, StrT, T, TargetT, TupleT, ValT, VoidT, has_references, is_int_like, is_pointer,
)

FIRST_CONTAINER_CLASS = 160


@dataclass
class Dispatcher:
    c_name: str
    ids: tuple
    params: list
    ret: T


@dataclass
class RootLayout:
    root: str
    slots: list[str] = field(default_factory=list)          # C-тип слота
    attribute_slot: dict[str, int] = field(default_factory=dict)
    class_slots: dict[str, set[int]] = field(default_factory=dict)
    list_based: bool = False
    presence_bits: dict[str, int] = field(default_factory=dict)


class Layout:
    def __init__(self, compiler: Compiler, crepr) -> None:
        self.c = compiler
        self.p = compiler.program
        self.r = crepr
        self.class_ids: dict[str, int] = {}
        self.roots: dict[str, RootLayout] = {}
        self.container_classes: dict[T, tuple[int, str, T]] = {}
        self.env_classes: dict[str, int] = {}
        self.dispatchers: dict[tuple, Dispatcher] = {}
        self.memberships: dict[tuple, str] = {}
        self.constant_symbols: dict[int, str] = {}
        self._assign_class_ids()
        self._layout_roots()

    # --- номера классов --------------------------------------------------------------

    def _assign_class_ids(self) -> None:
        number = 1
        roots = sorted(name for name, info in self.p.classes.items() if not info.bases)
        for root in roots:
            for name in self.p.descendants(root):
                self.class_ids[name] = number
                number += 1
        if number >= FIRST_CONTAINER_CLASS:
            raise TranslationError(f'классов {number}: не помещаются в номера до {FIRST_CONTAINER_CLASS}')

    def class_id_symbol(self, class_name: str) -> str:
        return f'P2C_CLS_{class_name}'

    def class_set_test(self, expr: str, classes: list[str]) -> str:
        numbers = sorted({self.class_ids[name] for name in classes})
        ranges = []
        start = previous = numbers[0]
        for number in numbers[1:]:
            if number == previous + 1:
                previous = number
                continue
            ranges.append((start, previous))
            start = previous = number
        ranges.append((start, previous))
        parts = []
        for low, high in ranges:
            if low == high:
                parts.append(f'({expr} == {low})')
            else:
                parts.append(f'({expr} >= {low} && {expr} <= {high})')
        return '(' + ' || '.join(parts) + ')'

    # --- слоты иерархий -------------------------------------------------------------

    def _layout_roots(self) -> None:
        by_root: dict[str, list] = {}
        for (root, name), cell in self.c.fields.items():
            if name.startswith('<') or not cell.classes or not cell.used:
                continue
            if self.p.classes[root].frozen:
                continue
            by_root.setdefault(root, []).append(cell)
        for root in sorted(set(by_root) | {self.p.root(name) for name in self.c.instantiated}):
            layout = RootLayout(root, list_based=self.p.list_base_of(root) is not None)
            cells = sorted(by_root.get(root, []), key=lambda cell: (-len(cell.classes), cell.name))
            for cell in cells:
                if isinstance(cell.t, BottomT):
                    raise TranslationError(f'поле {root}.{cell.name}: форма не выведена')
                ctype = self.r.ctype(cell.t)
                chosen = None
                for index, slot_type in enumerate(layout.slots):
                    if slot_type != ctype:
                        continue
                    if any(index in layout.class_slots.get(name, set()) for name in cell.classes):
                        continue
                    chosen = index
                    break
                if chosen is None:
                    chosen = len(layout.slots)
                    layout.slots.append(ctype)
                layout.attribute_slot[cell.name] = chosen
                for name in cell.classes:
                    layout.class_slots.setdefault(name, set()).add(chosen)
            # Биты присутствия атрибутов, которые проверяются у экземпляра.
            queried = sorted(name for name in layout.attribute_slot if name in self.c.presence_queries)
            if len(queried) > 16:
                raise TranslationError(f'{root}: больше 16 атрибутов с проверкой присутствия')
            layout.presence_bits = {name: index for index, name in enumerate(queried)}
            self.roots[root] = layout

    def presence_code(self, owner_code: str, class_name: str, attr: str) -> str:
        """Условие: атрибут записан в этот экземпляр (как hasattr CPython)."""
        root = self.p.root(class_name)
        layout = self.roots[root]
        bit = layout.presence_bits.get(attr)
        if bit is None:
            raise TranslationError(f'{class_name}.{attr}: нет бита присутствия')
        return f'((((P2cC_{root} *)({owner_code}))->presence & 0x{1 << bit:04X}u) != 0)'

    def presence_set(self, owner_code: str, class_name: str, attr: str) -> str:
        """Инструкция поднятия бита присутствия при записи атрибута (или пусто)."""
        root = self.p.root(class_name)
        layout = self.roots.get(root)
        if layout is None or attr not in layout.presence_bits:
            return ''
        return f'((P2cC_{root} *)({owner_code}))->presence |= 0x{1 << layout.presence_bits[attr]:04X}u; '

    def field_code(self, owner_code: str, class_name: str, attr: str) -> str:
        root = self.p.root(class_name)
        layout = self.roots.get(root)
        if layout is None or attr not in layout.attribute_slot:
            raise TranslationError(f'поле {class_name}.{attr} не размещено')
        slot = layout.attribute_slot[attr]
        return f'((P2cC_{root} *)({owner_code}))->s{slot}'

    def any_field_code(self, owner_code: str, attr: str) -> str:
        raise TranslationError(f'поле {attr} у object без общей базы не поддержано')

    def new_object_code(self, class_name: str) -> str:
        root = self.p.root(class_name)
        return f'((P2cC_{root} *)p2c_new_object({self.class_id_symbol(class_name)}, P2C_SIZE_{class_name}))'

    # --- контейнеры, окружения, вызываемые значения ------------------------------------

    def mark_signature(self, t: T):
        """Разметка элемента для сборщика: без ссылок, одна ссылка или структура со ссылками."""
        if not has_references(t):
            return 'raw'
        if is_pointer(t) or (isinstance(t, OptT) and is_pointer(t.inner)):
            return 'ptr'
        return self.r.normalized(t)

    def container_class_symbol(self, t: T) -> str:
        """Номер класса контейнера: общий для контейнеров с одинаковой разметкой элементов."""
        if isinstance(t, (ListT, ArrayT)):
            key = ('list', self.mark_signature(t.elem))
        elif isinstance(t, DequeT):
            key = ('deque', self.mark_signature(t.elem))
        elif isinstance(t, SetT):
            key = ('dict', self.mark_signature(t.elem), 'raw')
        elif isinstance(t, DictT):
            key = ('dict', self.mark_signature(t.k), self.mark_signature(t.v))
        else:
            raise TranslationError(f'класс контейнера для {t}')
        if key not in self.container_classes:
            number = FIRST_CONTAINER_CLASS + len(self.container_classes) + len(self.env_classes)
            if number >= 250:
                raise TranslationError('номера классов контейнеров исчерпаны')
            self.container_classes[key] = (number, f'P2C_CLS_C{number}', key)
        return self.container_classes[key][1]

    def env_is_direct(self, plan: Plan) -> bool:
        """Единственный захват-ссылка передаётся как окружение без выделения."""
        return (len(plan.captures) == 1 and not plan.captures[0].by_pointer and
                isinstance(plan.captures[0].t, ObjT))

    def env_symbol(self, plan: Plan) -> str:
        if plan.c_name not in self.env_classes:
            number = FIRST_CONTAINER_CLASS + len(self.container_classes) + len(self.env_classes)
            if number >= 250:
                raise TranslationError('номера классов окружений исчерпаны')
            self.env_classes[plan.c_name] = number
        return f'P2C_CLS_E_{plan.c_name}'

    def new_env_code(self, plan: Plan) -> str:
        self.env_symbol(plan)
        return f'((P2cE_{plan.c_name} *)p2c_new_object({self.env_symbol(plan)}, sizeof(P2cE_{plan.c_name})))'

    def fn_id_symbol(self, number: int) -> str:
        return f'P2C_FN_{number}'

    def dispatcher(self, ids: frozenset, arity: int) -> Dispatcher:
        key = (tuple(sorted(ids)), arity)
        if key in self.dispatchers:
            return self.dispatchers[key]
        params: list[T] = [None] * arity
        ret: T = BottomT()
        for number in key[0]:
            target_key, plan = self.c.fn_targets[number]
            if plan is None:
                extern = self.c.extern_by_key(target_key)
                target_params = list(extern.params)
                target_ret = extern.ret
            else:
                plan_params = plan.params[1:] if target_key[0] == 'bound' else plan.params
                target_params = [param.t if not isinstance(param.t, BottomT) else param.declared
                                 for param in plan_params]
                target_ret = plan.ret if not isinstance(plan.ret, BottomT) else plan.ret_declared
            for index, item in enumerate(target_params):
                if item is None or isinstance(item, BottomT):
                    continue
                if isinstance(item, IntT) and int_empty(item):
                    item = IntT(-(1 << 31), (1 << 31) - 1)
                params[index] = item if params[index] is None else self.c.join(params[index], item)
            if target_ret is None or isinstance(target_ret, (VoidT, NoneT)):
                target_ret = VoidT()
            if isinstance(ret, BottomT):
                ret = target_ret
            elif not isinstance(target_ret, VoidT) and not isinstance(ret, VoidT):
                ret = self.c.join(ret, target_ret)
        for index, item in enumerate(params):
            if item is None:
                raise TranslationError(f'вызываемое значение: форма параметра {index} не выведена')
        dispatcher = Dispatcher(f'p2c_call{len(self.dispatchers) + 1}', key[0], params,
                                VoidT() if isinstance(ret, BottomT) else ret)
        self.dispatchers[key] = dispatcher
        return dispatcher

    # --- константы ------------------------------------------------------------------

    def constant_code(self, number: int) -> str:
        value, t = self.c.constants[number]
        symbol = self.constant_symbols.setdefault(number, f'p2c_k{len(self.constant_symbols) + 1}')
        if isinstance(t, (TupleT, ValT)):
            return symbol
        if is_int_like(t):
            return symbol
        return f'(&{symbol})'

    def membership_function(self, values: list[int]) -> str:
        key = tuple(values)
        if key not in self.memberships:
            self.memberships[key] = f'p2c_in{len(self.memberships) + 1}'
        return self.memberships[key]
