"""Скорость сборки VDAC2+ против опорной: средние такты модели на кадр (шаг машины и вывод каждый кадр — модель сверки
пропусков вывода не делает) по участкам этапа 1 (кадры 400…8800) и этапа 2 (8900…) сценария автоогня.
Аргументы: JSON тактов проверяемой сборки (rtype_check --ticks) [опорный JSON, по умолчанию Baselines/v013_ticks_14000.json]."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    sys.stdout.reconfigure(encoding='utf-8')
    ours = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))['ticks']
    base_path = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / 'Baselines' / 'v013_ticks_14000.json'
    base = json.loads(base_path.read_text(encoding='utf-8'))['ticks']
    for name, first, last in (('этап 1', 400, 8800), ('этап 2', 8900, 14000)):
        last = min(last, len(ours), len(base))
        if last <= first:
            continue
        a = sum(ours[first:last]) / (last - first)
        b = sum(base[first:last]) / (last - first)
        print(f'{name} (кадры {first}…{last}): {a:,.0f} тактов на кадр против {b:,.0f} — {(a - b) * 100 / b:+.2f} %'
              .replace(',', ' '))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
