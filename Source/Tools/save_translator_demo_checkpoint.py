"""Сохранить отдельную, не перезаписываемую контрольную точку демо."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil

ROOT=Path(__file__).resolve().parents[2]
BUILD=ROOT/'Build/TranslatorDemo'

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--name',required=True,help='Имя новой папки внутри pre-releases')
    args=parser.parse_args()
    if Path(args.name).name!=args.name or args.name in ('.','..'):
        raise ValueError('Нужно одно имя папки, без пути')
    destination=ROOT/'pre-releases'/args.name
    payload=BUILD/'rtype_vdac2.spg'
    check=json.loads((BUILD/'z80_check.json').read_text(encoding='utf-8'))
    digest=hashlib.sha256(payload.read_bytes()).hexdigest()
    if check['spg_sha256']!=digest:
        raise RuntimeError('Проверка относится к другой сборке')
    scenario=json.loads((BUILD/'scenario_check.json').read_text(encoding='utf-8'))
    if scenario['spg_sha256']!=digest or scenario['rendered_frames']<1100:
        raise RuntimeError('Нет покадровой проверки всей демо-сцены для этой сборки')
    report=json.loads((BUILD/'build_report.json').read_text(encoding='utf-8'))
    if report['spg_sha256']!=digest:
        raise RuntimeError('Отчёт сборщика относится к другому SPG')
    for path,expected in {**report['source_sha256'],**report['implementation_sha256']}.items():
        if hashlib.sha256((ROOT/path).read_bytes()).hexdigest()!=expected:
            raise RuntimeError('Исходник изменён после сборки: '+path)
    if destination.exists():
        raise FileExistsError('Контрольную точку нельзя перезаписывать')
    destination.mkdir(parents=True)
    ignore=shutil.ignore_patterns('__pycache__','*.pyc','*.sym','*.lst')
    for directory in ('Source','Docs','cfg'):
        shutil.copytree(ROOT/directory,destination/directory,ignore=ignore)
    for source in [*ROOT.glob('*.md'),*ROOT.glob('*.cmd'),ROOT/'spgbld_rtype.ini']:
        if source.is_file(): shutil.copy2(source,destination/source.name)
    shutil.copy2(payload,destination/payload.name)
    shutil.copy2(BUILD/'boot.bin',destination/'Core.bin')
    artifacts=destination/'DemoArtifacts'
    artifacts.mkdir()
    for name in ('code.bin','build_report.json','z80_check.json','scenario_check.json'):
        shutil.copy2(BUILD/name,artifacts/name)
    native=BUILD/'native_check.json'
    if native.exists() and json.loads(native.read_text(encoding='utf-8'))['spg_sha256']==digest:
        shutil.copy2(native,artifacts/native.name)
    # Прямой запуск сохранённого файла: не указатель на изменяемый рабочий Build.
    (destination/'run_translator_demo.cmd').write_text(
        '@echo off\nstart "" "E:\\zx\\unreal_x64\\Unreal.exe" "%~dp0rtype_vdac2.spg"\n',
        encoding='utf-8')
    notes=(ROOT/'Docs/TRANSLATOR_DEMO_STATUS.md').read_text(encoding='utf-8')
    notes+='\n## Сохранённый файл\n\nSHA-256 SPG: `'+digest+'`.\n'
    notes+='\n`Core.bin` здесь содержит загрузочную обвязку; C-банк находится в `DemoArtifacts/code.bin`.\n'
    (destination/'RELEASE_NOTES.md').write_text(notes,encoding='utf-8')
    records=[]
    for path in sorted(destination.rglob('*')):
        if path.is_file():
            records.append(hashlib.sha256(path.read_bytes()).hexdigest()+'  '+path.relative_to(destination).as_posix())
    (destination/'SOURCE_MANIFEST_SHA256.txt').write_text('\n'.join(records)+'\n',encoding='utf-8')
    print(destination)
    print('SPG SHA256',digest)
    print('files',len(records))

if __name__=='__main__': main()
