"""Специализировать ROM-декодер; конечный кэш не задаёт порядок полос в игре."""
import json
from build_stage_record import ROOT, OUTPUT
from build_translator_demo import write
from rtype_port.stage import ROM_PATH
from pyz80_compiler.write_table import compile_write_table, emit_write_table

BUILD = ROOT/'Build/TilemapTable'


def main():
    source = (ROOT/'Source/Python/rtype_port/stage.py').read_text(encoding='utf-8')
    table = compile_write_table(source, 'M72Tilemaps', '_draw_strip',
        immutable_fields={'rom': ROM_PATH.read_bytes()}, target_field='vram',
        target_count=2, target_bytes=16384,
        key_domains={'layer': range(2), 'source': range(0, 5120, 10)},
        placement='destination', placements=range(0, 256, 16))
    header, code = emit_write_table(table, 'Tilemaps_TryTable')
    write(OUTPUT/'tilemap_table_generated.h', header)
    write(OUTPUT/'tilemap_table_generated.c', '#include "tilemap_table_generated.h"\n'+code)
    BUILD.mkdir(parents=True, exist_ok=True)
    (BUILD/'records.bin').write_bytes(table.records)
    write(BUILD/'manifest.json', json.dumps(table.manifest, ensure_ascii=False, indent=2)+'\n')
    write(BUILD/'layout.json', json.dumps(dict(lookup=table.lookup, slots=table.slots,
                                            placements=table.placements))+'\n')
    print('Ключей:', table.manifest['cached_keys'], 'записей:', table.manifest['unique_records'],
          'байт:', len(table.records), 'полных вычислений:', table.manifest['evaluated_calls'], flush=True)
    return table


if __name__ == '__main__':
    main()
