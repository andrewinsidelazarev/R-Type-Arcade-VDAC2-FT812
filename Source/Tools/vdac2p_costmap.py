"""Карта цены VDAC2+: профиль rtype_check --ticks (выборки PC по меткам) → процедуры ROM.

Метка A_xxxxx переведённого кода — одна инструкция V30 (линейный адрес). Инструкция относится к
функциям-владельцам (functions.build транслятора); общая для нескольких функций делится поровну.
Печатает долю перевода, рантайма, ядер и хоста и топ процедур ROM по цене перевода — очередь нативной
переписи VDAC2+ (сначала то, что дороже).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'Source' / 'Tools'))

import v30z80_build as vb  # noqa: E402
from v30z80 import functions  # noqa: E402
from v30z80.discover import discover  # noqa: E402


def load_function_map(with_flags: bool = False):
    state = vb.boot_state(False)
    program = discover(state.memory, vb.BUILD / 'trace.json', list(vb.IDLE_POINTS), state.pic[0],
                       vb.snapshot.patch_second_bytes(), ROOT / 'Build' / 'Analysis' / 'rtype_world_rom_complete.json')
    start = next(iter(vb.IDLE_POINTS))
    vectors = vb.vector_targets(state.memory, state.pic[0])
    fmap = functions.build(program, {start} | set(vectors))
    if not with_flags:
        return program, fmap
    # Живые флаги после инструкций — как у сборки (segments.Analysis + flags.liveness).
    from v30z80 import flags, segments
    start_segments = tuple(state.registers[name] for name in vb.snapshot.SEGMENTS)
    analysis = segments.Analysis(program, fmap, {start: start_segments})
    analysis.run()
    live = flags.liveness(program, set(vb.IDLE_POINTS), fmap, analysis)
    return program, fmap, live


def categories() -> dict[str, str]:
    result = {}
    for name, tag in (('v30z80_runtime.asm', 'рантайм'), ('v30z80_flags.inc', 'рантайм'),
                      ('v30z80_kernels.asm', 'ядра'), ('v30z80_ring.asm', 'кольцо'),
                      ('v30z80_host.asm', 'хост'), ('v30z80_sound.asm', 'звук'), ('vdac2p_native.asm', 'натив')):
        text = (ROOT / 'Source' / 'ASM' / name).read_text(encoding='utf-8')
        for label in re.findall(r'^([A-Za-z_][\w]*):', text, re.M):
            result.setdefault(label, tag)
    return result


def main() -> int:
    sys.stdout.reconfigure(encoding='utf-8')
    paths = [Path(item) for item in sys.argv[1:]]
    program, fmap = load_function_map()
    tags = categories()
    for path in paths:
        profile = json.loads(path.read_text(encoding='utf-8'))['profile']
        total = sum(profile.values())
        per_function: dict[int, float] = {}
        unowned = 0
        for label, ticks in profile.items():
            if not label.startswith('A_'):
                continue
            address = int(label[2:], 16)
            owners = fmap.owners.get(address)
            if not owners:
                unowned += ticks
                continue
            share = ticks / len(owners)
            for entry in owners:
                per_function[entry] = per_function.get(entry, 0) + share
        groups: dict[str, int] = {}
        for label, ticks in profile.items():
            tag = 'перевод' if label.startswith('A_') else tags.get(label, 'оболочка/прочее')
            groups[tag] = groups.get(tag, 0) + ticks
        print(f'== {path.name}')
        print('  ' + ', '.join(f'{tag} {ticks * 100 / total:.1f} %' for tag, ticks in
                                sorted(groups.items(), key=lambda kv: -kv[1])))
        ranked = sorted(per_function.items(), key=lambda kv: -kv[1])
        translated = sum(per_function.values()) + unowned
        cumulative = 0.0
        print(f'  процедур с ценой: {len(ranked)}; без владельца {unowned * 100 / total:.2f} %')
        for index, (entry, ticks) in enumerate(ranked[:60]):
            cumulative += ticks
            body = len(fmap.bodies.get(entry, ()))
            print(f'  {index + 1:3} ${entry:05X} (IP ${entry - 0x400:04X}) {ticks * 100 / total:5.2f} %  '
                  f'инструкций {body:4}  накоплено {cumulative * 100 / translated:5.1f} % перевода')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
