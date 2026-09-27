"""Перенести всё тело загрузчика полосы из активного world_terrain.py."""
import json
from build_stage_record import ROOT,OUTPUT
from build_translator_demo import write
from pyz80_compiler.buffer_backend import compile_buffer_function

BUILD=ROOT/'Build/TerrainBuffer'

def main():
    source=ROOT/'Source/Python/rtype_port/world_terrain.py'
    artifact=compile_buffer_function(source.read_text(encoding='utf-8'),'_apply_strip','Terrain_ApplyStrip')
    write(OUTPUT/'terrain_buffer_generated.h',artifact.header)
    write(OUTPUT/'terrain_buffer_generated.c','#include "terrain_buffer_generated.h"\n'+artifact.code)
    write(BUILD/'manifest.json',json.dumps(artifact.manifest,ensure_ascii=False,indent=2)+'\n')
    print('Полное тело _apply_strip:',artifact.manifest['source_lines'],flush=True)

if __name__=='__main__': main()
