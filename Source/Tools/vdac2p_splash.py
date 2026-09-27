"""Экран загрузки релиза (VDAC2+, 2026-09-27): заставка 1024×768 в pseudo-DXT1 и шкала BEAM для FT812.

Заставка — картинка пользователя Assets/Screenshots/R-Type TS.png (пользователь перенёс её 27.09 в папку снимков для
статьи; решение пользователя: «картинку смасштабировать до 1024×768», «выводим в pseudo DXT»). Масштаб — офлайн (Pillow
Lanczos, 1448×1086 → 1024×768, пропорции 4:3 те же) — Assets/Converted/Splash/splash_1024x768.png.

Pseudo-DXT1 — сжатие DXT1, которое FT812 рисует без поддержки DXT: блок 4×4 пикселя хранит два цвета RGB565 (c0, c1)
и по пикселю номер k = 0…3 — цвет c0·(3 − k)/3 + c1·k/3 (как четыре цвета блока DXT1). На FT812 это четыре битмапа:
цвета c0 и c1 — RGB565 256×192 (по пикселю на блок, выводятся с увеличением 4 через BITMAP_TRANSFORM, NEAREST), номера —
две битовые плоскости L1 1024×768 (b0 = k & 1, b1 = k >> 1). Вывод в четыре прохода: в альфу кадра (COLOR_MASK только
альфа, BLEND_FUNC ONE, ONE) — b0 с COLOR_A 85 и b1 с COLOR_A 170, альфа = 85·k; затем цвет (COLOR_MASK без альфы):
c1 с BLEND_FUNC(DST_ALPHA, ZERO), c0 с BLEND_FUNC(ONE_MINUS_DST_ALPHA, ONE) — итог c1·a + c0·(1 − a). Четыре бита на
пиксель: 384 КБ RAM_G вместо 1,5 МБ RGB565. Кодер: по блоку — главная ось цветов, концы по проекциям, затем два
уточнения концов наименьшими квадратами при найденных номерах (цвета квантованы в RGB565 до выбора номеров).

Шкала BEAM — Assets/Converted/Splash/beam_empty.png и beam_full.png (vdac2p_beam_capture.py, из кадров эталона) →
ARGB1555.

Результат — Build/V30Z80/splash: плоскости b0, b1, c0, c1 (*.bin, по 96 КБ) и шкалы (beam.bin, 48 КБ: пустая с
начала, полная — с #6000) — содержимое страниц-носителей SPG, которые загрузчик SPG отдаёт в RAM_G через DMA подряд с
адреса 0 (rtype_spg.py, rtype_boot.asm); splash.inc (адреса RAM_G, размеры шкалы), splash.json (размеры, сжатие zlib
для сравнения, PSNR); предпросмотр раскодированной заставки (та же арифметика, что у четырёх проходов FT812) —
Assets/Converted/Splash/splash_dxt_preview.png.
"""
from __future__ import annotations

import json
import zlib
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'Assets' / 'Screenshots' / 'R-Type TS.png'
CONVERTED = ROOT / 'Assets' / 'Converted' / 'Splash'
OUT = ROOT / 'Build' / 'V30Z80' / 'splash'
WIDTH, HEIGHT = 1024, 768
BLOCKS_X, BLOCKS_Y = WIDTH // 4, HEIGHT // 4
# RAM_G на время загрузки (игра потом переписывает всё своим): плоскости заставки и две шкалы.
RAM_B0 = 0x000000
RAM_B1 = 0x018000
RAM_C0 = 0x030000
RAM_C1 = 0x048000
RAM_BEAM_EMPTY = 0x060000
RAM_BEAM_FULL = 0x066000


def rgb565(colors: np.ndarray) -> np.ndarray:
    """Цвета (…, 3) 0…255 → RGB565 (округление к ближайшему)."""
    r = np.clip(np.rint(colors[..., 0] * 31 / 255), 0, 31).astype(np.uint16)
    g = np.clip(np.rint(colors[..., 1] * 63 / 255), 0, 63).astype(np.uint16)
    b = np.clip(np.rint(colors[..., 2] * 31 / 255), 0, 31).astype(np.uint16)
    return (r << 11) | (g << 5) | b


