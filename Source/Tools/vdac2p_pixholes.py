"""Сверка картинкой кадров с пропусками вывода: дыры против швов (VDAC2+, 2026-09-27).

Модель реального времени с RT_DRAWN находит показанные кадры, чей хеш «нарисованное» расходится с опорным
(rtype_check --drawn); RT_PIXELS_PNG сохраняет их отрисовку моделью FT812, прогон noskip с RT_PIXELS_FRAMES — те же
кадры без пропусков. Допустимые расхождения — швы: класс строки ушёл полосами вместо картинки (сроки выделения в пуле
картинок при пропусках иные) и многоклеточный спрайт выведен ячейками вместо объекта — линии в пиксель по краям тайлов
и ячеек. Пропавший или чужой кусок (дыра, под ним фон) — сплошное пятно.

Пиксель «объяснён», если его цвет в одной картинке есть в окрестности 3×3 того же места другой картинки; блок 16×16,
где необъяснённых не меньше 3/4, — сплошной. Блок 8×8 (--block 8) ловит куски мельче, но и швы объекта против ячеек у
мелко прорисованных спрайтов (другой шаг текселей — цвет из соседнего тексела дальше пикселя): такие кадры смотреть
глазами. Запуск: vdac2p_pixholes.py [--block 8] каталог_noskip каталог_с_пропусками […]. По каждому каталогу: сколько
кадров совпало пиксель в пиксель, сколько различается, кадры со сплошными блоками — число блоков и рамка (физические
пиксели 1024×768). Код выхода 1 — есть сплошные блоки.
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

BLOCK = 16                  # сторона блока, пикселей (--block)


def packed(path: Path) -> np.ndarray:
    """Картинка — числа RGB (24 бита) на пиксель."""
    image = np.asarray(Image.open(path).convert('RGB')).astype(np.int32)
    return (image[:, :, 0] << 16) | (image[:, :, 1] << 8) | image[:, :, 2]


def explained(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Маска пикселей b, цвет которых есть в a в окрестности 3×3."""
    pad = np.pad(a, 1, mode='edge')
    height, width = b.shape
    mask = np.zeros(b.shape, dtype=bool)
    for dy in (0, 1, 2):
        for dx in (0, 1, 2):
            mask |= pad[dy:dy + height, dx:dx + width] == b
    return mask


def main() -> int:
    args = sys.argv[1:]
    block = BLOCK
    if args[:1] == ['--block']:
        block = int(args[1])
        args = args[2:]
    solid_limit = block * block * 3 // 4
    base = Path(args[0])
    holes_total = 0
    for folder in map(Path, args[1:]):
        same = other = unpaired = 0
        holes = []
        for png in sorted(folder.glob('frame_*.png')):
            ref = base / png.name
            if not ref.is_file():
                unpaired += 1
                continue
            a, b = packed(ref), packed(png)
            if (a == b).all():
                same += 1
                continue
            other += 1
            bad = (~explained(a, b) | ~explained(b, a)).astype(np.int32)
            height, width = bad.shape
            blocks = bad.reshape(height // block, block, width // block, block).sum(axis=(1, 3))
            solid = np.argwhere(blocks >= solid_limit)
            if len(solid):
                ys, xs = solid[:, 0] * block, solid[:, 1] * block
                holes.append((int(png.stem.split('_')[1]), len(solid),
                              (int(xs.min()), int(xs.max()) + block, int(ys.min()), int(ys.max()) + block)))
        print(f'{folder.name}: пиксель в пиксель {same}, иных {other}, без пары {unpaired}, со сплошными блоками '
              f'{len(holes)}')
        for frame, count, box in holes:
            print(f'   кадр {frame}: блоков {count}, рамка x {box[0]}…{box[1]}, y {box[2]}…{box[3]}')
        holes_total += len(holes)
    return 1 if holes_total else 0


if __name__ == '__main__':
    sys.exit(main())
