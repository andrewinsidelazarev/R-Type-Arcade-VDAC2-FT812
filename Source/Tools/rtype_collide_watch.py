"""Наблюдение за записями столкновений на эталонной машине (unicorn, код ROM V30) — для rtype_check --collide-watch.

Вопрос (2026-09-26, кэш записей столкновений): меняются ли поля записей, которые читают сканы столкновений, во время
цикла списка объектов IRQ0 ($0263…$0277 — враги), кем-то, кроме самих сканов при попадании. Записи — поля
объектов-слотов игрока: SI = слот + #16 (флаг [si+1], прямоугольник [si+2…si+9]: X1, X2, Y1, Y2) и у лучей #A8/#C8 —
прямоугольник и владелец [si+#C] (#B4, #D4). Сканы: $F485 (#56), $F493 (#76, #136, #156), $F4AA (#F6, #116), $F4BF и
$F525 (#B6, #D6; лучи #A8, #C8), $F548 (#4D6, #4F6, #516), $F560 (#176 + #20·k, k < 24); проверка прямоугольника
$F578.

Ловушки: UC_HOOK_CODE на вход и выход цикла списка и на входы сканов, UC_HOOK_MEM_WRITE на рабочее ОЗУ #40040…#4051F.
В журнал — каждая запись в наблюдаемые байты во время цикла списка: IP инструкции (линейный = #400 + IP при CS =
#0040), какое поле, обработчик текущего объекта ([bp] при BP списка), кадр. Итог — счёт по инструкциям и полям.
"""
from __future__ import annotations

import json
from pathlib import Path

LOOP_B_START = 0x00663                  # IP $0263: MOV BP,#540 — начало цикла списка
LOOP_B_END = 0x00677                    # IP $0277: CALL $0653 — цикл списка кончился
SCANS = {0x0F885: '$F485', 0x0F893: '$F493', 0x0F8AA: '$F4AA', 0x0F8BF: '$F4BF', 0x0F925: '$F525',
         0x0F948: '$F548', 0x0F960: '$F560', 0x0F978: '$F578', 0x0FA94: '$F694', 0x0FADA: '$F6DA',
         0x0FB5F: '$F75F'}
FLAG_BOX = [0x56, 0xB6, 0xD6, 0x4D6, 0x4F6, 0x516] + [0x176 + 0x20 * k for k in range(24)]
BOX_ONLY = [0x76, 0x136, 0x156, 0xF6, 0x116]      # флаг сканы не читают, но $F4AA пишет INC [si+1] — тоже смотрим
BEAMS = [0xA8, 0xC8]


def watched_fields() -> dict[int, tuple[int, str]]:
    """Смещение в рабочем ОЗУ → (запись, поле)."""
    fields: dict[int, tuple[int, str]] = {}
    for record in FLAG_BOX + BOX_ONLY:
        fields[record + 1] = (record, 'флаг')
        for index, name in enumerate(('X1', 'X1', 'X2', 'X2', 'Y1', 'Y1', 'Y2', 'Y2')):
            fields[record + 2 + index] = (record, name)
    for record in BEAMS:
        for index, name in enumerate(('X1', 'X1', 'X2', 'X2', 'Y1', 'Y1', 'Y2', 'Y2')):
            fields[record + 2 + index] = (record, name)
        fields[record + 0xC] = (record, 'владелец')
        fields[record + 0xD] = (record, 'владелец')
    return fields


