"""Точная включающая стоимость процедур модели Z80: точки входа и возврат по SP/банку."""
from __future__ import annotations


class ProcedureProfile:
    def __init__(self, model, entries, reserved=()):
        self.model = model
        self.entries = entries  # (физическая страница, адрес CPU) → имя
        self.reserved = set(reserved)
        self.clock = 0
        self.active = []
        self.totals = {}
        self.marked = set()
        self.enabled = False

    def identity(self, address):
        return self.model.windows[address >> 14], address

    def refresh(self):
        wanted = {pc for _, pc in self.entries} if self.enabled else set()
        wanted.update(call['return'][1] for call in self.active)
        for pc in self.marked - wanted - self.reserved:
            self.model.cpu.clear_breakpoint(pc)
        for pc in wanted - self.marked:
            self.model.cpu.set_breakpoint(pc)
        self.marked = wanted

    def observe(self):
        cpu = self.model.cpu
        here = self.identity(cpu.pc)
        while self.active and (here, cpu.sp) == (self.active[-1]['return'], self.active[-1]['sp']):
            call = self.active.pop()
            ticks = self.clock - call['start']
            row = self.totals.setdefault(call['name'], dict(calls=0, ticks=0, maximum=0))
            row['calls'] += 1
            row['ticks'] += ticks
            row['maximum'] = max(row['maximum'], ticks)
        if self.enabled and here in self.entries:
            address = self.model.word(cpu.sp)
            self.active.append(dict(name=self.entries[here], start=self.clock,
                                    sp=(cpu.sp + 2) & 0xFFFF))
            self.active[-1]['return'] = self.identity(address)
        self.refresh()

    def report(self):
        if self.active:
            raise RuntimeError(f'Незавершённые процедуры: {self.active}')
        return self.totals
