"""Проверка 512-байтного кэша TS-Conf при исполнении Z80 на модели.

Правила тегов и заполнения — z80_main.inl Unreal (tslabs/zx-evo): прямая адресация,
пара байтов за чтение DRAM, тег = физический адрес >> 9. Запись CPU инвалидирует пару;
DMA и записи самой модели кэш не инвалидируют. Возвращаются реальные данные RAM:
это пассивный аудит устаревших чтений, а не изменение поведения проверяемой игры.
Тактов ожидания DRAM и арбитража здесь нет; число промахов не является замером FPS.
"""
from __future__ import annotations


class CacheProbe:
    def __init__(self, model, masks=(7, 15)):
        self.model = model
        self.states = {mask: {'tags': [-1] * 256, 'data': bytearray(512), 'reads': 0, 'misses': 0,
                              'window_reads': [0] * 4, 'window_misses': [0] * 4,
                              'stale': 0, 'examples': []} for mask in masks}
        self.frame = 0
        self.old_read = model.cpu.set_read_callback(self.read)
        self.old_write = model.cpu.set_write_callback(self.write)

    def read(self, address):
        address &= 0xFFFF
        model = self.model
        value = model.memory[address]
        window = address >> 14
        tag = (model.windows[window] << 5) | ((address >> 9) & 31)
        index = (address >> 1) & 255
        byte = address & 511
        for mask, state in self.states.items():
            state['reads'] += 1
            state['window_reads'][window] += 1
            if not mask & (1 << window) or state['tags'][index] != tag:
                state['misses'] += 1
                state['window_misses'][window] += 1
                state['tags'][index] = tag
                state['data'][byte & ~1] = model.memory[address & ~1]
                state['data'][byte | 1] = model.memory[address | 1]
            elif state['data'][byte] != value:
                state['stale'] += 1
                if len(state['examples']) < 16:
                    state['examples'].append({'frame': self.frame, 'pc': model.cpu.pc, 'address': address,
                                               'page': model.windows[window], 'cached': state['data'][byte],
                                               'ram': value})
        return value

    def write(self, address, value):
        address &= 0xFFFF
        for state in self.states.values():
            state['tags'][(address >> 1) & 255] = -1
        self.model.memory[address] = value

    def close(self):
        self.model.cpu.set_read_callback(self.old_read or (lambda address: self.model.memory[address & 0xFFFF]))
        self.model.cpu.set_write_callback(self.old_write or self.direct_write)
        return {mask: {key: value for key, value in state.items() if key not in ('tags', 'data')}
                for mask, state in self.states.items()}

    def direct_write(self, address, value):
        self.model.memory[address & 0xFFFF] = value
