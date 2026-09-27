"""Затыки подгрузки по трассам модели реального времени (vdac2p_realtime.py … trace): сравнение двух сборок.

Трасса — строки «кадр N: тактов T, показано S, время …, SD R, DMA B». Печатает для каждой трассы: распределение
длительности шага игры (мс), промежутки между показанными кадрами (то, что видит глаз), шаги с чтениями SD и цену
одного прочитанного сектора — наклон длительности шага по числу чтений (наименьшие квадраты).
Запуск: vdac2p_hitches.py трасса_до трасса_после [подписи через запятую].
"""
from __future__ import annotations

import re
import statistics
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
TICKS_PER_MS = 14_000
LINE = re.compile(r'^кадр (\d+): тактов (\d+), показано (\d+), .*SD (\d+), DMA (\d+)')


def load(path: Path) -> list[tuple[int, int, int, int]]:
    rows = []
    for line in path.read_text(encoding='utf-8').splitlines():
        match = LINE.match(line)
        if match:
            rows.append(tuple(int(value) for value in match.groups()[:4]))
    return rows


def percentile(values: list[float], share: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * share))]


def report(name: str, rows: list[tuple[int, int, int, int]]) -> dict:
    steps = [ticks / TICKS_PER_MS for _, ticks, _, _ in rows]
    intervals = []                        # мс между показанными кадрами
    pending = 0.0
    for _, ticks, shown, _ in rows:
        pending += ticks / TICKS_PER_MS
        if shown:
            intervals.append(pending)
            pending = 0.0
    with_sd = [(reads, ticks / TICKS_PER_MS) for _, ticks, _, reads in rows if reads]
    without_sd = [ticks / TICKS_PER_MS for _, ticks, _, reads in rows if not reads]
    reads_total = sum(reads for _, _, _, reads in rows)
    # Цена сектора: наклон длительности шага по числу чтений среди шагов с показом (подгрузка идёт при выводе).
    shown_rows = [(reads, ticks / TICKS_PER_MS) for _, ticks, shown, reads in rows if shown]
    mean_x = statistics.fmean(x for x, _ in shown_rows)
    mean_y = statistics.fmean(y for _, y in shown_rows)
    slope = (sum((x - mean_x) * (y - mean_y) for x, y in shown_rows) /
             max(1e-9, sum((x - mean_x) ** 2 for x, _ in shown_rows)))
    print(f'== {name}: шагов {len(rows)}, время {sum(steps) / 1000:.1f} с')
    print(f'  шаг: медиана {statistics.median(steps):.1f} мс, 99 % {percentile(steps, 0.99):.1f}, '
          f'99,9 % {percentile(steps, 0.999):.1f}, худший {max(steps):.1f}')
    print(f'  между показами: медиана {statistics.median(intervals):.1f} мс, 99 % {percentile(intervals, 0.99):.1f}, '
          f'99,9 % {percentile(intervals, 0.999):.1f}, худший {max(intervals):.1f}; '
          f'дольше 100 мс — {sum(1 for value in intervals if value > 100)}, дольше 150 мс — '
          f'{sum(1 for value in intervals if value > 150)}')
    print(f'  чтений SD {reads_total}, шагов с чтениями {len(with_sd)}: средний шаг {statistics.fmean(y for _, y in with_sd):.1f} мс '
          f'против {statistics.fmean(without_sd):.1f} без чтений; цена сектора (наклон) {slope:.2f} мс')
    heavy = sorted(with_sd, key=lambda item: -item[1])[:5]
    print('  тяжелейшие шаги с чтениями: ' + ', '.join(f'{reads} сект. — {ms:.0f} мс' for reads, ms in heavy))
    return {'steps': steps, 'intervals': intervals, 'slope': slope}


def main() -> int:
    paths = [Path(sys.argv[1]), Path(sys.argv[2])]
    names = sys.argv[3].split(',') if len(sys.argv) > 3 else ['до', 'после']
    results = [report(name, load(path)) for name, path in zip(names, paths)]
    before, after = results
    print(f'итог: время шагов {sum(before["steps"]) / 1000:.1f} → {sum(after["steps"]) / 1000:.1f} с; '
          f'цена сектора {before["slope"]:.2f} → {after["slope"]:.2f} мс; худший промежуток между показами '
          f'{max(before["intervals"]):.0f} → {max(after["intervals"]):.0f} мс')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
