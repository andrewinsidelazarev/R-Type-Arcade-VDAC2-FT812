"""Опорная версия VDAC2+: pre-releases/<дата> vNNN - <описание> (состав — по CLAUDE.md).

В снимок: Source/, Docs/, cfg/, Baselines/, корневые документы, build.cmd, spgbld_rtype.ini, run_python.cmd,
собранные rtype_vdac2.spg и RTYPECOD.PAC (с 2026-09-27 код игры — в нём, SPG — загрузчик с заставкой; пак уровней
RTYPELVL.PAC не копируется — меняется редко, 28 МБ), сгенерированные включения сборки (BuildArtifacts, в том числе
splash.inc), RELEASE_NOTES.md (готовый файл —
второй аргумент) и SOURCE_MANIFEST_SHA256.txt. Не копируются ROM (Arcade/), Assets/, Audio/, рабочий Build/ целиком,
отладочные .sym/.lst. Аргументы: имя папки снимка, файл заметок выпуска.
"""
from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.stdout.reconfigure(encoding='utf-8')
MACHINE = ROOT / 'Build' / 'V30Z80'
ARTIFACTS = ('config.inc', 'rtype_ay.inc', 'rtype_boot.inc', 'rtype_data.json', 'rtype_gs.inc', 'rtype_loader.inc',
             'rtype_loader.json', 'rtype_loader_entry.inc', 'rtype_ring.inc', 'rtype_sound.inc', 'rtype_spg.json',
             'rtype_switch.inc', 'video.inc', 'video_catalog.json', 'video_tables.inc', 'video_objects.inc',
             'rtype_objects.inc', 'rtype_objects.json')
SKIP_SUFFIXES = {'.sym', '.lst', '.pyc'}


def copy_tree(source: Path, target: Path) -> None:
    for path in source.rglob('*'):
        if path.is_dir() or path.suffix.lower() in SKIP_SUFFIXES or '__pycache__' in path.parts:
            continue
        destination = target / path.relative_to(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)


def main() -> int:
    name, notes = sys.argv[1], Path(sys.argv[2])
    target = ROOT / 'pre-releases' / name
    if target.exists():
        print(f'уже есть: {target}')
        return 1
    target.mkdir(parents=True)
    for folder in ('Source', 'Docs', 'cfg', 'Baselines'):
        copy_tree(ROOT / folder, target / folder)
    for file in ('CLAUDE.md', 'PROJECT_MEMORY.md', 'README.md', 'build.cmd', 'spgbld_rtype.ini', 'run_python.cmd'):
        shutil.copy2(ROOT / file, target / file)
    shutil.copy2(MACHINE / 'rtype_vdac2.spg', target / 'rtype_vdac2.spg')
    shutil.copy2(MACHINE / 'RTYPECOD.PAC', target / 'RTYPECOD.PAC')
    (target / 'BuildArtifacts').mkdir()
    for file in ARTIFACTS:
        shutil.copy2(MACHINE / file, target / 'BuildArtifacts' / file)
    shutil.copy2(MACHINE / 'splash' / 'splash.inc', target / 'BuildArtifacts' / 'splash.inc')
    shutil.copy2(notes, target / 'RELEASE_NOTES.md')
    lines = []
    for path in sorted(target.rglob('*')):
        if path.is_file() and path.name != 'SOURCE_MANIFEST_SHA256.txt':
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            lines.append(f'{digest}  {path.relative_to(target).as_posix()}')
    (target / 'SOURCE_MANIFEST_SHA256.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    spg = hashlib.sha256((target / 'rtype_vdac2.spg').read_bytes()).hexdigest()
    code = hashlib.sha256((target / 'RTYPECOD.PAC').read_bytes()).hexdigest()
    print(f'снимок: {target}\nфайлов: {len(lines)}\nSPG: {spg} ({(target / "rtype_vdac2.spg").stat().st_size} байт)\n'
          f'RTYPECOD.PAC: {code} ({(target / "RTYPECOD.PAC").stat().st_size} байт)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
