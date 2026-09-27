"""Полный _draw_strip: поля метода связаны с логическими байтовыми объектами."""
import json
from build_stage_record import ROOT, OUTPUT
from build_translator_demo import write
from pyz80_compiler.buffer_backend import compile_buffer_function

BUILD=ROOT/'Build/TilemapBuffer'


def main():
    source=ROOT/'Source/Python/rtype_port/stage.py'
    artifact=compile_buffer_function(source.read_text(encoding='utf-8'),
        '_draw_strip','Tilemaps_DrawStrip',memory='view',owner='M72Tilemaps',
        fields={'self.rom':'bytes','self.vram':'list[bytearray]'})
    write(OUTPUT/'tilemap_buffer_generated.h',artifact.header)
    write(OUTPUT/'tilemap_buffer_generated.c','#include "tilemap_buffer_generated.h"\n'+artifact.code)
    write(BUILD/'manifest.json',json.dumps(artifact.manifest,ensure_ascii=False,indent=2)+'\n')
    print('Полное тело M72Tilemaps._draw_strip:',artifact.manifest['source_lines'],flush=True)


if __name__=='__main__': main()