def expand565(value: np.ndarray) -> np.ndarray:
    """RGB565 → цвета 0…255 (повтор старших битов, как расширяет FT812)."""
    r = (value >> 11) & 31
    g = (value >> 5) & 63
    b = value & 31
    return np.stack([(r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)], axis=-1).astype(np.float64)


def palette(c0: np.ndarray, c1: np.ndarray) -> np.ndarray:
    """Четыре цвета блока (N, 4, 3): k = 0…3 — c0·(3 − k)/3 + c1·k/3 (альфа 85·k из 255)."""
    alpha = np.array([0, 85, 170, 255], dtype=np.float64) / 255
    return c0[:, None, :] * (1 - alpha[None, :, None]) + c1[:, None, :] * alpha[None, :, None]


def encode(image: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Картинка (768, 1024, 3) → c0, c1 (192·256, RGB565), номера (192·256, 16) k = 0…3."""
    blocks = image.reshape(BLOCKS_Y, 4, BLOCKS_X, 4, 3).transpose(0, 2, 1, 3, 4).reshape(-1, 16, 3)
    mean = blocks.mean(axis=1)
    centered = blocks - mean[:, None, :]
    covariance = np.einsum('nki,nkj->nij', centered, centered)
    axis = np.tile(np.array([0.577, 0.577, 0.577]), (len(blocks), 1))
    for _ in range(12):                                         # главная ось — степенной итерацией
        axis = np.einsum('nij,nj->ni', covariance, axis)
        norm = np.linalg.norm(axis, axis=1, keepdims=True)
        axis = np.where(norm > 1e-9, axis / np.maximum(norm, 1e-9), np.array([0.577, 0.577, 0.577]))
    projection = np.einsum('nki,ni->nk', centered, axis)
    e0 = np.clip(mean + projection.min(axis=1, keepdims=True) * axis, 0, 255)
    e1 = np.clip(mean + projection.max(axis=1, keepdims=True) * axis, 0, 255)
    for _ in range(3):
        q0, q1 = rgb565(e0), rgb565(e1)
        colors = palette(expand565(q0), expand565(q1))
        error = ((blocks[:, :, None, :] - colors[:, None, :, :]) ** 2).sum(axis=3)
        index = error.argmin(axis=2)
        # Уточнение концов при найденных номерах: наименьшие квадраты x ≈ (1 − α)·c0 + α·c1.
        alpha = index / 3.0
        a00 = ((1 - alpha) ** 2).sum(axis=1)
        a01 = ((1 - alpha) * alpha).sum(axis=1)
        a11 = (alpha ** 2).sum(axis=1)
        b0 = np.einsum('nk,nki->ni', 1 - alpha, blocks)
        b1 = np.einsum('nk,nki->ni', alpha, blocks)
        det = a00 * a11 - a01 * a01
        solvable = det > 1e-6
        safe = np.where(solvable, det, 1.0)
        n0 = (b0 * a11[:, None] - b1 * a01[:, None]) / safe[:, None]
        n1 = (b1 * a00[:, None] - b0 * a01[:, None]) / safe[:, None]
        e0 = np.where(solvable[:, None], np.clip(n0, 0, 255), e0)
        e1 = np.where(solvable[:, None], np.clip(n1, 0, 255), e1)
    q0, q1 = rgb565(e0), rgb565(e1)
    colors = palette(expand565(q0), expand565(q1))
    error = ((blocks[:, :, None, :] - colors[:, None, :, :]) ** 2).sum(axis=3)
    index = error.argmin(axis=2)
    return q0, q1, index.astype(np.uint8)


def decode(q0: np.ndarray, q1: np.ndarray, index: np.ndarray) -> np.ndarray:
    """Раскодирование — как четыре прохода FT812: альфа 85·k, итог c1·a + c0·(1 − a)."""
    colors = palette(expand565(q0), expand565(q1))
    pixels = np.take_along_axis(colors, index[:, :, None].astype(np.int64), axis=1)
    return pixels.reshape(BLOCKS_Y, BLOCKS_X, 4, 4, 3).transpose(0, 2, 1, 3, 4).reshape(HEIGHT, WIDTH, 3)


def argb1555(path: Path) -> tuple[bytes, int, int]:
    """PNG RGBA → ARGB1555 (прозрачность — старший бит), младший байт первым."""
    image = np.asarray(Image.open(path).convert('RGBA')).astype(np.uint16)
    value = ((image[..., 3] >= 128).astype(np.uint16) << 15) | ((image[..., 0] >> 3) << 10) | \
            ((image[..., 1] >> 3) << 5) | (image[..., 2] >> 3)
    return value.astype('<u2').tobytes(), image.shape[1], image.shape[0]


def main() -> int:
    CONVERTED.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    scaled = Image.open(SOURCE).convert('RGB').resize((WIDTH, HEIGHT), Image.LANCZOS)
    scaled.save(CONVERTED / 'splash_1024x768.png')
    image = np.asarray(scaled).astype(np.float64)
    q0, q1, index = encode(image)
    preview = decode(q0, q1, index)
    Image.fromarray(np.clip(np.rint(preview), 0, 255).astype(np.uint8)).save(CONVERTED / 'splash_dxt_preview.png')
    psnr = 10 * np.log10(255 ** 2 / ((preview - image) ** 2).mean())
    # Плоскости: номера блока 4×4 → пиксели 1024×768; бит 7 байта L1 — левый пиксель.
    pixels = index.reshape(BLOCKS_Y, BLOCKS_X, 4, 4).transpose(0, 2, 1, 3).reshape(HEIGHT, WIDTH)
    planes = {
        'b0': np.packbits((pixels & 1).astype(np.uint8), axis=1, bitorder='big').tobytes(),
        'b1': np.packbits((pixels >> 1).astype(np.uint8), axis=1, bitorder='big').tobytes(),
        'c0': q0.reshape(BLOCKS_Y, BLOCKS_X).astype('<u2').tobytes(),
        'c1': q1.reshape(BLOCKS_Y, BLOCKS_X).astype('<u2').tobytes(),
    }
    beam_empty, beam_w, beam_h = argb1555(CONVERTED / 'beam_empty.png')
    beam_full, _, _ = argb1555(CONVERTED / 'beam_full.png')
    planes['beam_empty'] = beam_empty
    planes['beam_full'] = beam_full
    sizes = {}
    for name, data in planes.items():
        sizes[name] = [len(data), len(zlib.compress(data, 9))]
    assert len(planes['b0']) == RAM_B1 - RAM_B0 and len(planes['c1']) == RAM_BEAM_EMPTY - RAM_C1
    assert len(beam_empty) <= RAM_BEAM_FULL - RAM_BEAM_EMPTY
    for name in ('b0', 'b1', 'c0', 'c1'):
        (OUT / f'{name}.bin').write_bytes(planes[name])
    # Шкалы — три страницы-носителя подряд за плоскостями: RAM_G #060000 (пустая) и #066000 (полная).
    beam = bytearray(0xC000)
    beam[0:len(beam_empty)] = beam_empty
    beam[RAM_BEAM_FULL - RAM_BEAM_EMPTY:RAM_BEAM_FULL - RAM_BEAM_EMPTY + len(beam_full)] = beam_full
    (OUT / 'beam.bin').write_bytes(bytes(beam))
    lines = ['; Сгенерировано vdac2p_splash.py: экран загрузки — заставка pseudo-DXT1 и шкала BEAM (RAM_G на время загрузки).',
             f'SPLASH_B0        EQU #{RAM_B0:06X}', f'SPLASH_B1        EQU #{RAM_B1:06X}',
             f'SPLASH_C0        EQU #{RAM_C0:06X}', f'SPLASH_C1        EQU #{RAM_C1:06X}',
             f'SPLASH_BEAM_EMPTY EQU #{RAM_BEAM_EMPTY:06X}', f'SPLASH_BEAM_FULL EQU #{RAM_BEAM_FULL:06X}',
             f'SPLASH_BEAM_W    EQU {beam_w}', f'SPLASH_BEAM_H    EQU {beam_h}', '']
    (OUT / 'splash.inc').write_text('\n'.join(lines), encoding='utf-8', newline='\n')
    report = {'psnr': round(float(psnr), 2), 'sizes': sizes, 'beam': [beam_w, beam_h],
              'raw_total': sum(raw for raw, _ in sizes.values()),
              'packed_total': sum(packed for _, packed in sizes.values())}
    (OUT / 'splash.json').write_text(json.dumps(report, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(f'заставка pseudo-DXT1: PSNR {psnr:.2f} дБ, байт {report["raw_total"]} (zlib дал бы {report["packed_total"]})')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
