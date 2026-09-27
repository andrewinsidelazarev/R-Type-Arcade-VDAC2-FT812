"""Шкала BEAM для экрана загрузки (VDAC2+, 2026-09-27): пустая и полная шкала панели из кадров эталона.

Источник — снимки пошаговой сверки rtype_check.py (`--png`: слева наш вывод, справа эталон M72HqRenderer — тайлы ROM
через офлайн-апскейл проекта), кадры игры, где заряд BEAM пуст и где полон:

    sh Source/Tools/vdac2p_wide.sh 780 beam --invincible --keys "330:331:space,600:780:space" --no-tsfm-check \
        --render 599,780 --png Build/png_beam

(огонь держится с кадра 600 — к кадру 780 шкала полна). Из правой половины (эталон) вырезается шкала без надписи BEAM:
x 339…707, y 720…745 физических пикселей 1024×768. Прозрачность: всё, что внутри контура шкалы (по строкам — от
первого до последнего непустого пикселя полной шкалы), непрозрачно — пустая шкала внутри чёрная, как в игре; снаружи —
прозрачно (под шкалой видна заставка). Результат — Assets/Converted/Splash/beam_empty.png и beam_full.png (RGBA).
Запуск: vdac2p_beam_capture.py [каталог снимков] (по умолчанию Build/png_beam).
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'Assets' / 'Converted' / 'Splash'
EMPTY_FRAME, FULL_FRAME = 599, 780
X0, X1, Y0, Y1 = 339, 708, 720, 746          # шкала без надписи BEAM


def reference(folder: Path, frame: int) -> np.ndarray:
    """Кадр эталона (правая половина снимка сверки)."""
    image = np.asarray(Image.open(folder / f'rtype_{frame:05d}_game.png').convert('RGB'))
    return image[:, 1024:]


def main() -> int:
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'Build' / 'png_beam'
    empty = reference(folder, EMPTY_FRAME)[Y0:Y1, X0:X1]
    full = reference(folder, FULL_FRAME)[Y0:Y1, X0:X1]
    # Контур шкалы — по полной: непустые пиксели, внутри строки — от первого до последнего.
    solid = full.astype(int).sum(axis=2) > 24
    mask = np.zeros(solid.shape, dtype=bool)
    for row in range(solid.shape[0]):
        columns = np.nonzero(solid[row])[0]
        if len(columns):
            mask[row, columns[0]:columns[-1] + 1] = True
    # Рамка у пустой и полной одна и та же — различаться может только середина.
    border = np.abs(empty.astype(int) - full.astype(int)).sum(axis=2) > 0
    outside = ~mask & border
    if outside.any():
        raise SystemExit(f'пустая и полная шкала различаются вне контура: {int(outside.sum())} пикселей')
    OUT.mkdir(parents=True, exist_ok=True)
    for name, image in (('beam_empty.png', empty), ('beam_full.png', full)):
        rgba = np.dstack([image, (mask * 255).astype(np.uint8)])
        Image.fromarray(rgba, 'RGBA').save(OUT / name)
    print(f'шкала BEAM: {X1 - X0}×{Y1 - Y0}, непрозрачных {int(mask.sum())} → {OUT}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
