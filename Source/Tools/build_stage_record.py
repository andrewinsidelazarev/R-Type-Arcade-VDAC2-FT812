"""Сгенерировать весь M72Scroll отдельным C-модулем, не меняя запущенную SPG."""
import json
from pathlib import Path
from pyz80_compiler.record_backend import compile_record

ROOT=Path(__file__).resolve().parents[2]
OUTPUT=ROOT/'Source/C/generated'
BUILD=ROOT/'Build/StageRecord'


def main():
    source=ROOT/'Source/Python/rtype_port/stage.py'
    artifact=compile_record(source.read_text(encoding='utf-8'),'M72Scroll','StageScroll')
    OUTPUT.mkdir(parents=True,exist_ok=True); BUILD.mkdir(parents=True,exist_ok=True)
    (OUTPUT/'stage_scroll_generated.h').write_text(artifact.header,encoding='utf-8')
    (OUTPUT/'stage_scroll_generated.c').write_text('#include "stage_scroll_generated.h"\n'+artifact.code,encoding='utf-8')
    (BUILD/'record_manifest.json').write_text(json.dumps(artifact.manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Полный M72Scroll:',len(artifact.manifest['fields']),'полей,',len(artifact.manifest['methods']),'методов/свойств')


if __name__=='__main__': main()
