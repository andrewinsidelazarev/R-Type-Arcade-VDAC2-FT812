"""Оригиналы эффектов R-Type в Audio/Original: вырезка из детерминированного скана MAME без обработки.

Скан Build/Arcade/Audio/scan (запись MAME 0.288 по одной звуковой команде, WAV 48 кГц 16 бит моно и
catalog.json с началом и длительностью звучания) — производное дерево сборки. Оригиналы, из которых делаются
сэмплы General Sound (rtype_gs.py) и которые играет эталон (rtype_port.audio.GeneralSound), хранятся в
Audio/Original:
  * rtype_sfx_XX.wav — звучащая часть команды $XX, отсчёты скана без изменений;
  * rtype_sfx.json — для каждой команды: исходный файл скана, его SHA-256, смещение и длина вырезки в отсчётах,
    пик и скз (как в каталоге скана), SHA-256 вырезки.
Берутся только команды, которые World ROM отправляет звуковому Z80 (rtype_gs.ROM_COMMANDS), кроме команд
остановки (у них нет своего звука).

Запускается один раз (или после пересъёмки скана); в обычную сборку не входит.
"""
from __future__ import annotations

import hashlib
import json
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'Source' / 'Tools'))
sys.path.insert(0, str(ROOT / 'Build' / 'PythonDeps'))

import numpy as np                                                  # noqa: E402

import rtype_gs                                                     # noqa: E402

SCAN = ROOT / 'Build' / 'Arcade' / 'Audio' / 'scan'
ORIGINAL = ROOT / 'Audio' / 'Original'


def main() -> int:
    sys.stdout.reconfigure(encoding='utf-8')
    catalog = json.loads((SCAN / 'catalog.json').read_text(encoding='utf-8'))['sounding']
    stops = rtype_gs.stop_targets()
    result = {}
    for command in rtype_gs.ROM_COMMANDS:
        key = f'0x{command:02X}'
        if command in stops:
            continue
        meta = catalog[key]
        source_path = SCAN / f'cmd_{command:02X}.wav'
        source_bytes = source_path.read_bytes()
        with wave.open(str(source_path), 'rb') as source:
            rate = source.getframerate()
            if source.getsampwidth() != 2 or source.getnchannels() != 1:
                raise SystemExit(f'{source_path.name}: нужен моно PCM S16')
            start = max(0, round(meta['start_seconds'] * rate))
            count = max(1, round(meta['duration_seconds'] * rate))
            source.setpos(min(start, source.getnframes()))
            frames = source.readframes(min(count, source.getnframes() - source.tell()))
        target = ORIGINAL / f'rtype_sfx_{command:02X}.wav'
        with wave.open(str(target), 'wb') as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(rate)
            out.writeframes(frames)
        samples = np.frombuffer(frames, dtype='<i2').astype(np.float64)
        result[key] = {
            'file': target.name,
            'rate': rate,
            'samples': len(samples),
            'start_seconds': 0.0,
            'duration_seconds': len(samples) / rate,
            'peak': float(np.max(np.abs(samples))),
            'rms': float(np.sqrt(np.mean(samples ** 2))),
            'sha256': hashlib.sha256(frames).hexdigest(),
            'source': {'file': f'Build/Arcade/Audio/scan/{source_path.name}',
                       'sha256': hashlib.sha256(source_bytes).hexdigest(),
                       'start_sample': start, 'samples': len(samples),
                       'catalog_peak': meta['peak']},
        }
        print(f'  ${command:02X}: {len(samples)} отсчётов, {len(samples) / rate:.3f} с → {target.name}')
    document = {
        'description': 'Оригиналы эффектов R-Type World: звучащие части записей MAME 0.288 по одной звуковой '
                       'команде (скан Build/Arcade/Audio/scan), без обработки. Команды — те, что шлёт ROM.',
        'sounding': result,
    }
    (ORIGINAL / 'rtype_sfx.json').write_text(json.dumps(document, ensure_ascii=False, indent=1) + '\n',
                                             encoding='utf-8')
    print(f'оригиналов: {len(result)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
