"""Раскладка C-типов на Z80 (SDCC): без выравнивания, little-endian, указатель 2 байта.

Совпадает с тем, как SDCC размещает структуры для -mz80: члены подряд без
заполнителей. Нужна для сериализации начального состояния в страницы.
"""
from __future__ import annotations

import dataclasses

from .compiler import int_empty
from .errors import TranslationError
from .ptypes import (
    ArrayT, BoolT, BottomT, BytesT, DequeT, DictT, ExtT, FnT, FontT, ImageT, IntT, ListT, NoneT,
    ObjT, OptT, SetT, StrT, T, TargetT, TupleT, ValT, VoidT, is_pointer,
)

POINTER = 2
# Заголовки контейнеров рантайма на Z80 (p2c_runtime.h, P2cSize = uint16_t, буфер — uint32_t длина).
LIST_HEADER = 1 + 1 + 2 + 2 + POINTER + 1      # cls gc length capacity data page
DEQUE_HEADER = 1 + 1 + 2 + 2 + 2 + POINTER + 1  # cls gc length capacity head data page
DICT_HEADER = 1 + 1 + 2 + 2 + 2 + 1 + 1 + POINTER * 3
BUF_HEADER = 1 + 1 + 4 + 4 + POINTER + 1        # cls gc length capacity data page
STR_HEADER = 1 + 1 + 2 + POINTER
FN_SIZE = 1 + POINTER


class Z80Layout:
    def __init__(self, compiler, crepr, layout) -> None:
        self.c = compiler
        self.p = compiler.program
        self.r = crepr
        self.layout = layout

    def resolved(self, t: T) -> T:
        if isinstance(t, IntT) and int_empty(t):
            return IntT(-(1 << 31), (1 << 31) - 1)
        return t

    def sizeof(self, t: T) -> int:
        t = self.resolved(t)
        if isinstance(t, IntT):
            return self.r.cint(t).bits // 8
        if isinstance(t, BoolT) or isinstance(t, NoneT):
            return 1
        if is_pointer(t):
            return POINTER
        if isinstance(t, OptT):
            if is_pointer(t.inner):
                return POINTER
            if isinstance(t.inner, FnT):
                return FN_SIZE
            return 1 + self.sizeof(self.r.normalized(t).inner)
        # Пустые структуры в C содержат байт-заполнитель (uint8_t unused).
        if isinstance(t, TupleT):
            return max(1, sum(self.sizeof(item) for item in self.r.normalized(t).items))
        if isinstance(t, ValT):
            if t.cls == 'Rect':
                return 16
            return max(1, sum(size for _name, _offset, size, _t in self.value_members(t.cls)))
        if isinstance(t, FnT):
            return FN_SIZE
        if isinstance(t, ImageT):
            return 2
        if isinstance(t, (TargetT, FontT, ExtT)):
            return POINTER
        raise TranslationError(f'Z80: размер {t} не определён')

    def value_members(self, class_name: str) -> list[tuple[str, int, int, T]]:
        info = self.p.classes[class_name]
        members = []
        offset = 0
        for item in dataclasses.fields(info.python):
            field_t = self.c.field_type(class_name, item.name)
            if isinstance(field_t, BottomT):
                continue
            size = self.sizeof(field_t)
            members.append((item.name, offset, size, field_t))
            offset += size
        return members

    def tuple_members(self, t: TupleT) -> list[tuple[int, int, T]]:
        members = []
        offset = 0
        for item in self.r.normalized(t).items:
            size = self.sizeof(item)
            members.append((offset, size, item))
            offset += size
        return members

    def root_layout(self, root: str) -> tuple[int, dict[int, int], int]:
        """Смещения слотов корневой структуры: (смещение бита присутствия, слоты, размер)."""
        layout = self.layout.roots[root]
        offset = LIST_HEADER if layout.list_based else 2
        presence = -1
        if layout.presence_bits:
            presence = offset
            offset += 2
        slots = {}
        for index, ctype in enumerate(layout.slots):
            slots[index] = offset
            offset += self.slot_size(root, index)
        return presence, slots, offset

    def slot_size(self, root: str, slot: int) -> int:
        layout = self.layout.roots[root]
        for attr, index in layout.attribute_slot.items():
            if index == slot:
                return self.sizeof(self.c.field_type(self.class_with(root, attr), attr))
        raise TranslationError(f'{root}: слот {slot} без атрибута')

    def class_with(self, root: str, attr: str) -> str:
        cell = self.c.fields[(root, attr)]
        return sorted(cell.classes)[0]

    def object_size(self, class_name: str) -> int:
        root = self.p.root(class_name)
        layout = self.layout.roots.get(root)
        if layout is None:
            return 2
        presence, slots, total = self.root_layout(root)
        used = sorted(layout.class_slots.get(class_name, set()))
        if not used:
            return (LIST_HEADER if layout.list_based else 2) + (2 if presence >= 0 else 0)
        last = used[-1]
        return slots[last] + self.slot_size(root, last)