class CollideWatch:
    def __init__(self) -> None:
        self.machine = None
        self.fields = watched_fields()
        self.in_list = False
        self.frame = 0
        self.writes: dict[str, dict] = {}
        self.scan_calls: dict[str, list[int]] = {}
        self.samples: list[dict] = []
        self.list_passes = 0
        self.live_shots: dict[int, list[int]] = {}
        self.reject: dict[int, dict[str, int]] = {}
        self.group_reject: dict[int, dict[str, list[int]]] = {}

    def install(self, machine) -> None:
        """Ловушки на экземпляр эталонной машины (новая машина — новые ловушки)."""
        if machine is self.machine:
            return
        from unicorn.unicorn_const import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
        self.machine = machine
        self.in_list = False
        cpu = machine.cpu
        cpu.hook_add(UC_HOOK_CODE, self._list_start, None, LOOP_B_START, LOOP_B_START)
        cpu.hook_add(UC_HOOK_CODE, self._list_end, None, LOOP_B_END, LOOP_B_END)
        for address in SCANS:
            cpu.hook_add(UC_HOOK_CODE, self._scan, SCANS[address], address, address)
        cpu.hook_add(UC_HOOK_MEM_WRITE, self._write, None, 0x40040, 0x4051F)

    def _list_start(self, uc, address, size, data) -> None:
        self.in_list = True
        self.list_passes += 1

    def _list_end(self, uc, address, size, data) -> None:
        self.in_list = False

    def _scan(self, uc, address, size, name) -> None:
        counts = self.scan_calls.setdefault(name, [0, 0])
        counts[0 if self.in_list else 1] += 1
        if name in ('$F6DA', '$F75F', '$F694') and self.in_list:
            self._chain_reject(uc, name)
        if name == '$F560' and self.in_list:
            # Живые записи снарядов при вызове скана (флаг [si+1] ≠ 0) — по этапу ([2FCD]): гистограмма числа.
            block = uc.mem_read(0x40176, 0x300)
            live = sum(1 for k in range(24) if block[0x20 * k + 1])
            stage = uc.mem_read(0x42FCD, 1)[0]
            histogram = self.live_shots.setdefault(stage, [0] * 25)
            histogram[live] += 1

    def _chain_reject(self, uc, name) -> None:
        """Оценка быстрого отказа всей цепочки урона: объект целиком правее (X и XR не меньше наибольшего края X записей)
        или левее (X и XL меньше наименьшего X1) всех записей, которые цепочка может проверить (флаги — на этот вызов)."""
        from unicorn.x86_const import UC_X86_REG_BP, UC_X86_REG_DI, UC_X86_REG_ES
        bp = uc.reg_read(UC_X86_REG_BP)
        di = uc.reg_read(UC_X86_REG_DI)
        es = uc.reg_read(UC_X86_REG_ES)
        work = uc.mem_read(0x40000, 0x600)
        word = lambda offset: work[offset] | (work[offset + 1] << 8)
        x = int.from_bytes(uc.mem_read(0x40000 + (bp + 4 & 0xFFFF), 2), 'little')   # объект — где угодно в рабочем ОЗУ
        hitbox = uc.mem_read(((es << 4) + di) & 0xFFFFF, 4)
        xr = (x + (hitbox[0] | (hitbox[1] << 8))) & 0xFFFF
        xl = (x + (hitbox[2] | (hitbox[3] << 8))) & 0xFFFF
        # Отказ по отдельным группам записей (сканы $F485, $F493, $F4AA, лучи $F4BF): объект правее всех записей группы.
        groups = {'R-9 #56': [0x56] if work[0x57] == 0 else [], 'Force и биты #76/#136/#156': [0x76, 0x136, 0x156],
                  '#F6/#116': [0xF6, 0x116], 'лучи #A8/#C8': [0xA8, 0xC8], 'игрок (все три скана)': (
                      ([0x56] if work[0x57] == 0 else []) + [0x76, 0x136, 0x156, 0xF6, 0x116])}
        stage_groups = self.group_reject.setdefault(uc.mem_read(0x42FCD, 1)[0], {})
        for group, pool in groups.items():
            entry = stage_groups.setdefault(group, [0, 0])
            if not pool:
                continue
            entry[0] += 1
            maxx = max(max(word(r + 2), word(r + 4)) for r in pool)
            if x >= maxx and xr >= maxx:
                entry[1] += 1
        records = [0x76, 0x136, 0x156, 0xF6, 0x116]
        if work[0x57] == 0:
            records.append(0x56)
        records += [r for r in [0xB6, 0xD6, 0x4D6, 0x4F6, 0x516] + [0x176 + 0x20 * k for k in range(24)] if work[r + 1]]
        beams = [0xA8, 0xC8]
        stage = uc.mem_read(0x42FCD, 1)[0]
        stats = self.reject.setdefault(stage, {'calls': 0, 'right': 0, 'left': 0, 'right_nobeam': 0, 'left_nobeam': 0})
        stats['calls'] += 1
        for key, pool in (('', records + beams), ('_nobeam', records)):
            maxx = max(max(word(r + 2), word(r + 4)) for r in pool)
            minx1 = min(word(r + 2) for r in pool)
            if x >= maxx and xr >= maxx:
                stats['right' + key] += 1
            elif x < minx1 and xl < minx1:
                stats['left' + key] += 1

    def _write(self, uc, access, address, size, value, data) -> None:
        if not self.in_list:
            return
        offset = address - 0x40000
        hit = [self.fields[byte] for byte in range(offset, offset + size) if byte in self.fields]
        if not hit:
            return
        from unicorn.x86_const import UC_X86_REG_BP, UC_X86_REG_CS, UC_X86_REG_IP
        ip = uc.reg_read(UC_X86_REG_IP)
        linear = ((uc.reg_read(UC_X86_REG_CS) << 4) + ip) & 0xFFFFF
        bp = uc.reg_read(UC_X86_REG_BP)
        handler = int.from_bytes(uc.mem_read(0x40000 + bp, 2), 'little') if bp < 0x3FFE else -1
        key = f'{linear:05X}'
        entry = self.writes.setdefault(key, {'ip': f'${ip:04X}', 'count': 0, 'fields': {}, 'handlers': {},
                                             'transitions': {}})
        entry['count'] += 1
        # Переходы флагов (ловушка — до записи: в памяти ещё прежнее значение): 0 → не 0 — включение записи.
        old = uc.mem_read(address, size)
        for index in range(size):
            field = self.fields.get(offset + index)
            if field is None or field[1] != 'флаг':
                continue
            before, after = old[index], (value >> (8 * index)) & 0xFF
            kind = ('включение' if before == 0 and after else 'гашение' if before and not after else
                    'изменение' if before != after else 'то же')
            name = f'#{field[0]:03X}:{kind}'
            entry['transitions'][name] = entry['transitions'].get(name, 0) + 1
        for record, field in hit:
            name = f'#{record:03X}:{field}'
            entry['fields'][name] = entry['fields'].get(name, 0) + 1
        handler_key = f'${handler:04X}' if handler >= 0 else '?'
        entry['handlers'][handler_key] = entry['handlers'].get(handler_key, 0) + 1
        if len(self.samples) < 400 and entry['count'] <= 3:
            self.samples.append({'frame': self.frame, 'ip': f'${ip:04X}', 'address': f'#{offset:04X}', 'size': size,
                                 'value': value, 'bp': f'#{bp:04X}', 'handler': handler_key})

    def report(self, path: str) -> None:
        data = {'list_passes': self.list_passes, 'scan_calls': self.scan_calls, 'writes': self.writes,
                'samples': self.samples, 'live_shots': self.live_shots}
        for stage, stats in sorted(self.reject.items()):
            calls = stats['calls'] or 1
            print(f'этап {stage}: цепочек урона в цикле {stats["calls"]}; быстрый отказ справа {stats["right"] * 100 / calls:.0f} %, '
                  f'слева {stats["left"] * 100 / calls:.0f} % (без лучей #A8/#C8 — {stats["right_nobeam"] * 100 / calls:.0f} % '
                  f'и {stats["left_nobeam"] * 100 / calls:.0f} %)')
        for stage, groups in sorted(self.group_reject.items()):
            print(f'этап {stage}: отказ справа по группам — ' + ', '.join(
                f'{name} {hits * 100 / calls:.0f} %' for name, (calls, hits) in groups.items() if calls))
        for stage, histogram in sorted(self.live_shots.items()):
            calls = sum(histogram)
            mean = sum(count * live for live, count in enumerate(histogram)) / calls if calls else 0
            print(f'этап {stage}: вызовов $F560 в цикле {calls}, живых записей снарядов в среднем {mean:.1f}; '
                  f'распределение ' + ' '.join(f'{live}:{count}' for live, count in enumerate(histogram) if count))
        Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
        print(f'записи столкновений: проходов цикла списка {self.list_passes}; вызовы сканов (в цикле / вне) ' +
              ', '.join(f'{name} {counts[0]}/{counts[1]}' for name, counts in sorted(self.scan_calls.items())))
        for key, entry in sorted(self.writes.items(), key=lambda item: -item[1]['count']):
            fields = ', '.join(f'{name} {count}' for name, count in sorted(entry['fields'].items(),
                                                                          key=lambda item: -item[1])[:6])
            handlers = ', '.join(f'{name} {count}' for name, count in sorted(entry['handlers'].items(),
                                                                            key=lambda item: -item[1])[:6])
            kinds = {}
            for name, count in entry.get('transitions', {}).items():
                kind = name.split(':', 1)[1]
                kinds[kind] = kinds.get(kind, 0) + count
            transitions = ', '.join(f'{kind} {count}' for kind, count in sorted(kinds.items()))
            print(f'  {key} (IP {entry["ip"]}): {entry["count"]} записей; поля {fields}; обработчики {handlers}' +
                  (f'; флаги: {transitions}' if transitions else ''))
