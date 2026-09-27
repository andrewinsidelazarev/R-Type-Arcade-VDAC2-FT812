"""Места вызова процедуры ROM с живыми флагами после возврата: какие вызывающие действительно читают флаги.
Аргументы: входы (линейный hex или ipXXXX)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'Source' / 'Tools'))
from vdac2p_costmap import load_function_map  # noqa: E402

NAMES = ((0, 'C'), (1, 'P'), (2, 'A'), (3, 'Z'), (4, 'S'), (5, 'O'))


def main() -> int:
    sys.stdout.reconfigure(encoding='utf-8')
    program, fmap, live = load_function_map(with_flags=True)
    for argument in sys.argv[1:]:
        entry = int(argument[2:], 16) + 0x400 if argument.lower().startswith('ip') else int(argument, 16)
        sites = sorted(fmap.callers.get(entry, ()))
        print(f'=== ${entry:05X} (IP ${entry - 0x400:04X}): мест вызова {len(sites)}')
        for site in sites:
            mask = live.get(site, 0)
            names = ''.join(name for bit, name in NAMES if mask & (1 << bit)) or '-'
            nxt = program.instructions[site].next
            following = program.instructions.get(nxt)
            print(f'  {site:05X} ({site - 0x400:04X}) живые {names:6} далее: {following.text if following else "?"}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
