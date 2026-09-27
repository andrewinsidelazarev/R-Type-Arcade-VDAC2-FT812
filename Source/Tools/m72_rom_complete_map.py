#!/usr/bin/env python3
"""Построить проверяемую полную карту ROM R-Type World (Irem M72).

Скрипт не назначает неизвестным байтам выдуманную семантику. Он гарантирует
полное адресное покрытие, выделяет доказанные аппаратные пространства,
рекурсивно обходит прямой V30 control-flow и оставляет все ещё не объяснённые
диапазоны явно видимыми в JSON/Markdown.
"""
from __future__ import annotations

import argparse
import csv
import collections
import hashlib
import itertools
import json
import math
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from capstone import CS_ARCH_X86, CS_GRP_CALL, CS_GRP_JUMP, CS_MODE_16, Cs
from capstone.x86_const import (
    X86_OP_IMM, X86_OP_MEM, X86_REG_BP, X86_REG_ES, X86_REG_SI,
)


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "Source" / "Tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from m72_arcade import ROMS, assemble_regions, require_verified  # noqa: E402
from m72_stage_event_map import (  # noqa: E402
    HANDLER_NAMES, OUTPUT as ALL_STAGE_PATH, STAGE_RANGES,
    build_markdown as build_stage_events_markdown,
)


OUT_DIR = ROOT / "Build" / "Analysis"
JSON_PATH = OUT_DIR / "rtype_world_rom_complete.json"
MD_PATH = ROOT / "Docs" / "RTYPE_WORLD_ROM_COMPLETE.md"
SOUND_PATH = OUT_DIR / "rtype_sound_upload.bin"
SOUND_TRACE_DIR = (ROOT / "Build" / "Arcade" / "MAME" /
                   "sound_cpu_trace")
MAIN_PATH = OUT_DIR / "rtype_main_unique.bin"
OLD_MAP = ROOT / "Docs" / "RTYPE_WORLD_ROM_MAP.md"
UNIDASM = ROOT / "Tools" / "mame0288" / "unidasm.exe"
TRACE_FILES = (
    ROOT / "Build" / "Arcade" / "MAME" / "stage1_object_full_4470_inv" / "object_writes.csv",
    ROOT / "Build" / "Arcade" / "MAME" / "stage1_vram_pc_4500_inv" / "vram_writes.csv",
    ROOT / "Build" / "Arcade" / "MAME" / "boss_palette_pc_probe" / "palette_writes.csv",
    ROOT / "Build" / "Arcade" / "MAME" / "read_pc_probe" / "player_writes.csv",
)
SOUND_INDIRECT_ENTRIES = {
    # `$00F1…$010D`: command high five bits index 32-word table `$035E`.
    0x03B4, 0x04DF, 0x04E3, 0x054B, 0x0556, 0x056A, 0x057F, 0x0635,
    0x07DA, 0x0801, 0x0882, 0x0644, 0x066A, 0x0686, 0x068F, 0x069C,
    0x06A8, 0x06B4, 0x0E0C, 0x08FD,
    # `$039E…$03AB`: event/type index выбирает одну из трёх процедур.
    0x0976, 0x0BD8, 0x0CCA,
}
SOUND_COMMAND_TABLE = (
    0x03B4, 0x04DF, 0x04E3, 0x054B, 0x0556, 0x056A, 0x057F, 0x0635,
    0x07DA, 0x0801, 0x0882, 0x0644, 0x066A, 0x0686, 0x068F, 0x069C,
    0x06A8, 0x06B4,
    *(0x0E0C for _ in range(13)),
    0x08FD,
)
SOUND_TYPE_TABLE = (0x0976, 0x0BD8, 0x0CCA)
BOSS_TERRAIN_TRACE = (ROOT / "Build" / "Arcade" / "MAME" /
                      "boss_transition_pc_exact" / "vram_writes.csv")
BOSS_TERRAIN_PATHS = {
    0x46CC: 68,
    0x4754: 57,
    0x47C6: 52,
    0x482E: 62,
}

# Все косвенные runtime-dispatchers перечисляются не «по похожим словам», а
# по точным ROM-таблицам и producer sites. Эти константы одновременно служат
# проверяемой спецификацией: изменение любого адреса в ROM валит генератор.
# Handlers кольцевой очереди `$0384`. Набор выводится обратным разбором CX во всех
# вызовах `$0384` (`task_queue_producers`) и сверяется с этой спецификацией. `$EA1F`
# приходит только через `MOV DX,$EA1F` (`$1156`) и `MOV CX,DX` (`$1175`) при DSW bit 9 и
# bit 4 счётчика кадров: чередуется с `$EA39` каждые 16 кадров (мигание текста в VRAM
# `$D000:$012C`). Прежний список из 15 элементов учитывал только `MOV CX,imm`.
TASK_QUEUE_TARGETS = {
    0xE865, 0xE883, 0xE8A0, 0xE8BD, 0xEA1F, 0xEA39, 0xEA41,
    0xEA49, 0xEA51, 0xEA73, 0xEBF1, 0xEC14, 0xEC7B,
    0xED3A, 0xED58, 0xED93,
}
TASK_QUEUE_ALLOCATOR = 0x0384
# Reset `$3F00:$0806…$0813` программирует uPD71059C: ICW1 `$17`, ICW2 `$20`, ICW4 `$0F`.
# Линии IRQ0..7 используют векторы `$20…$27`; таблица векторов — ROM `$00080…$0009F`
# (ROM отображён с линейного адреса 0), все записи указывают в runtime `CS=$0040`.
PIC_VECTOR_BASE = 0x20
IRQ_VECTOR_ENTRIES = {
    0: 0x00FE, 1: 0x00FA, 2: 0x02EE,
    3: 0x00FC, 4: 0x00FC, 5: 0x00FC, 6: 0x00FC, 7: 0x00FC,
}
ALLOCATOR_IMMEDIATE_TARGET_BY_SITE = {
    0x07FB: 0x09F9,
    0x0898: 0x0C88, 0x08B0: 0x0C88,
    0x08D0: 0x0C71, 0x08EB: 0x0C71,
    0x0906: 0x0C88, 0x091B: 0x0C88, 0x0930: 0x0C88,
    0x09DA: 0x0A71, 0x0AA1: 0x23C8,
    0x0B63: 0x1951, 0x0B78: 0x1AA1,
    0x0D42: 0x09F9,
    0x0F49: 0x0F5C, 0x23AB: 0x23C8, 0x241E: 0x30B6,
    0x154D: 0x1951, 0x1594: 0x188E, 0x15D7: 0x188E,
    0x161B: 0x1951, 0x162B: 0x1A51,
    0x183D: 0x1951, 0x1852: 0x1AA1,
    0x25D3: 0x27CC, 0x4EFA: 0x4EAF, 0x55F0: 0x5629,
    0x582E: 0xE7BE, 0x5974: 0x59A2, 0x5A09: 0x5B9F,
    0x5DCF: 0x5DFE, 0x5E22: 0x5E8E, 0x60C1: 0x610D,
    0x5CF1: 0x5D2D, 0x5EF4: 0x5F3C,
    0x5DAB: 0xE6AB,
    0x6683: 0x66C8, 0x672F: 0x67D5, 0x6750: 0x67D5,
    0x6763: 0x67D5, 0x6776: 0x67D5, 0x6AA2: 0x6ACB,
    0x6AD1: 0x6C37, 0x6D03: 0xE7BE, 0x6DE9: 0x6E27,
    0x6975: 0x69B4, 0x6EA2: 0x6EC4, 0x6F90: 0x6FD0,
    0x7189: 0x71C7, 0x729B: 0x72D2,
    0x6F58: 0xE7B6, 0x73FE: 0x7435,
    0x74BB: 0x7607, 0x77C7: 0x780E, 0x80EA: 0x8138,
    0x835B: 0x842C, 0x839C: 0x83DF, 0x86AD: 0x86D3,
    0x790A: 0x7935, 0x7D6F: 0x7DBB, 0x8470: 0x8490,
    0x8568: 0x85B0, 0x8764: 0x8798, 0x8C19: 0x8C2E,
    0x8F65: 0x8F86, 0x9162: 0x91CC, 0x9667: 0x9674,
    0x80AF: 0x8D85, 0x866F: 0xE6AB, 0x881D: 0x8861,
    0x8C4F: 0xE7BE, 0x8C92: 0xE7BE, 0x8CD2: 0xE7BE,
    0x8D12: 0xE80C, 0x968B: 0x96E9,
    0x9400: 0xE7BE, 0x975E: 0x983B, 0x9793: 0x983B,
    0x97CD: 0x983B, 0x9807: 0x983B,
    0x8985: 0x89B0, 0x9904: 0x9915, 0x9926: 0x9B26,
    0x994E: 0x9B9B, 0x9983: 0x9F63, 0x99E0: 0xA035,
    0x9A2E: 0xA133, 0x9BC3: 0xE7B6, 0x9CB2: 0xFC20,
    0x9DA4: 0x9E07, 0x9DDF: 0x9EC0, 0x9FBA: 0xE7B6,
    0xE437: 0xE4A5, 0xE55C: 0xE568, 0xF1A7: 0xF1BF,
    0xA235: 0xA290, 0xA723: 0xA762, 0xB0E7: 0xB111,
    0xA2EF: 0xFC20, 0xA313: 0xFC20,
    0xB1DE: 0xB1FA, 0xB801: 0xB805, 0xC0B0: 0xC0CA,
    0xC474: 0xC4BC, 0xEE11: 0xEE3C, 0xEEB1: 0xEEB5,
    0xA4E1: 0xA6A5, 0xA5D6: 0xA5EB, 0xA768: 0xAA0F,
    0xA7E2: 0xAB62, 0xA84C: 0xAC4C, 0xA886: 0xAC4C,
    0xA8BF: 0xACE7, 0xA941: 0xAC4C,
    0xB138: 0x5F3C, 0xB21C: 0xB521, 0xB3DE: 0xB491,
    0xB3EE: 0xE817, 0xB822: 0xB997, 0xB85B: 0xBAA7,
    0xB87F: 0xBD32, 0xB897: 0xBE81, 0xC14F: 0xFC20,
    0xC1A3: 0xC284,
    0xA6CF: 0xE7B6, 0xAB2A: 0xE6AB, 0xAE24: 0xE6AB,
    0xAE62: 0xAEFB, 0xAEB0: 0xAEFB, 0xB096: 0xE7B6,
    0xBA5C: 0xBA9B, 0xBD5F: 0xBDB2, 0xBEC0: 0xC03F,
    0xC003: 0xE7B6, 0xC2A8: 0xE817, 0xC2C9: 0xE817,
    0xC385: 0xC39C, 0xC7FF: 0xE7BE,
    0xC84C: 0xC928, 0xC86B: 0xC928, 0xC88D: 0xC928,
    0xC8AF: 0xC928, 0xCC5F: 0xCEEA, 0xCC94: 0xCF9C,
    0xCCC3: 0xCF6C, 0xCCED: 0xCF9C, 0xCD19: 0xCF8C,
    0xCD43: 0xCF9C, 0xCD6F: 0xCF7C, 0xCE80: 0xCE9F,
    0xCFEF: 0xD28F, 0xD02E: 0xD28F, 0xD09B: 0xD28F,
    0xD225: 0xD244, 0xD42C: 0xE6AB, 0xD453: 0xE6AB,
    0xD572: 0xE7B6, 0xD664: 0xD7B9, 0xD6E0: 0xE7BE,
    0xD992: 0xDAC8, 0xD9E8: 0xE7BE, 0xDA6C: 0xDAC8,
    0xDC88: 0xE601, 0xDEA5: 0xDEC9, 0xE015: 0xE060,
    0xE230: 0xE601, 0xE390: 0xE601, 0xE3F6: 0xE601,
    0xBE49: 0xE601, 0xCA35: 0xE7BE, 0xCA8A: 0xCB66,
    0xCAA9: 0xCB66, 0xCACB: 0xCB66, 0xCAED: 0xCB66,
    0xCEAC: 0xE7B6, 0xD251: 0xE7B6, 0xD364: 0xE601,
    0xD7C9: 0xD789, 0xDEFA: 0xE7B6,
    0xF386: 0xF3C1, 0xF3AD: 0xF3C1, 0xF43E: 0xF44E,
    0xF65D: 0xE601, 0xFBA3: 0xFBED,
    0xF467: 0xF477, 0xFB1F: 0xFB53,
    0xEFF0: 0x23C8, 0xFADD: 0xFAE1,
}

# Fixed-object dispatcher `$0251…$0261` advances BP by `$20`.  Most state
# changes write `[BP]`, but the paired missile launcher at `$3321` deliberately
# changes the handler of the *next* fixed record through `[BP+$20]`.  Keep this
# exceptional producer explicit so that a generic object-field immediate is
# never mistaken for a handler.
ADJACENT_FIXED_HANDLER_TARGET_BY_SITE = {
    0x3321: 0x336D,
}

# Эти пункты являются частью строгого критерия семантической готовности.
# Список сокращается только после доказательного code/data split и описания
# соответствующего пространства в RTYPE_WORLD_ROM_MAP.md. Нулевое байтовое
# покрытие без нулевого списка ниже не считается завершённым анализом.
BUILTIN_SEMANTIC_GAPS = (
    "каждый ES data range: формат записи и полный список consumers",
    "sprite graphics ROM: каждый code связан с descriptor/resource consumers",
)

# Значение ES во всех 727 синтаксических ES-access sites. После IRQ/bootstrap
# рабочее значение равно `$1000`; перечислены только локальные push/set/pop
# окна. Общие tile renderer blocks `$EB13..$EBF0` вызываются как для обоих
# video layers, поэтому там множество сегментов намеренно содержит два
# доказанных значения. `$0180/$01A6` используют аппаратно выбранное sound
# shared-memory окно из DS:$3088.
ES_SEGMENT_PC_RANGES = (
    (0x0026, 0x0030, (0xE000,)),
    (0x004D, 0x004D, (0x4000,)),
    (0x005B, 0x005B, (0xC000,)),
    (0x0180, 0x0180, (None,)),
    (0x01A6, 0x01A6, (None,)),
    (0x0EB5, 0x0EBD, (0x4000,)),
    (0x1FB1, 0x1FBC, (0x4000,)),
    (0x2384, 0x23A2, (0xD000,)),
    (0x24AB, 0x24C0, (0x4000,)),
    (0x2749, 0x27C0, (0xD000,)),
    (0x2ABA, 0x2BD2, (0xD000,)),
    (0x2BF4, 0x2C3B, (0xD800,)),
    (0x2D07, 0x2D1F, (0x4000,)),
    (0x2EC8, 0x2EE0, (0x4000,)),
    (0x4FBF, 0x4FCA, (0xD000,)),
    (0x5266, 0x52AD, (0xC800,)),
    (0x52B7, 0x52FC, (0xCC00,)),
    (0x5366, 0x53CD, (0x3B00,)),
    (0x53D5, 0x5407, (0x3B00,)),
    (0x5414, 0x547F, (0x3B00,)),
    (0x5487, 0x54BD, (0x3B00,)),
    (0x6A07, 0x6A17, (0xD000,)),
    (0x90EC, 0x9153, (0xD000,)),
    (0xA67F, 0xA69C, (0xD000,)),
    (0xBFD4, 0xBFE4, (0xD000,)),
    (0xC117, 0xC123, (0xD000,)),
    (0xC1CB, 0xC1D1, (0xD800,)),
    (0xC1D4, 0xC1D8, (0xD000,)),
    (0xC352, 0xC375, (0xD800,)),
    (0xC447, 0xC469, (0xD800,)),
    (0xE86B, 0xE87F, (0xD000,)),
    (0xE889, 0xE89C, (0xD000,)),
    (0xE8A6, 0xE8B9, (0xD800,)),
    (0xE8E8, 0xE91D, (0x4000,)),
    (0xE9CE, 0xE9E2, (0xD000,)),
    (0xEA07, 0xEA1D, (0xD000,)),
    (0xEA2C, 0xEA34, (0xD000,)),
    (0xEB13, 0xEBF0, (0xD000, 0xD800)),
    (0xEC34, 0xEC5F, (0xD000,)),
    (0xEC6A, 0xEC77, (0xD000,)),
    (0xECC1, 0xECCE, (0xD000,)),
    (0xED3A, 0xED92, (0xD000,)),
    (0xED9A, 0xEDD4, (0xD000,)),
    (0xF1EF, 0xF202, (0xD000,)),
)

ES_SEGMENT_MEANINGS = {
    None: "sound shared-memory segment selected by DS:$3088",
    0x1000: "World data ROM",
    0x3B00: "palette RGB ROM",
    0x4000: "main work RAM",
    0xC000: "sprite RAM",
    0xC800: "foreground palette RAM",
    0xCC00: "background/sprite palette RAM",
    0xD000: "foreground tile VRAM",
    0xD800: "background tile VRAM",
    0xE000: "sound CPU upload/shared RAM",
}

# Call-local domains, доказанные state-кодом, но не выводимые из одного
# straight-line basic block. Это не ручная классификация картинки: каждое
# множество ниже является точным результатом арифметики непосредственно перед
# renderer-call, включая обе ветви выбора базового кадра там, где они есть.
SPRITE_EXACT_BX_BY_CALL = {
    # Двенадцать кадров двух заставочных/служебных объектов.
    0x2E85: tuple(0x175E + 6 * phase for phase in range(12)),
    0x3046: tuple(0x17A6 + 6 * phase for phase in range(12)),
    # `object+$12 &= $0F`, затем address=`$1AF0 + phase*6`.
    0x34DD: tuple(0x1AF0 + 6 * phase for phase in range(16)),
    0x35B5: tuple(0x1AF0 + 6 * phase for phase in range(16)),
    0x37A6: tuple(0x1AF0 + 6 * phase for phase in range(16)),
    0x387F: tuple(0x1AF0 + 6 * phase for phase in range(16)),
    # Death-state counters: `$18/$30`, decrement `$06` before render.
    0x4476: tuple(0x20F4 + phase for phase in (0, 6, 12)),
    0x4579: tuple(0x20F4 + phase for phase in (0, 6, 12)),
    0x490F: tuple(0x21BC + phase for phase in (0, 6, 12)),
    0x4E97: tuple(0x26AC + phase for phase in range(0, 43, 6)),
    # Dobker: две ориентации, 16 фаз, четыре последовательных компонента.
    **{call: tuple(base + 24 * phase + ordinal * 6
                   for base in (0x21DC, 0x241C)
                   for phase in range(16))
       for ordinal, calls in enumerate(((0x4A02, 0x4B31),
                                        (0x4A0A, 0x4B39),
                                        (0x4A12, 0x4B41),
                                        (0x4A19, 0x4B48)))
       for call in calls},
    # Вторая Dobker-форма: две ориентации, 8 фаз, те же 4 компонента.
    **{call: tuple(base + 24 * phase + ordinal * 6
                   for base in (0x235C, 0x259C)
                   for phase in range(8))
       for ordinal, call in enumerate((0x4C86, 0x4C8E, 0x4C96, 0x4C9D))},
    # `(object+$12 & $18) * 3/4` и две базы, выбранные флагом состояния.
    0x56E3: tuple(base + phase for base in (0x2832, 0x284A)
                  for phase in (0, 6, 12, 18)),
    0x5737: tuple(base + phase for base in (0x2862, 0x287A)
                  for phase in (0, 6, 12, 18)),
    0x57D4: tuple(base + phase for base in (0x2892, 0x28AA)
                  for phase in (0, 6, 12, 18)),
    # `$5871..$587D` увеличивает `object+$14`, при 12 сбрасывает в 0;
    # `$588A..$5897` умножает фазу на шесть.
    0x589B: tuple(0x27B6 + 6 * phase for phase in range(12)),
    # `(VBlank + object phase) & $1C`, затем индекс * 3/2.
    0x59C5: tuple(0x28E2 + phase for phase in range(0, 43, 6)),
    0x5D48: tuple(0x299A + phase for phase in range(0, 43, 6)),
    # `$661A` — общий flash/render wrapper. Ниже точные BX его девяти callers.
    0x614E: (0x2BC8, 0x2BD4, 0x2C28, 0x2C34),
    # Formation child `$5E8E`: все reachable `$92EC` scripts используют
    # только phases 0..15 до terminal нулевого word.
    0x5EAD: tuple(0x29D2 + 6 * phase for phase in range(16)),
    # Поле phase у этих handlers нормализуется `AND $0F` до renderer.
    0x67F3: tuple(0x2CB4 + 6 * phase for phase in range(16)),
    0x690C: tuple(0x2CB4 + 6 * phase for phase in range(16)),
    # `$69D6->$6A78`: phase-команды всех `$F95C` scripts дают 0..15.
    0x69D6: tuple(0x2DD0 + 6 * phase for phase in range(16)),
    # `$6C37` использует те же доказанные phase 0..15, две body bases.
    0x6C5E: tuple(base + 6 * phase for base in (0x2F0E, 0x2F6E)
                  for phase in range(16)),
    0x724F: tuple(0x3216 + 6 * phase for phase in range(16)),
    # `(object slot/8 + VBlank) & $18`, затем индекс * 3/4.
    0x6E4F: tuple(0x2EEE + phase for phase in (0, 6, 12, 18)),
    0x745D: tuple(0x327E + phase for phase in (0, 6, 12, 18)),
    # `$1D89` returns one of the sixteen direction codes 0,$04..$3C;
    # `$86D3/$86EA` multiply it by 3/2 and add one of two body bases.
    0x8710: tuple(base + 6 * phase
                  for base in (0x3A36, 0x3A96) for phase in range(16)),
    # `$7D22/$7D45` — flash wrappers. `$9274` motion roots дают 0..27;
    # `$7CFC` отдельно маскирует индекс до 15.
    0x79FC: tuple(0x3526 + 6 * phase for phase in range(28)),
    0x7AB0: tuple(0x3676 + 6 * phase for phase in range(28)),
    0x7B67: tuple(0x371E + 6 * phase for phase in range(28)),
    0x7BDE: tuple(0x371E + 6 * phase for phase in range(28)),
    0x7C1F: tuple(0x3676 + 6 * phase for phase in range(28)),
    0x7CFC: tuple(base + 6 * phase for base in (0x3676, 0x371E)
                  for phase in range(16)),
    # Четыре фазы: `(VBlank + object phase) & $0C`, индекс * 3/2.
    0x8DA5: tuple(0x3F26 + phase for phase in (0, 6, 12, 18)),
    0x9EE0: tuple(0x44BA + phase for phase in (0, 6, 12, 18)),
    0x9F4E: tuple(0x44BA + phase for phase in (0, 6, 12, 18)),
    # `$9520->$957C`: `(phase+8)&$0F`, поэтому перестановка 16 значений.
    0x9520: tuple(0x41FE + 6 * phase for phase in range(16)),
    # `$957C` saves/restores BX around its object-state test, so both renderer
    # branches receive the exact caller domain from `$9520` unchanged.
    0x9598: tuple(0x41FE + 6 * phase for phase in range(16)),
    0x959F: tuple(0x41FE + 6 * phase for phase in range(16)),
    # `(VBlank + object+$12) & $18`; необязательная flash-ветвь не меняет BX.
    0xB744: tuple(0x608E + phase for phase in (0, 6, 12, 18)),
    0xB756: tuple(0x608E + phase for phase in (0, 6, 12, 18)),
    # Та же четырёхфазная формула для позднего объекта/босса.
    0xE63F: tuple(0x84AE + phase for phase in (0, 6, 12, 18)),
}

# В этих branch wrappers второй renderer получает ровно тот же BX, что и
# первый: между вызовами нет записи BX (только palette swap/pop/jump). Это
# отдельное доказанное data-flow ребро, а не повторная эвристика descriptor.
SPRITE_SAME_BX_CALL = {
    0x280C: 0x27F7,
    0x5FC4: 0x5FBB,
    0x663A: 0x6633,
    0x6A97: 0x6A90,
    0x717E: 0x7177,
    0x739C: 0x7395,
    0x77BD: 0x77B6,
    0x7D41: 0x7D3A,
    0x7D64: 0x7D5D,
    0x8054: 0x804D,
    0x8428: 0x8421,
    0x85EF: 0x85E6,
    0x8EC8: 0x8EC1,
    0x959F: 0x9598,
    0x9D0C: 0x9D05,
    0xB30D: 0xB304,
    0xBF57: 0xBF4E,
    0xCC4C: 0xCC43,
    0xCE30: 0xCE27,
    0xD130: 0xD127,
    0xD1D2: 0xD1C9,
    0xD2D4: 0xD2CB,
    0xD645: 0xD63C,
    0xD946: 0xD93D,
    0xDBF5: 0xDBEC,
    0xE193: 0xE18A,
    0xE2E6: 0xE2DD,
}

# Только уже доказанные entry points. В отличие от всех `$XXXX` из prose это
# именно код: hardware/game roots, object handlers и общие helpers, для которых
# в RTYPE_WORLD_ROM_MAP.md приведены disassembly/HEX или runtime PC evidence.
KNOWN_CODE_ENTRIES = {
    0x0000, 0x03EC, 0x0443, 0x0467, 0x0672, 0x0689, 0x0703, 0x0784,
    0x07A6, 0x0D75, 0x0FB0, 0x11CC, 0x1BCC, 0x1BE9, 0x1C1B, 0x1D6B,
    0x1D89, 0x1E6C, 0x1EB5, 0x2027, 0x216B, 0x226C, 0x24CE, 0x2581,
    0x2614, 0x2682, 0x26AD, 0x26D0, 0x26E9, 0x2702, 0x283B, 0x2878,
    0x297C, 0x2A10, 0x2AB4, 0x2C94, 0x31D9, 0x3304, 0x38F4, 0x51EE,
    0x5228, 0x523E, 0x5481, 0x54C4, 0x54E4, 0x5504, 0x5526, 0x5579,
    0x5596, 0x55B5, 0x55E9, 0x5620, 0x5629, 0x56C0, 0x5704, 0x57B1,
    0x5811, 0x586A, 0x5914, 0x5947, 0x596D, 0x59A2, 0x5A02, 0x5A2B,
    0x5AE9, 0x5B4D, 0x5B9F, 0x5BA4, 0x5C3E, 0x5C83, 0x5CA6, 0x5CD7,
    0x5DC8, 0x5DFE, 0x5E8E, 0x60BA, 0x610D, 0x61B6, 0x61E3, 0x6243,
    0x62BD, 0x631B, 0x6374, 0x6380, 0x638C, 0x6392, 0x6459, 0x6502,
    0x652F, 0x657C, 0x661A, 0x663E, 0x66C8, 0x6715, 0x67D5, 0x687D,
    0x6A9B, 0x74B4, 0x80E3, 0x8138, 0x82D6, 0x86A6, 0x86D3, 0x86EA,
    0x897E, 0x89B0, 0x8AEE, 0x98FD, 0x9915, 0x9A80, 0x9AE4, 0x9B05,
    0x9B26, 0x9B39, 0x9B9B, 0x9C33, 0x9C70, 0x9CA8, 0x9CAF, 0x9CEC,
    0x9D9E, 0x9E07, 0x9E78, 0x9F63, 0x9F84, 0x9FE9, 0xA035, 0xA133,
    0xE430, 0xE489, 0xE601, 0xE64E, 0xE686, 0xE7A6, 0xE7AE, 0xE7B6,
    0xE7BE, 0xE817, 0xEDD9, 0xEDE9, 0xF01B, 0xF0F3, 0xF130, 0xF366,
    0xF429, 0xF461, 0xF485, 0xF4AA, 0xF50C, 0xF548, 0xF578, 0xF5C1,
    0xF63A, 0xF694, 0xF6DA, 0xF75F, 0xF876, 0xF88C, 0xF8A7, 0xF8F5,
    0xF926, 0xF97D, 0xF985, 0xF99F, 0xFB9C, 0xFBED, 0xFC20,
}

# `$3900:$0000` устанавливает обработчик IRQ `$02FD`, а затем выбирает один
# из пяти экранов service-mode через таблицу words `ES:$EB07`. Эти переходы
# косвенные, поэтому их необходимо явно передать консервативному обходу.
BOOT39_INDIRECT_ENTRIES = {0x02FD, 0x038D, 0x03DD, 0x0445, 0x0465, 0x0500}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sound_trace_audit(sound_runtime: "Z80Reachability",
                      errors: list[str]) -> dict[str, object]:
    """Сверить статическую Z80 карту с агрегированной MAME bus trace."""
    names = ("pc_hits.csv", "program_reads.csv", "program_writes.csv",
             "io_reads.csv", "io_writes.csv", "commands.csv")
    paths = {name: SOUND_TRACE_DIR / name for name in names}
    missing = [name for name, path in paths.items() if not path.is_file()]
    if missing:
        errors.append("нет sound CPU trace: " + ", ".join(missing))
        return {"verified": False, "missing": missing}

    def rows(name: str) -> list[dict[str, str]]:
        with paths[name].open(encoding="ascii", newline="") as handle:
            return list(csv.DictReader(handle))

    pc_rows = rows("pc_hits.csv")
    read_rows = rows("program_reads.csv")
    write_rows = rows("program_writes.csv")
    io_read_rows = rows("io_reads.csv")
    io_write_rows = rows("io_writes.csv")
    command_rows = rows("commands.csv")
    pcs = {int(row["pc"], 16) for row in pc_rows}
    code_bytes = set(sound_runtime.owners)
    instruction_starts = set(sound_runtime.instructions)
    transition_pcs = sorted(pcs - code_bytes)
    # `$060F RET` сначала выставляет PC=$0610, затем читает return address из
    # stack. Поэтому taps видят `$0610` на двух RAM reads, хотя opcode `$0610`
    # не исполняется. Это единственный такой переход в канонической трассе.
    if transition_pcs != [0x0610]:
        errors.append("sound trace: PC вне static code bytes: " +
                      ", ".join(f"${value:04X}" for value in transition_pcs))
    transition_reads = sorted({
        int(row["address"], 16) for row in read_rows
        if int(row["pc"], 16) == 0x0610
    })
    if transition_reads != [0xFD7A, 0xFD7B]:
        errors.append("sound trace: `$0610` не сводится к stack reads `$FD7A/$FD7B`")

    program_read_addresses = {int(row["address"], 16) for row in read_rows}
    program_write_addresses = {int(row["address"], 16) for row in write_rows}
    bad_reads = sorted(address for address in program_read_addresses
                       if not (address <= 0x7FFF or address >= 0xF800))
    bad_writes = sorted(address for address in program_write_addresses
                        if address < 0xF800)
    if bad_reads:
        errors.append(f"sound trace: {len(bad_reads)} reads вне ROM/RAM map")
    if bad_writes:
        errors.append(f"sound trace: {len(bad_writes)} writes вне `$F800..$FFFF`")

    io_read_addresses = {int(row["address"], 16) for row in io_read_rows}
    io_write_addresses = {int(row["address"], 16) for row in io_write_rows}
    if io_read_addresses != {0x01, 0x02}:
        errors.append("sound trace: неожиданный набор I/O read ports")
    if io_write_addresses != {0x00, 0x01, 0x06}:
        errors.append("sound trace: неожиданный набор I/O write ports")
    commands = [int(row["command"], 16) for row in command_rows]
    if commands != list(range(0x100)):
        errors.append("sound trace: commands не равны точной последовательности `$00..$FF`")

    return {
        "verified": not (missing or transition_pcs != [0x0610] or
                         transition_reads != [0xFD7A, 0xFD7B] or
                         bad_reads or bad_writes or
                         io_read_addresses != {0x01, 0x02} or
                         io_write_addresses != {0x00, 0x01, 0x06} or
                         commands != list(range(0x100))),
        "source": str(SOUND_TRACE_DIR.relative_to(ROOT)).replace("\\", "/"),
        "sha256": {name: sha256(path.read_bytes())
                   for name, path in paths.items()},
        "commands_sent": len(commands),
        "observed_pc_values": len(pcs),
        "observed_instruction_starts": len(pcs & instruction_starts),
        "observed_static_code_bytes": len(pcs & code_bytes),
        "transition_pc_stack_read": {
            "pc": 0x0610,
            "addresses": transition_reads,
        },
        "program_read_edges": len(read_rows),
        "program_write_edges": len(write_rows),
        "io_read_edges": len(io_read_rows),
        "io_write_edges": len(io_write_rows),
        "program_read_unique_addresses": len(program_read_addresses),
        "program_write_unique_addresses": len(program_write_addresses),
        "io_read_ports": sorted(io_read_addresses),
        "io_write_ports": sorted(io_write_addresses),
    }


SOUND_STREAM_OPCODES = (
    (0x00, 0x07, 0x03B4, "note/key event; opcode `$01` имеет explicit duration byte", "1 или 2", "next"),
    (0x08, 0x0F, 0x04DF, "hold/rest с текущим pitch; `$09` имеет explicit duration byte", "1 или 2", "next"),
    (0x10, 0x17, 0x04E3, "выбрать 4-byte operator-level vector `$1678[index*4]`", "2", "next"),
    (0x18, 0x1F, 0x054B, "записать default duration в channel `+$08`", "2", "next"),
    (0x20, 0x27, 0x0556, "записать octave nibble в channel `+$07[7:4]`", "2", "next"),
    (0x28, 0x2F, 0x056A, "записать две articulation nibbles в channel `+$06`", "3", "next"),
    (0x30, 0x37, 0x057F, "загрузить 31-byte YM2151 instrument `$134C[index*31]`", "2", "next"),
    (0x38, 0x3F, 0x0635, "channel-relative YM2151 register,value", "3", "next"),
    (0x40, 0x47, 0x07DA, "пять global YM bytes: regs `$18,$1B,$19,$19` и `$F872`", "6", "next"),
    (0x48, 0x4F, 0x0801, "создать linked auxiliary envelope из `$19A4[index*4]`", "2", "next"),
    (0x50, 0x57, 0x0882, "удалить все linked auxiliary envelopes channel", "1", "next"),
    (0x58, 0x5F, 0x0644, "CALL relative word; target=opcode_address+signed_word", "3", "call"),
    (0x60, 0x67, 0x066A, "RETURN из per-channel stack `$FD80+channel*16`", "1", "return"),
    (0x68, 0x6F, 0x0686, "записать timing scale в channel `+$05`", "2", "next"),
    (0x70, 0x77, 0x068F, "JUMP relative word; target=opcode_address+signed_word", "3", "jump"),
    (0x78, 0x7F, 0x069C, "увеличить octave nibble на `$10`", "1", "next"),
    (0x80, 0x87, 0x06A8, "уменьшить octave nibble на `$10`", "1", "next"),
    (0x88, 0x8F, 0x06B4, "создать 16-byte pitch-transition object; три operands", "4", "next"),
    (0x90, 0xF7, 0x0E0C, "terminate channel через `$08FD`", "1", "stop"),
    (0xF8, 0xFF, 0x08FD, "terminate channel и освободить YM/channel links", "1", "stop"),
)


def sound_data_format_map(sound: bytes,
                          errors: list[str]) -> dict[str, object]:
    """Раскрыть command records и bytecode streams `$1000..$5781`."""
    word = lambda address: int.from_bytes(sound[address:address + 2], "little")
    signed_word = lambda address: int.from_bytes(
        sound[address:address + 2], "little", signed=True)
    commands = []
    roots: list[tuple[int, int, int]] = []
    record_bytes: set[int] = set()
    for command in range(0x80):
        record = word(0x1000 + command * 2)
        if not 0x1100 <= record <= 0x134B:
            errors.append(f"sound command `${command:02X}` record вне `$1100..$134B`")
            continue
        kind_byte = sound[record]
        high = kind_byte & 0xF0
        owner = command
        pointers: list[int] = []
        if high == 0x00:
            kind = "start"
            count = (kind_byte & 7) + 1
            length = 1 + count * 2
            pointer_at = record + 1
        elif high == 0x10:
            kind = "replace-owner"
            owner = sound[record + 1]
            count = (kind_byte & 7) + 1
            length = 2 + count * 2
            pointer_at = record + 2
        elif high == 0x20:
            kind = "fade-owner"
            owner = sound[record + 1]
            count = 0
            length = 4
            pointer_at = 0
        elif kind_byte >= 0x30:
            kind = "no-op"
            count = 0
            length = 1
            pointer_at = 0
        else:
            errors.append(f"sound command `${command:02X}` имеет type `${kind_byte:02X}`")
            kind = "invalid"
            count = 0
            length = 1
            pointer_at = 0
        for index in range(count):
            pointer = word(pointer_at + index * 2)
            pointers.append(pointer)
            roots.append((pointer, command, index))
            if not 0x1A0A <= pointer <= 0x5780:
                errors.append(f"sound stream root `${pointer:04X}` вне data region")
        record_bytes.update(range(record, record + length))
        item = {
            "base_command": command,
            "aliases": [command, command | 0x80],
            "record": record,
            "type": kind_byte,
            "kind": kind,
            "owner_command": owner,
            "stream_pointers": pointers,
        }
        if kind == "fade-owner":
            item["target_attenuation"] = sound[record + 2]
            item["duration_divisor"] = sound[record + 3]
        commands.append(item)

    record_padding = sorted(set(range(0x1100, 0x134C)) - record_bytes)
    if record_padding != [0x1101, 0x1102, 0x1103, 0x1104]:
        errors.append("sound command-record padding изменился")
    if len(commands) != 128 or len(roots) != 213 or len({x[0] for x in roots}) != 148:
        errors.append("sound command/root cardinality изменилась")

    # MAME read tap at `$0348 LD A,(HL)` observes actual stream opcode reads.
    dynamic_entries: set[int] = set()
    trace_path = SOUND_TRACE_DIR / "program_reads.csv"
    if trace_path.is_file():
        with trace_path.open(encoding="ascii", newline="") as handle:
            for row in csv.DictReader(handle):
                address = int(row["address"], 16)
                if row["pc"] == "0349" and address >= 0x1A0A:
                    dynamic_entries.add(address)

    root_addresses = {item[0] for item in roots}
    used: set[int] = set(root_addresses)  # priority byte каждого stream record
    states: set[tuple[int, tuple[int, ...]]] = set()
    queue = [(root + 1, ()) for root in root_addresses]
    queue.extend((entry, ()) for entry in dynamic_entries)
    group_counts: collections.Counter[int] = collections.Counter()
    bad_targets = []
    while queue:
        pc, stack = queue.pop()
        state = (pc, stack)
        if state in states:
            continue
        states.add(state)
        if not 0x1A0A <= pc <= 0x5781:
            bad_targets.append(pc)
            continue
        opcode = sound[pc]
        group = opcode >> 3
        group_counts[group] += 1
        if group == 0:
            size = 2 if (opcode & 7) == 1 else 1
        elif group in (1, 10, 12, 15, 16) or group >= 18:
            size = 1
        elif group in (2, 3, 4, 6, 9, 13):
            size = 2
        elif group in (5, 7, 11, 14):
            size = 3
        elif group == 8:
            size = 6
        elif group == 17:
            size = 4
        else:
            errors.append(f"sound bytecode group `${group:02X}` без size")
            break
        used.update(range(pc, pc + size))
        if group == 11:
            queue.append(((pc + signed_word(pc + 1)) & 0xFFFF,
                          stack + (pc + 3,)))
        elif group == 12:
            # Dynamic seed может начинаться внутри уже вызванной процедуры;
            # пустой stack тогда означает только конец этого локального walk.
            if stack:
                queue.append((stack[-1], stack[:-1]))
        elif group == 14:
            queue.append(((pc + signed_word(pc + 1)) & 0xFFFF, stack))
        elif group < 18:
            queue.append((pc + size, stack))
    if bad_targets:
        errors.append("sound bytecode targets вне `$1A0A..$5781`")

    orphan_ranges = []
    for address in range(0x1A0A, 0x5782):
        if address in used:
            continue
        if not orphan_ranges or address > orphan_ranges[-1][1] + 1:
            orphan_ranges.append([address, address])
        else:
            orphan_ranges[-1][1] = address
    expected_orphans = [
        [0x2CB2, 0x2CBD], [0x2F87, 0x2F89], [0x3344, 0x3344],
        [0x364F, 0x3651], [0x48B3, 0x48DB], [0x4B72, 0x4B72],
        [0x4BD5, 0x4BD5], [0x5321, 0x535A],
    ]
    if orphan_ranges != expected_orphans:
        errors.append("sound orphan bytecode ranges изменились")
    orphan_records = [{
        "start": start, "end": end,
        "raw": sound[start:end + 1].hex(" "),
        "meaning": "valid stream-bytecode bytes без inbound edge от command roots или MAME `$0349` trace",
    } for start, end in orphan_ranges]

    layouts = [
        {"start": 0x1000, "end": 0x10FF, "format": "128 little-endian command pointers; command bit 7 discarded by `SLA E`"},
        {"start": 0x1100, "end": 0x134B, "format": "99 shared variable-length command records; `$1101..$1104` inert padding"},
        {"start": 0x134C, "end": 0x1671, "format": "26 YM2151 instrument records ×31 bytes (30 consumed + byte30 reserved stride)"},
        {"start": 0x1672, "end": 0x1677, "format": "6-byte alignment padding, no Z80 consumer"},
        {"start": 0x1678, "end": 0x19A3, "format": "203 operator-level vectors ×4 bytes"},
        {"start": 0x19A4, "end": 0x1A07, "format": "25 auxiliary-envelope records ×4 bytes"},
        {"start": 0x1A08, "end": 0x1A09, "format": "2-byte alignment padding"},
        {"start": 0x1A0A, "end": 0x5780, "format": "148 rooted priority+bytecode streams and shared substreams"},
        {"start": 0x5781, "end": 0x5781, "format": "erased `$FF` terminal fetched by stream ending at `$5780`"},
    ]
    return {
        "verified": not bad_targets and orphan_ranges == expected_orphans,
        "layouts": layouts,
        "commands": commands,
        "unique_command_records": len({item["record"] for item in commands}),
        "stream_pointer_references": len(roots),
        "unique_stream_roots": len(root_addresses),
        "dynamic_stream_entries": len(dynamic_entries),
        "walk_states": len(states),
        "opcode_group_state_counts": {f"{group:02X}": count
                                      for group, count in sorted(group_counts.items())},
        "opcode_classes": [
            {"start": start, "end": end, "handler": handler,
             "meaning": meaning, "bytes": size, "flow": flow}
            for start, end, handler, meaning, size, flow in SOUND_STREAM_OPCODES
        ],
        "orphan_bytecode_blocks": orphan_records,
        "unclassified_bytes_1000_5781": 0,
    }


def tile_graphics_consumer_map(main: bytes,
                               errors: list[str]) -> dict[str, object]:
    """Связать все tile codes с 256 metatiles и ES layer descriptors."""
    metatile_data = main[0x30000:0x39000]
    if len(metatile_data) != 256 * 144:
        errors.append("metatile bank не равен `256*144` bytes")
    es = main[0x10000:0x20000]
    layer_specs = (
        ("tiles0_foreground", 0xC627, 0xD68E),
        ("tiles1_background", 0xD68F, 0xEB06),
    )
    layer_descriptors: dict[str, list[dict[str, int]]] = {}
    metatile_layer_consumers = {
        name: [[] for _ in range(256)] for name, _start, _end in layer_specs
    }


    for name, start, end in layer_specs:
        if (end - start + 1) % 2:
            errors.append(f"{name}: нечётный descriptor range")
        records = []
        for address in range(start, end + 1, 2):
            value = int.from_bytes(es[address:address + 2], "little")
            index = value & 0x3FFF
            if index >= 256:
                errors.append(f"{name}: metatile index `${index:04X}` >=256")
                continue
            record = {
                "address": address,
                "raw": value,
                "metatile": index,
                "flip_x": 1 if value & 0x4000 else 0,
                "flip_y": 1 if value & 0x8000 else 0,
            }
            records.append(record)
            metatile_layer_consumers[name][index].append(address)
        layer_descriptors[name] = records
    if (len(layer_descriptors["tiles0_foreground"]) != 2100 or
            len(layer_descriptors["tiles1_background"]) != 2620):
        errors.append("число foreground/background metatile descriptors изменилось")

    metatiles = []
    code_metatiles = [set() for _ in range(4096)]
    for index in range(256):
        cells = []
        for cell in range(48):
            offset = index * 144 + cell * 3
            raw_code = int.from_bytes(metatile_data[offset:offset + 2], "little")
            code = raw_code & 0x0FFF
            attribute = metatile_data[offset + 2]
            code_metatiles[code].add(index)
            cells.append({
                "cell": cell,
                "code": code,
                "flip_x": 1 if raw_code & 0x4000 else 0,
                "flip_y": 1 if raw_code & 0x8000 else 0,
                "attribute": attribute,
            })
        metatiles.append({
            "index": index,
            "physical": 0x30000 + index * 144,
            "cells": cells,
            "foreground_descriptor_addresses":
                metatile_layer_consumers["tiles0_foreground"][index],
            "background_descriptor_addresses":
                metatile_layer_consumers["tiles1_background"][index],
        })

    def code_map(layer: str) -> list[dict[str, object]]:
        result = []
        consumers = metatile_layer_consumers[layer]
        for code, indices in enumerate(code_metatiles):
            used = sorted(index for index in indices if consumers[index])
            result.append({
                "code": code,
                "metatiles": used,
                "descriptor_count": sum(len(consumers[index]) for index in used),
                "unused": not used,
            })
        return result

    tile0 = code_map("tiles0_foreground")
    tile1 = code_map("tiles1_background")
    return {
        "verified": not any(item["metatile"] >= 256
                            for records in layer_descriptors.values()
                            for item in records),
        "metatile_bank": {
            "physical_start": 0x30000,
            "physical_end": 0x38FFF,
            "record_count": 256,
            "record_size": 144,
            "cell_count": 48,
            "cell_format": "tile code word + attribute byte",
        },
        "layer_descriptor_ranges": {
            "tiles0_foreground": {"start": 0xC627, "end": 0xD68E,
                                    "count": 2100},
            "tiles1_background": {"start": 0xD68F, "end": 0xEB06,
                                    "count": 2620},
        },
        "metatiles": metatiles,
        "tiles0_codes": tile0,
        "tiles1_codes": tile1,
        "tiles0_used_codes": sum(not item["unused"] for item in tile0),
        "tiles1_used_codes": sum(not item["unused"] for item in tile1),
        "unclassified_tile_codes": 0,
    }


def intraprocedural_owner_map(runtime: "RecursiveV30") -> dict[int, list[int]]:
    """Построить ownership по CFG, не по числовой близости адресов.

    CALL target принадлежит вызываемой процедуре, а instruction после CALL —
    вызывающей. Прямой tail-JMP остаётся частью текущего пути; shared tails
    поэтому честно получают несколько owners.
    """
    result: dict[int, set[int]] = collections.defaultdict(set)
    for entry in sorted(runtime.function_entries):
        if entry not in runtime.instructions:
            continue
        queue = collections.deque((entry,))
        visited = set()
        while queue:
            address = queue.popleft()
            if address in visited or address not in runtime.instructions:
                continue
            visited.add(address)
            result[address].add(entry)
            instruction = runtime.instructions[address]
            next_address = address + instruction.size
            direct = (int(instruction.operands, 16) & 0xFFFF
                      if re.fullmatch(r"0x[0-9a-f]+", instruction.operands)
                      else None)
            mnemonic = instruction.mnemonic
            if mnemonic.startswith("ret") or mnemonic in ("iret", "hlt", "ljmp"):
                continue
            if mnemonic == "jmp":
                if direct is not None:
                    queue.append(direct)
                continue
            if (mnemonic.startswith("j") or mnemonic in ("loop", "loope",
                                                           "loopne", "jcxz")):
                if direct is not None:
                    queue.append(direct)
                queue.append(next_address)
                continue
            # Near CALL is summarized as ES-preserving here. All explicit ES
            # mutations are separately delimited by push/set/pop invariants.
            queue.append(next_address)
    return {address: sorted(owners) for address, owners in sorted(result.items())}


def sprite_direct_descriptor_map(main: bytes, runtime: "RecursiveV30",
                                 errors: list[str]) -> dict[str, object]:
    """Связать доказанные literal-BX renderer calls со sprite codes.

    Это строгий нижний предел полной карты. Никакой похожий на descriptor
    шестибайтный фрагмент не принимается без достигнутого renderer consumer.
    Косвенные pointers из object fields будут добавляться отдельным
    producer/data-flow проходом.
    """
    render_counts = {0x1BCC: 1, 0x1BE9: 1, 0x1C1B: 2, 0x1CA6: 2}
    order = sorted(runtime.instructions)
    positions = {address: index for index, address in enumerate(order)}
    calls = sorted((source, target) for source, target in runtime.calls
                   if target in render_counts)
    es = main[0x10000:0x20000]

    def table_words(base: int, indices) -> set[int]:
        """Прочитать только доказанные word-элементы World ROM table."""
        return {int.from_bytes(es[base + 2 * index:base + 2 * index + 2],
                               "little")
                for index in indices}

    def table_word(base: int, index: int) -> int:
        return int.from_bytes(es[base + 2 * index:base + 2 * index + 2],
                              "little")

    # Точные domains pointer-таблиц. Границы индексов здесь следуют из
    # CMP/reset state machines `$283B..$2AB3`, а не из фильтрации по внешнему
    # виду данных. Вложенная таблица `$1488` сначала выбирается byte-map
    # `$15AE`, затем индексируется фазой 0..3.
    exact_table_domains: dict[int, set[int]] = {
        # Два attract constructors `$07EC/$0D33`: семь 10-byte records
        # `ES:$08C4`, descriptor pointer находится в record+$06.
        0x0A08: {table_word(0x08C4 + 10 * index, 3)
                 for index in range(7)},
        0x0A6D: {table_word(0x08C4 + 10 * index, 3)
                 for index in range(7)},
        # Player launch `$10C2`: 8-byte records; `+$04` primary descriptor,
        # `+$06` four-frame engine descriptor. Terminal primary zero excluded.
        0x1F83: {table_word(0x10C2 + 8 * index, 2)
                 for index in range(14)},
        0x1FA3: {table_word(0x10C2 + 8 * index, 3) + phase
                 for index in range(14) for phase in (0, 6, 12, 18)},
        # R-9 explosion stream: `(descriptor,duration)` от `$1318` до
        # нулевой duration. Последняя `$1362` также рисуется перед terminal.
        0x2318: set(table_words(0x1318, range(0, 16, 2))),
        # Title/player death composite: countdown `$17..1`, bases by facing.
        0x27F7: {base + 6 * phase
                 for base in (0x1398, 0x13E0) for phase in range(12)},
        0x280C: {base + 6 * phase
                 for base in (0x1398, 0x13E0) for phase in range(12)},
        # Двойной composite stream `$1960`: pointer/duration pairs; второй
        # renderer получает соседнюю композицию по `pointer+$0C`.
        # The last pointer is rendered once before its following zero duration
        # terminates the script, so all six records belong to the domain.
        0x32CA: set(table_words(0x1960, range(0, 12, 2))),
        0x32D1: {value + 0x0C
                 for value in table_words(0x1960, range(0, 10, 2))},
        # `$3133` берёт power/width из шестисловной `$188C`; нулевой вариант
        # уходит в terminal до render. Остальные дают 5 phases × 2 subframes.
        0x3201: set(table_words(0x1898, range(10))),
        # Projectile cleanup `$3D17/$3D37`: базы `$2000/$2018`, countdown 3.
        0x3D65: {base + 6 * phase
                 for base in (0x2000, 0x2018) for phase in (1, 2, 3)},
        # Общий projectile handler `$3EC4`; все шесть initializers задают
        # descriptor field литералом перед state transition.
        0x3ED3: {0x2030, 0x2036, 0x203C, 0x2042, 0x2048},
        0x2874: table_words(0x144C, range(6)),
        0x2939: set().union(*(table_words(base, range(6))
                             for base in (0x1458, 0x1464, 0x1470, 0x147C))),
        0x29D5: set().union(*(table_words(base, range(6))
                             for base in (0x1458, 0x1470))),
        0x2A0C: table_words(0x1440, range(6)),
        0x2A5E: table_words(0x149A, range(8)),
        0x2A8C: set().union(*(table_words(base, range(6))
                             for base in (0x1458, 0x1470))),
        0x2AB0: table_words(0x144C, range(6)),
        # `$4311`: phase всегда even 0/2/4/6. Три terrain-ветви читают
        # descriptor pointers из различных полей одной 6-byte записи.
        0x4433: ({int.from_bytes(es[base + 6 * phase:
                                       base + 6 * phase + 2], "little")
                  for base in (0x205A, 0x2060)
                  for phase in (0, 2, 4, 6)} |
                 {int.from_bytes(es[0x209A + phase:
                                    0x209C + phase], "little")
                  for phase in (0, 2, 4, 6)}),
        # `$44EE`: поле `$0C` переключается XOR 2, поэтому ровно две words.
        0x4536: {int.from_bytes(es[0x20A2 + phase:
                                      0x20A4 + phase], "little")
                 for phase in (0, 2)},
        # `$4E0F/$4E42`: четыре инициализатора указателя, optional mirror
        # `+$0C` и VBlank offset 0/6.
        0x4E57: {base + mirror + frame
                 for base in (0x267C, 0x2694)
                 for mirror in (0, 0x0C)
                 for frame in (0, 6)},
        # `$6F89->$F9F0`: четыре 14-byte spawn records `$9384`; word #5
        # задаёт base 16-word descriptor table. `$7009` берёт +2/+4,
        # animation/death states `$709F/$7123` проходят offsets 0..$1E.
        0x7009: {table_word(table_word(0x9384 + 14 * record, 5), phase)
                 for record in range(4) for phase in (1, 2)},
        0x709F: {table_word(table_word(0x9384 + 14 * record, 5), phase)
                 for record in range(4) for phase in range(16)},
        0x7123: {table_word(table_word(0x9384 + 14 * record, 5), phase)
                 for record in range(4) for phase in range(16)},
        # `$72D2`: orientation byte is exactly 0/2. It selects one of two
        # words `$32BE/$32C2`; the local phase cycles 0,6,12,18,24.
        0x7318: {table_word(0x32BE, orientation) + 6 * phase
                 for orientation in (0, 2) for phase in range(5)},
        # `$779E` is a flash wrapper. Its five callers construct BX from the
        # literals below and closed counter masks (`$1C` or `$18`).
        0x7523: {base + 6 * phase
                 for base in (0x334E, 0x337E) for phase in range(8)},
        0x75B2: (0x334E, 0x337E),
        0x766C: {base + 6 * phase
                 for base in (0x33AE, 0x33C6) for phase in range(4)},
        0x76C2: {base + phase
                 for base in (0x33DE, 0x3402) for phase in (0, 6)},
        0x7731: {base + 6 * phase
                 for base in (0x33EA, 0x340E) for phase in range(4)},
        # `$7D68` stores object+$28 as exactly 0/1. All `$8035` callers use
        # 12-byte descriptor groups; two states add the four `$30` phases.
        0x7DD2: (0x37E6, 0x37F2),
        0x7E3C: (0x37E6, 0x37F2),
        0x7EA7: tuple(base + phase
                      for base in (0x37E6, 0x37F2)
                      for phase in (0, 24, 48, 72)),
        0x7F02: (0x382E, 0x383A),
        0x7F6E: tuple(base + phase
                      for base in (0x37E6, 0x37F2)
                      for phase in (0, 24, 48, 72)),
        0x7FC4: (0x37E6, 0x37F2),
        # Child `$83DF`: countdown 15..1 selects four frames from one of the
        # two literal bases written at `$83C2/$83CD`.
        0x83FB: {base + phase
                 for base in (0x38F6, 0x390E)
                 for phase in (0, 6, 12, 18)},
        # `$8409` wrapper callers select descriptor pointers from the four
        # 4-word direction tables `$3866..$388E`.
        0x8233: set().union(*(table_words(base, range(4))
                             for base in (0x3866, 0x386E,
                                          0x3876, 0x387E))),
        0x830F: set().union(*(table_words(base, range(4))
                             for base in (0x3886, 0x388E))),
        # Direction helper `$1D89` yields 16 multiples of four. `$8930`
        # halves that code and selects one of 16 descriptor bases `$3B32`;
        # `$8950` adds the closed four-frame animation phase.
        0x8963: {table_word(0x3B32, direction) + 6 * phase
                 for direction in range(16) for phase in range(4)},
        # Projectile `$9674`: the same 16 direction codes select the word
        # table `$428C`; VBlank bit 3 switches to the adjacent frame.
        0x9703: {table_word(0x428C, direction) + frame
                 for direction in range(16) for frame in (0, 6)},
        # Boss child constructor `$99D7`: 18 ten-byte records `$43AC`, with
        # the persistent descriptor pointer in record+$04.
        0xA03E: {table_word(0x43AC + 10 * record, 2)
                 for record in range(18)},
        0xA0A0: {table_word(0x43AC + 10 * record, 2)
                 for record in range(18)},
        0xA115: {table_word(0x43AC + 10 * record, 2)
                 for record in range(18)},
        # `$A133/$A1A3`: direction helper result 0,$04..$3C is halved,
        # therefore it indexes all sixteen words of `$4CC6` exactly once.
        0xA153: table_words(0x4CC6, range(16)),
        0xA1C8: table_words(0x4CC6, range(16)),
        # Attached boss part `$AC4C`: `$1D89` indexes 16 four-byte records;
        # the descriptor pointer is the second word at `$5872+4*n`.
        0xAC9E: {table_word(0x5872 + 4 * direction, 0)
                 for direction in range(16)},
        0xACAA: {table_word(0x5872 + 4 * direction, 0)
                 for direction in range(16)},
        # Common stage-object renderer `$BC95`. Constructors `$BB40..$BC63`
        # write the listed literal bases; only `$BC08` enables the 16-frame
        # VBlank phase, and only `$BBAE` enables the second component +$06.
        0xBCB7: ({0x616C, 0x6172, 0x6178, 0x6184, 0x6190, 0x619C,
                  0x61A8, 0x61B4, 0x61C0, 0x61C6, 0x622C, 0x6232,
                  0x6238, 0x623E} |
                 {0x61CC + 6 * phase for phase in range(16)}),
        0xBCC7: {0x61BA},
        # Spawned child `$BDB2`: direction code is halved and selects all
        # sixteen words of `$625C`.
        0xBDF4: table_words(0x625C, range(16)),
        # `$BEBD` chooses one of four persistent descriptors `$6312`; F5C1
        # advances only motion-script fields `$12/$14/$17`, not object+$34.
        0xC04E: table_words(0x6312, range(4)),
        0xC078: table_words(0x6312, range(4)),
        # Paired late-stage bodies `$D0FF/$D188`: constructors write one of
        # two literal descriptor addresses; the flash branches preserve BX.
        0xD127: {0x7A6C, 0x7A78},
        0xD1C9: {0x7A6C, 0x7A78},
        # Three `$D28F` children share direction table `$7A94`.
        0xD2CB: table_words(0x7A94, range(16)),
        # `$D596..$D5D7` select five 16-word direction tables. The death
        # state `$D71D` retains the same object+$30 base.
        0xD63C: set().union(*(table_words(base, range(16))
                              for base in (0x7B4E, 0x7B6E, 0x7B8E,
                                           0x7BAE, 0x7BCE))),
        0xD75F: set().union(*(table_words(base, range(16))
                              for base in (0x7B4E, 0x7B6E, 0x7B8E,
                                           0x7BAE, 0x7BCE))),
        # Spawn descriptors for `$D7B9` are word #2 of nonzero six-byte
        # records selected through six 16-word pointer tables `$7C30..$7CD0`.
        0xD839: {
            table_word(record_pointer, 2)
            for pointer_table in (0x7C30, 0x7C50, 0x7C70,
                                  0x7C90, 0x7CB0, 0x7CD0)
            for direction in range(16)
            for record_pointer in (table_word(pointer_table, direction),)
            if record_pointer
        },
        # `$D86D` chooses one of two explosion bases; countdown mask `$0E`
        # produces the eight six-byte phases.
        0xD8A2: {base + 6 * phase
                 for base in (0x7DE6, 0x7E16) for phase in range(8)},
        # `$7E56` threshold records only assign low-byte indices
        # 0,4,6,8,10 before the `$FFFF` sentinel.
        0xD93D: table_words(0x7E9A, (0, 2, 3, 4, 5)),
        # Four constructors and four VBlank phases feed `$DBB5`.
        0xDBEC: {base + 6 * phase
                 for base in (0x8006, 0x801E, 0x8036, 0x804E)
                 for phase in range(4)},
        0xDE25: {0x81BE},
        # Direction-indexed tables for the two final-stage object families.
        0xE18A: table_words(0x81FA, range(16)),
        0xE2DD: set(table_words(0x8258, range(16))) |
                set(table_words(0x8278, range(16))),
        # `$E568`: RNG low five bits select 32 four-byte records `$83AC`;
        # object+$34 is their first word.
        0xE5DD: {table_word(0x83AC + 4 * record, 0)
                 for record in range(32)},
        # Walker turn streams: word pointers, sentinel zero не рисуется.
        0x5AFE: ({value for value in table_words(0x292A, range(4)) if value} |
                 {value for value in table_words(0x2932, range(4)) if value}),
        0x5C53: ({value for value in table_words(0x292A, range(4)) if value} |
                 {value for value in table_words(0x2932, range(4)) if value}),
        # Все producers общего `$661A` wrapper. Word-таблицы индексируются
        # только масками `$0C/$38`, остальные callers выбирают literals.
        0x61F8: set().union(*(table_words(base, range(4))
                              for base in (0x2B60, 0x2B68))),
        0x6265: set(table_words(0x2B70, range(8))),
        0x62D8: {0x2B80, 0x2BE0},
        0x6330: set().union(*(table_words(base, range(4))
                              for base in (0x2B60, 0x2B68))),
        0x63CD: {0x2BC8, 0x2BD4, 0x2C28, 0x2C34},
        0x649A: {0x2BC8, 0x2BD4, 0x2C28, 0x2C34},
        0x6544: set().union(*(table_words(base, range(4))
                              for base in (0x2B60, 0x2B68))),
        0x65B2: {0x2C48, 0x2C4E, 0x2C60, 0x2C66},
        # `$8F65` записывает byte phase из `ES:$3F76[CX&$0F]`;
        # `$9028..$9045` использует stride 24 и 4 VBlank subframes.
        0x9049: {0x4006 + 24 * phase + subframe
                 for phase in set(es[0x3F76:0x3F86])
                 for subframe in (0, 6, 12, 18)},
        # `$9055` maps the four approach directions and target side through
        # the 16-word matrix `$3FC6`. Zero cells are the impossible
        # same-axis combinations; every populated cell points to two words,
        # selected by countdown bit `$10` at `$90B2`.
        0x90C2: {
            table_word(pointer_table, frame)
            for matrix_index in range(16)
            for pointer_table in (table_word(0x3FC6, matrix_index),)
            if pointer_table
            for frame in range(2)
        },
        # `$9849/$98D4`: modulo-3 state индексирует ровно три pointers.
        0x9855: set(table_words(0x4374, range(3))),
        0x98E0: set(table_words(0x4374, range(3))),
        # `$CF07..$CF21`: `(timer-$60)&$0C`, умножение на 3.
        0xCF21: {0x79DC + phase for phase in (0, 12, 24, 36)},
    }

    def duration_pointer_stream(base: int) -> set[int]:
        """Дескрипторы 4-byte `(duration,pointer)` stream до sentinel."""
        pointers: set[int] = set()
        cursor = base
        while table_word(cursor, 0):
            pointers.add(table_word(cursor, 1))
            cursor += 4
            if cursor >= 0x10000:
                raise ValueError(f"sprite stream ${base:04X} не завершён")
        return pointers

    def zero_terminated_word_pointer_stream(base: int) -> set[int]:
        """Word-pointer stream; terminal zero is tested before rendering."""
        pointers: set[int] = set()
        cursor = base
        while True:
            pointer = table_word(cursor, 0)
            if not pointer:
                return pointers
            pointers.add(pointer)
            cursor += 2
            if cursor >= 0x10000:
                raise ValueError(f"sprite pointer stream ${base:04X} не завершён")

    def cumulative_timeline_descriptors(base: int) -> set[int]:
        """Descriptors of 8-byte cumulative-time records used by `$FB53`."""
        descriptors: set[int] = set()
        cursor = base
        for _ in range(256):
            descriptors.add(table_word(cursor, 3))
            next_threshold = table_word(cursor, 4)
            if next_threshold & 0x8000:
                return descriptors
            cursor += 8
        raise ValueError(f"sprite timeline ${base:04X} не завершён")

    explosion_streams = set().union(*(
        duration_pointer_stream(base)
        for base in (0x8506, 0x8530, 0x8552, 0x8574)))
    exact_table_domains[0xE731] = set(duration_pointer_stream(0x8506))
    exact_table_domains[0xE7E1] = explosion_streams
    exact_table_domains[0xE83A] = set(duration_pointer_stream(0x85FA))
    # `$DAC8` chooses four 8-byte records; word #2 is a zero-terminated list
    # of composite descriptor pointers. `$DB42` renders its second component.
    db_roots = {table_word(0x7ED2 + 8 * variant, 2)
                for variant in range(4)}
    db_descriptors = set().union(*(
        zero_terminated_word_pointer_stream(root) for root in db_roots))
    exact_table_domains[0xDB39] = db_descriptors
    exact_table_domains[0xDB42] = {pointer + 6
                                    for pointer in db_descriptors}
    # `$FB10` traverses six-byte spawn records `$945C` until root zero. Every
    # root addresses 8-byte cumulative-time records; a high-bit next threshold
    # is the terminal state that remains active until the object leaves screen.
    fb_roots: set[int] = set()
    cursor = 0x945C
    while table_word(cursor, 0):
        fb_roots.add(table_word(cursor, 0))
        cursor += 6
    exact_table_domains[0xFB7F] = set().union(*(
        cumulative_timeline_descriptors(root) for root in fb_roots))
    for call_site, selector_indices in {
            0x28EE: (0, 1, 2, 4, 5, 6, 8, 9, 10),
            0x2978: tuple(range(16)),
    }.items():
        selectors = {es[0x15AE + index] for index in selector_indices}
        exact_table_domains[call_site] = set().union(*(
            table_words(table_word(0x1488, selector), range(4))
            for selector in selectors))

    # `$583F..$5857`: исходный low-nibble и VBlank bit выбирают одну из 16
    # words; high byte этой word становится ограниченной sprite phase.
    phase_values_58ce = {
        int.from_bytes(es[0x27FE + offset:0x2800 + offset], "little") >> 8
        for offset in range(0, 32, 2)
    }
    exact_table_domains[0x58CE] = {
        0x278C + 3 * phase for phase in phase_values_58ce
    }
    # Sprite phase/table indices в этой игре не требуют более 256 вариантов.
    # Более широкий набор означает потерянную зависимость регистров, а не
    # полезное точное перечисление, и остаётся unresolved для следующего pass.
    value_limit = 256
    mask_cache: dict[int, set[int] | None] = {}

    def binary(left: set[int] | None, right: set[int] | None,
               operation) -> set[int] | None:
        if left is None or right is None or len(left) * len(right) > value_limit:
            return None
        values = {operation(a, b) & 0xFFFF for a in left for b in right}
        return values if len(values) <= value_limit else None

    def masked_unknown(mask: int) -> set[int] | None:
        if mask not in mask_cache:
            # Результаты `unknown & mask` — все submasks данного mask; это
            # эквивалентно перебору 65536 words, но ограничено `2^popcount`.
            bits = [1 << bit for bit in range(16) if mask & (1 << bit)]
            if 1 << len(bits) > value_limit:
                mask_cache[mask] = None
            else:
                values = {0}
                for bit in bits:
                    values |= {value | bit for value in values}
                mask_cache[mask] = values
        return mask_cache[mask]

    def evaluate_bx(block: list[Instruction]) -> set[int] | None:
        """Finite-set abstract execution для straight-line address setup."""
        registers: dict[str, set[int] | None] = {
            name: None for name in ("ax", "bx", "cx", "dx", "si", "di")
        }
        byte_parts: dict[str, dict[str, set[int] | None]] = {
            name: {"l": None, "h": None}
            for name in ("ax", "bx", "cx", "dx")
        }
        byte_parent = {"al": ("ax", "l"), "ah": ("ax", "h"),
                       "bl": ("bx", "l"), "bh": ("bx", "h"),
                       "cl": ("cx", "l"), "ch": ("cx", "h"),
                       "dl": ("dx", "l"), "dh": ("dx", "h")}

        def reg_value(name: str) -> set[int] | None:
            if name in registers:
                values = registers[name]
                if values is not None or name not in byte_parts:
                    return values
                low, high = byte_parts[name]["l"], byte_parts[name]["h"]
                if low is None or high is None or len(low) * len(high) > value_limit:
                    return None
                return {(hi << 8) | lo for lo in low for hi in high}
            parent_side = byte_parent.get(name)
            if parent_side is None:
                return None
            parent, side = parent_side
            part = byte_parts[parent][side]
            if part is not None:
                return part
            values = registers[parent]
            if values is not None:
                return {((value >> 8) if side == "h" else value) & 0xFF
                        for value in values}
            return None

        def set_reg(name: str, values: set[int] | None) -> None:
            if name in registers:
                registers[name] = values
                if name in byte_parts:
                    byte_parts[name]["l"] = (None if values is None else
                                                {value & 0xFF for value in values})
                    byte_parts[name]["h"] = (None if values is None else
                                                {(value >> 8) & 0xFF for value in values})
                return
            parent_side = byte_parent.get(name)
            if parent_side is None:
                return
            parent, side = parent_side
            byte_parts[parent][side] = values
            registers[parent] = None

        def source_values(text: str) -> set[int] | None:
            if text in registers or text in ("al", "ah", "bl", "bh", "cl", "ch", "dl", "dh"):
                return reg_value(text)
            match = re.fullmatch(r"0x([0-9a-f]+)|(-?[0-9]+)", text)
            if match:
                value = (int(match.group(1), 16) if match.group(1) else
                         int(match.group(2)))
                return {value & 0xFFFF}
            match = re.fullmatch(r"word ptr es:\[([^]]+)\]", text)
            if match:
                addresses = expression_values(match.group(1))
                if addresses is None:
                    return None
                return {int.from_bytes(es[address:address + 2], "little")
                        for address in addresses if address <= 0xFFFE}
            match = re.fullmatch(r"byte ptr es:\[([^]]+)\]", text)
            if match:
                addresses = expression_values(match.group(1))
                if addresses is None:
                    return None
                return {es[address] for address in addresses}
            return None

        def expression_values(text: str) -> set[int] | None:
            parts = re.findall(r"[+-]?\s*(?:0x[0-9a-f]+|[a-z]{2})", text)
            if not parts:
                return None
            result: set[int] | None = {0}
            for part in parts:
                compact = part.replace(" ", "")
                sign = -1 if compact.startswith("-") else 1
                token = compact.lstrip("+-")
                values = source_values(token)
                if values is None:
                    return None
                result = binary(result, values,
                                (lambda a, b: a - b) if sign < 0 else
                                (lambda a, b: a + b))
            return result

        for item in block:
            operands = [part.strip() for part in item.operands.split(",", 1)]
            if len(operands) != 2:
                if item.mnemonic in ("inc", "dec") and operands:
                    current = reg_value(operands[0])
                    set_reg(operands[0], binary(current, {1},
                            (lambda a, b: a + b) if item.mnemonic == "inc" else
                            (lambda a, b: a - b)))
                continue
            destination, source = operands
            if destination not in registers and destination not in (
                    "al", "ah", "bl", "bh", "cl", "ch", "dl", "dh"):
                continue
            if item.mnemonic == "mov":
                values = source_values(source)
                if destination in byte_parent and values is None:
                    values = set(range(256))
                set_reg(destination, values)
            elif item.mnemonic == "xor" and destination == source:
                set_reg(destination, {0})
            elif item.mnemonic in ("add", "sub"):
                left, right = reg_value(destination), source_values(source)
                set_reg(destination, binary(left, right,
                        (lambda a, b: a + b) if item.mnemonic == "add" else
                        (lambda a, b: a - b)))
            elif item.mnemonic == "and":
                right = source_values(source)
                if right is not None and len(right) == 1:
                    mask = next(iter(right))
                    left = reg_value(destination)
                    values = (masked_unknown(mask) if left is None else
                              {value & mask for value in left})
                    set_reg(destination, values)
                else:
                    set_reg(destination, None)
            elif item.mnemonic in ("shl", "shr", "sar"):
                left, right = reg_value(destination), source_values(source)
                if item.mnemonic == "shl":
                    operation = lambda a, b: a << b
                elif item.mnemonic == "shr":
                    operation = lambda a, b: a >> b
                else:
                    operation = lambda a, b: ((a - 0x10000) if a & 0x8000 else a) >> b
                set_reg(destination, binary(left, right, operation))
            else:
                set_reg(destination, None)
        return registers["bx"]

    symbolic_diagnostics: dict[int, dict[str, object]] = {}
    owner_map = intraprocedural_owner_map(runtime)

    def evaluate_bx_symbolic(block: list[Instruction],
                             call_site: int) -> set[int] | None:
        """Точный bit-vector expression pass с сохранением корреляций.

        Неизвестное RAM/object поле становится переменной. Если декартово
        пространство всех переменных не превышает 65536, перебирается весь
        домен, поэтому итоговый набор BX является точным, не sample/trace.
        """
        Expr = tuple
        registers: dict[str, Expr] = {}
        variables: dict[str, int] = {}
        explicit_domains: dict[str, tuple[int, ...]] = {}
        byte_parent = {"al": ("ax", False), "ah": ("ax", True),
                       "bl": ("bx", False), "bh": ("bx", True),
                       "cl": ("cx", False), "ch": ("cx", True),
                       "dl": ("dx", False), "dh": ("dx", True)}

        def const(value: int) -> Expr:
            return ("const", value & 0xFFFF)

        def variable(key: str, bits: int) -> Expr:
            variables.setdefault(key, bits)
            return ("var", key, bits)

        def contains_surjective_timer(node: Expr) -> bool:
            """True, если expression остаётся bijective по VBlank word."""
            if node[0] == "var":
                return node[1] == "mem:word ptr [0x2eb6]"
            if node[0] in ("add", "sub"):
                return (contains_surjective_timer(node[1]) or
                        contains_surjective_timer(node[2]))
            return False

        def reg(name: str) -> Expr:
            if name in byte_parent:
                parent, high = byte_parent[name]
                side = 1 if high else 0
                parent_expr = registers.get(
                    parent, variable(f"entry:{parent}", 16))
                if parent_expr[0] == "setbyte" and parent_expr[3] == side:
                    return ("byte", parent_expr[2], 0)
                if parent_expr[0] == "makeword":
                    return ("byte", parent_expr[2] if high else parent_expr[1], 0)
                return ("byte", parent_expr, side)
            return registers.get(name, variable(f"entry:{name}", 16))

        def assign(name: str, expression: Expr) -> None:
            if name in byte_parent:
                parent, high = byte_parent[name]
                old = reg(parent)
                side = 1 if high else 0
                if old[0] == "setbyte" and old[3] != side:
                    low = expression if side == 0 else old[2]
                    high_expr = expression if side == 1 else old[2]
                    registers[parent] = ("makeword", low, high_expr)
                else:
                    registers[parent] = ("setbyte", old, expression, side)
            else:
                registers[name] = expression

        def parse_expression(text: str, site: int) -> Expr | None:
            parts = re.findall(r"[+-]?\s*(?:0x[0-9a-f]+|[a-z]{2})", text)
            if not parts:
                return None
            expression: Expr = const(0)
            for part in parts:
                compact = part.replace(" ", "")
                operation = "sub" if compact.startswith("-") else "add"
                token = compact.lstrip("+-")
                if token.startswith("0x"):
                    value = const(int(token, 16))
                else:
                    value = reg(token)
                expression = (operation, expression, value)
            return expression

        def source(text: str, site: int) -> Expr:
            if text in ("ax", "bx", "cx", "dx", "si", "di",
                        "al", "ah", "bl", "bh", "cl", "ch", "dl", "dh"):
                return reg(text)
            match = re.fullmatch(r"0x([0-9a-f]+)|(-?[0-9]+)", text)
            if match:
                value = (int(match.group(1), 16) if match.group(1) else
                         int(match.group(2)))
                return const(value)
            match = re.fullmatch(r"(word|byte) ptr es:\[([^]]+)\]", text)
            if match:
                address = parse_expression(match.group(2), site)
                if address is not None:
                    return ("rom16" if match.group(1) == "word" else "rom8",
                            address)
            bits = 8 if text.startswith("byte ptr") else 16
            # Одинаковый operand в straight-line block означает то же чтение;
            # site включается только для безадресных/неразобранных operands.
            key = f"mem:{text}" if "[" in text else f"site:{site:04X}:{text}"
            return variable(key, bits)

        for item in block:
            operands = [part.strip() for part in item.operands.split(",", 1)]
            if len(operands) == 1 and operands[0] in (
                    "ax", "bx", "cx", "dx", "si", "di"):
                if item.mnemonic == "inc":
                    assign(operands[0], ("add", reg(operands[0]), const(1)))
                elif item.mnemonic == "dec":
                    assign(operands[0], ("sub", reg(operands[0]), const(1)))
                continue
            if len(operands) != 2:
                continue
            destination, operand = operands
            if destination not in ("ax", "bx", "cx", "dx", "si", "di",
                                   "al", "ah", "bl", "bh", "cl", "ch", "dl", "dh"):
                continue
            if item.mnemonic == "mov":
                assign(destination, source(operand, item.address))
            elif item.mnemonic == "xor" and destination == operand:
                assign(destination, const(0))
            elif item.mnemonic in ("add", "sub", "and", "or", "xor",
                                   "shl", "shr", "sar"):
                left = reg(destination)
                right = source(operand, item.address)
                if (item.mnemonic == "and" and destination in
                        ("ax", "bx", "cx", "dx", "si", "di") and
                        right[0] == "const" and
                        contains_surjective_timer(left)):
                    mask = right[1]
                    values = tuple(sorted({value & mask
                                           for value in range(0x10000)}))
                    key = f"timer-mask:{item.address:04X}"
                    variables[key] = 16
                    explicit_domains[key] = values
                    assign(destination, ("var", key, 16))
                else:
                    assign(destination, (item.mnemonic, left, right))

        expression = registers.get("bx")
        if expression is None:
            symbolic_diagnostics[call_site] = {"reason": "BX never assigned"}
            return None

        referenced: set[str] = set()

        def collect(node: Expr) -> None:
            if node[0] == "var":
                referenced.add(node[1])
            for child in node[1:]:
                if isinstance(child, tuple):
                    collect(child)

        collect(expression)
        domain_size = math.prod(len(explicit_domains[name])
                                if name in explicit_domains else
                                1 << variables[name] for name in referenced)
        if domain_size > 0x10000:
            symbolic_diagnostics[call_site] = {
                "reason": "symbolic Cartesian domain too large",
                "variables": {name: variables[name] for name in sorted(referenced)},
                "domain_size": domain_size,
                "expression": repr(expression),
            }
            return None

        def evaluate(node: Expr, environment: dict[str, int]) -> int:
            kind = node[0]
            if kind == "const":
                return node[1]
            if kind == "var":
                return environment[node[1]]
            if kind == "byte":
                value = evaluate(node[1], environment)
                return (value >> 8) & 0xFF if node[2] else value & 0xFF
            if kind == "setbyte":
                old = evaluate(node[1], environment)
                byte = evaluate(node[2], environment) & 0xFF
                return (((byte << 8) | (old & 0xFF)) if node[3] else
                        ((old & 0xFF00) | byte))
            if kind == "makeword":
                return ((evaluate(node[2], environment) & 0xFF) << 8) | (
                    evaluate(node[1], environment) & 0xFF)
            if kind in ("rom16", "rom8"):
                address = evaluate(node[1], environment) & 0xFFFF
                return (int.from_bytes(es[address:address + 2], "little")
                        if kind == "rom16" and address <= 0xFFFE else es[address])
            left, right = evaluate(node[1], environment), evaluate(node[2], environment)
            if kind == "add": result = left + right
            elif kind == "sub": result = left - right
            elif kind == "and": result = left & right
            elif kind == "or": result = left | right
            elif kind == "xor": result = left ^ right
            elif kind == "shl": result = left << (right & 0x1F)
            elif kind == "shr": result = left >> (right & 0x1F)
            elif kind == "sar":
                signed = left - 0x10000 if left & 0x8000 else left
                result = signed >> (right & 0x1F)
            else: raise ValueError(f"неизвестный symbolic op {kind}")
            return result & 0xFFFF

        names = sorted(referenced)
        domains = [explicit_domains.get(name, range(1 << variables[name]))
                   for name in names]
        values = {evaluate(expression, dict(zip(names, combination)))
                  for combination in itertools.product(*domains)}
        symbolic_diagnostics[call_site] = {
            "reason": "resolved" if len(values) <= 0x1000 else
                      "too many distinct BX values",
            "variables": {name: variables[name] for name in names},
            "domain_size": domain_size,
            "value_count": len(values),
            "expression": repr(expression),
        }
        # Relational symbolic domain сохраняет зависимости и допускает более
        # широкий точный результат, чем non-relational fallback.
        return values if len(values) <= 0x1000 else None

    def block_before(site: int) -> list[Instruction]:
        position = positions[site]
        start = position
        while start and position - start < 96:
            previous = runtime.instructions[order[start - 1]]
            previous_call_target = None
            if (previous.mnemonic == "call" and
                    re.fullmatch(r"0x[0-9a-f]+", previous.operands)):
                previous_call_target = int(previous.operands, 16) & 0xFFFF
            if (previous.mnemonic.startswith("ret") or
                    previous.mnemonic in ("jmp", "iret") or
                    (previous.mnemonic == "call" and
                     previous_call_target not in render_counts)):
                break
            start -= 1
        return [runtime.instructions[address]
                for address in order[start:position]]

    domain_cache: dict[int, set[int] | None] = {}

    def local_domain(site: int, resolving: set[int] | None = None) -> set[int] | None:
        if site in domain_cache:
            cached = domain_cache[site]
            return None if cached is None else set(cached)
        resolving = set() if resolving is None else set(resolving)
        if site in resolving:
            return None
        resolving.add(site)
        if site in SPRITE_SAME_BX_CALL:
            values = local_domain(SPRITE_SAME_BX_CALL[site], resolving)
            domain_cache[site] = None if values is None else set(values)
            return values
        if site in SPRITE_EXACT_BX_BY_CALL:
            values = set(SPRITE_EXACT_BX_BY_CALL[site])
            domain_cache[site] = set(values)
            return values
        if site in exact_table_domains:
            values = set(exact_table_domains[site])
            domain_cache[site] = set(values)
            return values
        block = block_before(site)
        values = evaluate_bx_symbolic(block, site)
        if values is None:
            values = evaluate_bx(block)
        domain_cache[site] = None if values is None else set(values)
        return values

    calls_by_target: dict[int, list[int]] = collections.defaultdict(list)
    for call_source, call_target in runtime.calls:
        calls_by_target[call_target].append(call_source)

    def caller_domain(site: int, visited: set[int] | None = None) -> set[int] | None:
        """Продолжить BX через direct callers общего render-helper."""
        visited = set() if visited is None else set(visited)
        if site in visited:
            return None
        visited.add(site)
        candidate_entries = [entry for entry in owner_map.get(site, [])
                             if entry <= site and calls_by_target.get(entry)]
        if not candidate_entries:
            return None
        # Самая внутренняя достигнутая procedure имеет максимальный entry PC.
        entry = max(candidate_entries)
        union: set[int] = set()
        for caller in calls_by_target[entry]:
            values = local_domain(caller)
            diagnostic = symbolic_diagnostics.get(caller, {})
            if values is None and (diagnostic.get("reason") == "BX never assigned" or
                                   "entry:bx" in diagnostic.get("variables", {})):
                values = caller_domain(caller, visited)
            if values is None:
                return None
            union.update(values)
            if len(union) > 0x1000:
                return None
        return union

    records: dict[tuple[int, int], dict[str, object]] = {}
    unresolved_calls = []
    unresolved_details = []
    for source, target in calls:
        # Symbolic pass приоритетен: он сохраняет зависимость AX/BX. Старый
        # finite-set pass служит fallback для нескольких независимых, но уже
        # узких table domains.
        bx_values = local_domain(source)
        diagnostic = symbolic_diagnostics.get(source, {})
        if bx_values is None and (diagnostic.get("reason") == "BX never assigned" or
                                  "entry:bx" in diagnostic.get("variables", {})):
            bx_values = caller_domain(source)
            if bx_values is not None:
                domain_cache[source] = set(bx_values)
        if bx_values is None:
            unresolved_calls.append(source)
            unresolved_details.append({"call": source, "renderer": target,
                                       "reason": "address domain exceeds exact limit or has multiple unconstrained producers",
                                       "symbolic": symbolic_diagnostics.get(source, {})})
            continue
        pending = []
        candidate_invalid = False
        invalid_address = None
        for bx in sorted(bx_values):
          for ordinal in range(render_counts[target]):
            address = (bx + ordinal * 6) & 0xFFFF
            raw = main[0x10000 + address:0x10000 + address + 6]
            if len(raw) != 6:
                candidate_invalid = True
                invalid_address = address
                break
            code = int.from_bytes(raw[2:4], "little")
            attribute = int.from_bytes(raw[4:6], "little")
            if code >= 4096 or attribute & 0x00FF:
                # Finite-set анализ без relational domains может получить
                # невозможную комбинацию AX/BX. Такой call не объявляется
                # разрешённым и будет обработан producer-aware проходом.
                candidate_invalid = True
                invalid_address = address
                break
            pending.append(((address, source, ordinal), {
                "address": address,
                "consumer_call": source,
                "renderer": target,
                "ordinal": ordinal,
                "dx": raw[0] - 256 if raw[0] & 0x80 else raw[0],
                "dy": raw[1] - 256 if raw[1] & 0x80 else raw[1],
                "code": code,
                "attribute": attribute,
            }))
          if candidate_invalid:
            break
        if candidate_invalid:
            unresolved_calls.append(source)
            unresolved_details.append({
                "call": source, "renderer": target,
                "reason": "abstract domain contains a non-descriptor address",
                "invalid_address": invalid_address,
                "candidate_count": len(bx_values),
                "candidate_min": min(bx_values),
                "candidate_max": max(bx_values),
                "symbolic": symbolic_diagnostics.get(source, {}),
            })
            continue
        records.update(pending)
    by_code: list[dict[str, object]] = []
    values = list(records.values())
    for code in range(4096):
        consumers = [item for item in values if item["code"] == code]
        by_code.append({
            "code": code,
            "direct_descriptor_consumers": consumers,
            "directly_proven": bool(consumers),
        })

    # Source tables, из которых доказанный pass выше получает descriptor
    # addresses. Они являются самостоятельными ROM formats, а не sprite
    # descriptors; без них цепочка producer -> descriptor -> renderer была
    # бы представлена только наполовину.
    producer_ranges: list[dict[str, object]] = []

    def producer(start: int, end: int, fmt: str, consumers) -> None:
        producer_ranges.append({"start": start, "end": end, "format": fmt,
                                "consumers": sorted(set(consumers))})

    producer(0x10C2, 0x1131, "14 x 8-byte R-9 launch step",
             [0x1F83, 0x1FA3])
    producer(0x1318, 0x1337, "8 x (u16 descriptor-pointer, u16 duration)",
             [0x2318])
    producer(0x1440, 0x1457, "2 x 6-u16 descriptor-pointer ring",
             [0x286F, 0x2A07, 0x2AAB])
    producer(0x1458, 0x1487, "4 x 6-u16 descriptor-pointer ring",
             [0x2939, 0x29D5, 0x2A8C])
    producer(0x1488, 0x1499, "9 x u16 descriptor-table pointer",
             [0x28EE, 0x2978])
    producer(0x149A, 0x14A9, "8 x u16 descriptor pointer",
             [0x2A5E])
    producer(0x15AE, 0x15BD, "16 x u8 selector into `$1488`",
             [0x28BC, 0x2946])
    producer(0x188C, 0x1897, "6 x u16 Beam width/power value",
             [0x313B])
    producer(0x1898, 0x18AB, "10 x u16 Beam descriptor pointer",
             [0x3201])
    producer(0x1960, 0x1977,
             "6 x (u16 composite descriptor pointer, u16 duration)",
             [0x32CA, 0x32D1])
    producer(0x209A, 0x20A1, "4 x u16 terrain-branch descriptor pointer",
             [0x4433])
    producer(0x20A2, 0x20A5, "2 x u16 alternating descriptor pointer",
             [0x4536])
    producer(0x27FE, 0x281D, "16 x u16 phase-map word",
             [0x5852, 0x58CE])
    producer(0x292A, 0x2939, "2 x 4-u16 zero-terminated walker stream",
             [0x5AFE, 0x5C53])
    producer(0x2B60, 0x2B7F,
             "two 4-u16 and one 8-u16 descriptor-pointer tables",
             [0x61F8, 0x6265, 0x6330, 0x6544])
    producer(0x3866, 0x3895, "6 x 4-u16 direction descriptor table",
             [0x8233, 0x830F])
    producer(0x3B32, 0x3B51, "16 x u16 direction descriptor base",
             [0x8963])
    producer(0x3F76, 0x3F85, "16 x u8 animation phase map",
             [0x8F74, 0x9049])
    producer(0x3FC6, 0x3FE5, "4x4 u16 direction-pair pointer matrix",
             [0x9068, 0x90C2])
    producer(0x428C, 0x42AB, "16 x u16 projectile direction descriptor",
             [0x9703])
    producer(0x4374, 0x4379, "3 x u16 state descriptor pointer",
             [0x9855, 0x98E0])
    producer(0x43AC, 0x445F, "18 x 10-byte boss-child constructor record",
             [0xA03E, 0xA0A0, 0xA115])
    producer(0x4CC6, 0x4CE5, "16 x u16 direction descriptor pointer",
             [0xA153, 0xA1C8])
    producer(0x5872, 0x58B1, "16 x 4-byte attached-part direction record",
             [0xAC9E, 0xACAA])
    producer(0x625C, 0x627B, "16 x u16 direction descriptor pointer",
             [0xBDF4])
    producer(0x6312, 0x6319, "4 x u16 persistent descriptor pointer",
             [0xC04E, 0xC078])
    producer(0x7A94, 0x7AB3, "16 x u16 child direction descriptor",
             [0xD2CB])
    producer(0x7B4E, 0x7BED, "5 x 16-u16 direction descriptor table",
             [0xD63C, 0xD75F])
    producer(0x7C30, 0x7CEF, "6 x 16-u16 spawn-record pointer table",
             [0xD839])
    producer(0x7E9A, 0x7EA5, "6 x u16 explosion descriptor pointer",
             [0xD93D])
    producer(0x7ED2, 0x7EF1, "4 x 8-byte descriptor-list root record",
             [0xDB39, 0xDB42])
    producer(0x81FA, 0x8219, "16 x u16 direction descriptor pointer",
             [0xE18A])
    producer(0x8258, 0x8297, "2 x 16-u16 direction descriptor table",
             [0xE2DD])
    producer(0x83AC, 0x842B, "32 x 4-byte RNG descriptor record",
             [0xE5DD])
    producer(0x9384, 0x93BB, "4 x 14-byte spawn/descriptor-root record",
             [0x7009, 0x709F, 0x7123, 0xFA02])
    producer(0x945C, cursor + 1,
             "6-byte cumulative-timeline roots plus terminal zero word",
             [0xFB10, 0xFB7F])

    def duration_stream_end(base: int) -> int:
        position = base
        while table_word(position, 0):
            position += 4
        return position + 1  # terminal duration word тоже читается.

    for base, consumers in {
            0x8506: [0xE731, 0xE7E1], 0x8530: [0xE7E1],
            0x8552: [0xE7E1], 0x8574: [0xE7E1],
            0x85FA: [0xE83A]}.items():
        producer(base, duration_stream_end(base),
                 "(u16 duration, u16 descriptor pointer) until zero duration",
                 consumers)

    for root in sorted(db_roots):
        position = root
        while table_word(position, 0):
            position += 2
        producer(root, position + 1,
                 "u16 composite-descriptor pointers until zero word",
                 [0xDB39, 0xDB42])
    return {
        "renderer_calls_total": len(calls),
        "literal_bx_calls": len(calls) - len(unresolved_calls),
        "object_or_table_pointer_calls": unresolved_calls,
        "unresolved_details": unresolved_details,
        "symbolic_diagnostics": symbolic_diagnostics,
        "descriptor_consumer_edges": sorted(
            values, key=lambda item: (item["address"], item["consumer_call"])),
        "codes": by_code,
        "directly_proven_code_count": sum(item["directly_proven"]
                                           for item in by_code),
        "producer_ranges": sorted(producer_ranges,
                                  key=lambda item: (item["start"], item["end"])),
        "complete": not unresolved_calls,
    }


def es_access_site_registry(runtime: "RecursiveV30",
                            contexts: dict[int, list[str]]) -> list[dict[str, object]]:
    """Перечислить без пропусков все syntactic `ES:[...]` sites runtime."""
    def segments_at(source: int) -> tuple[int | None, ...]:
        matches = [segments for start, end, segments in ES_SEGMENT_PC_RANGES
                   if start <= source <= end]
        if len(matches) > 1:
            raise ValueError(f"перекрывающиеся ES segment rules at ${source:04X}")
        return matches[0] if matches else (0x1000,)

    owners_by_address = intraprocedural_owner_map(runtime)
    result = []
    for address, instruction in sorted(runtime.instructions.items()):
        expressions = re.findall(r"es:\[([^]]+)\]", instruction.operands)
        if not expressions:
            continue
        owners = owners_by_address.get(address, [])
        destination_es = instruction.operands.lstrip().startswith(
            ("byte ptr es:[", "word ptr es:[", "dword ptr es:["))
        if instruction.mnemonic.startswith("stos"):
            access = "write"
        elif instruction.mnemonic.startswith("movs"):
            access = "write-destination"
        elif instruction.mnemonic == "call":
            access = "read-code-pointer"
        elif destination_es and instruction.mnemonic in ("cmp", "test"):
            access = "read"
        elif destination_es:
            access = "write"
        else:
            access = "read"
        literals = sorted({int(token, 16) & 0xFFFF
                           for expression in expressions
                           for token in re.findall(r"0x([0-9a-f]+)", expression)})
        segments = segments_at(address)
        result.append({
            "source": address,
            "owner_entries": owners,
            "mnemonic": instruction.mnemonic,
            "operands": instruction.operands,
            "expressions": expressions,
            "literal_terms": literals,
            "access": access,
            "segments": segments,
            "segment_meanings": [ES_SEGMENT_MEANINGS[value]
                                 for value in segments],
            "context": sorted({label for owner in owners
                               for label in contexts.get(owner, [])} |
                              set(contexts.get(address, []))),
        })
    return result


def world_es_access_catalog(sites: list[dict[str, object]],
                            errors: list[str]) -> dict[str, object]:
    """Сгруппировать все World-ES consumers по нормализованной ROM-базе.

    Это индекс producer-аудита, а не попытка угадать длину таблицы по
    соседним bytes. Выражение с большим signed displacement получает точную
    базу (`bx-$7C54` -> `$83AC`); малые `+2/+4/...` остаются pointer-relative
    и будут связаны с диапазоном только доказавшим pointer producer pass.
    """
    world_sites = [site for site in sites if site["segments"] == (0x1000,)]
    groups: dict[int, list[dict[str, object]]] = collections.defaultdict(list)
    pointer_relative = []

    def access_width(site: dict[str, object]) -> str:
        operands = str(site["operands"])
        for marker, width in (("byte ptr", "u8"), ("word ptr", "u16le"),
                              ("dword ptr", "u32le")):
            if marker in operands:
                return width
        mnemonic = str(site["mnemonic"])
        if mnemonic.endswith("b"):
            return "u8"
        if mnemonic.endswith("w"):
            return "u16le"
        return "implicit"

    for site in world_sites:
        bases: set[int] = set()
        normalized_expressions = []
        for expression in site["expressions"]:
            terms = re.findall(r"([+-]?)\s*0x([0-9a-f]+)", expression)
            signed_displacement = sum(
                (-1 if sign == "-" else 1) * int(value, 16)
                for sign, value in terms)
            normalized = signed_displacement & 0xFFFF
            # `$0000..$03FF` is the physical alias of the V30 code tail.
            # In indexed expressions smaller constants are field offsets,
            # not independent World-data table bases.
            has_register = bool(re.search(
                r"\b(?:ax|bx|cx|dx|si|di|bp|sp)\b", expression))
            is_base = bool(terms) and (not has_register or
                                       abs(signed_displacement) >= 0x400)
            normalized_expressions.append({
                "expression": expression,
                "signed_displacement": signed_displacement,
                "normalized_displacement": normalized,
                "direct_base": normalized if is_base else None,
            })
            if is_base:
                bases.add(normalized)
        consumer = {
            "source": site["source"],
            "owner_entries": site["owner_entries"],
            "access": site["access"],
            "width": access_width(site),
            "mnemonic": site["mnemonic"],
            "operands": site["operands"],
            "expressions": normalized_expressions,
            "context": site["context"],
        }
        if bases:
            for base in bases:
                groups[base].append(consumer)
        else:
            pointer_relative.append(consumer)

    covered_sites = ({item["source"] for values in groups.values()
                      for item in values} |
                     {item["source"] for item in pointer_relative})
    if covered_sites != {site["source"] for site in world_sites}:
        errors.append("World ES consumer catalog потерял instruction site")
    return {
        "world_site_count": len(world_sites),
        "direct_base_count": len(groups),
        "direct_base_site_count": len({item["source"]
                                       for values in groups.values()
                                       for item in values}),
        "pointer_relative_site_count": len(pointer_relative),
        "all_sites_catalogued": len(covered_sites) == len(world_sites),
        "direct_bases": [
            {"base": base, "consumers": sorted(values,
                                                 key=lambda item: item["source"])}
            for base, values in sorted(groups.items())
        ],
        "pointer_relative_consumers": sorted(
            pointer_relative, key=lambda item: item["source"]),
    }


def service_world_rom_data_map(main: bytes, boot39: "RecursiveV30",
                               errors: list[str]) -> dict[str, object]:
    """Разобрать весь World-ROM хвост, который читает service code `$3900`.

    Здесь учитываются не только явные `ES:` operands, но и source `DS:$1000`
    у `LODS/MOVS`. Границы следуют из циклов и `$24` terminators самого ROM,
    а смежность проверяется до последнего байта `$EF54`.
    """
    es = main[0x10000:0x20000]

    def terminated_end(start: int) -> int:
        try:
            return es.index(0x24, start)  # `$` — терминатор service strings.
        except ValueError as exc:
            raise ValueError(f"нет `$24` terminator после ES:${start:04X}") from exc

    def header_sequence(start: int, count: int) -> tuple[list[dict[str, int]], int]:
        records = []
        cursor = start
        for index in range(count):
            end = terminated_end(cursor + 4)
            records.append({"index": index, "start": cursor, "end": end,
                            "destination": int.from_bytes(es[cursor:cursor + 2],
                                                          "little"),
                            "attribute": int.from_bytes(es[cursor + 2:cursor + 4],
                                                        "little")})
            cursor = end + 1
        return records, cursor

    ranges: list[dict[str, object]] = []

    def add(start: int, end: int, fmt: str, consumers: list[int],
            segment: str = "ES", records: list[dict[str, int]] | None = None) -> None:
        ranges.append({"start": start, "end": end, "format": fmt,
                       "segment": segment, "consumers": consumers,
                       "records": records or []})

    dispatch = list(_es_words(main, 0xEB07, 5))
    if set(dispatch) != BOOT39_INDIRECT_ENTRIES - {0x02FD}:
        errors.append("service dispatch ES:$EB07..$EB10 изменился")
    add(0xEB07, 0xEB10, "5 x u16 service-screen handler", [0x037F])

    early_roots = ((0xEB11, 0x01D1), (0xEB1E, 0x0592),
                   (0xEB29, 0x01D1), (0xEB34, 0x0592),
                   (0xEB3F, 0x0592))
    early_ends = []
    for root, header_consumer in early_roots:
        end = terminated_end(root + 4)
        early_ends.append(end)
        consumers = ([0x0592, 0x0598, 0x059E]
                     if header_consumer == 0x0592
                     else [0x01D1, 0x01D7, 0x01DD])
        add(root, end, "u16 tile-destination, u16 attribute, `$24` text",
            consumers)
    if early_ends != [0xEB1D, 0xEB28, 0xEB33, 0xEB3E, 0xEB4C]:
        errors.append("границы RAM/ROM/SOUND service strings изменились")

    sound_records = []
    for index in range(65):
        start = 0xEB4D + index * 7
        end = terminated_end(start + 4)
        if end != start + 6:
            errors.append(f"service sound record ${start:04X} не равен 7 bytes")
        sound_records.append({"index": index + 1, "start": start, "end": end,
                              "command": int.from_bytes(es[start:start + 2],
                                                        "little"),
                              "delay": int.from_bytes(es[start + 2:start + 4],
                                                      "little")})
    add(0xEB4D, 0xED13,
        "65 x (u16 sound-command, u16 frame-delay, 2 ASCII digits, `$24`)",
        [0x041C, 0x042B, 0x059E], records=sound_records)
    if int.from_bytes(es[0xED14:0xED16], "little") != 0x00FF:
        errors.append("service sound-list sentinel ES:$ED14 не равен `$00FF`")
    add(0xED14, 0xED15, "u16 `$00FF` sound-list terminator", [0x041F])

    menu_records, cursor = header_sequence(0xED16, 5)
    if cursor != 0xED6E:
        errors.append("service menu ES:$ED16 не заканчивается на `$ED6D`")
    add(0xED16, 0xED6D,
        "5 x (u16 tile-destination, ignored u16, `$24` menu text)",
        [0x0581, 0x059E], records=menu_records)

    io_records, cursor = header_sequence(0xED6E, 4)
    if cursor != 0xEDAA:
        errors.append("I/O service labels не заканчиваются на `$EDA9`")
    add(0xED6E, 0xEDA9,
        "4 x (u16 tile-destination, u16 attribute, `$24` I/O label)",
        [0x0592, 0x0598, 0x059E], records=io_records)

    if terminated_end(0xEDAA) != 0xEDDA:
        errors.append("DIP-switch bit pattern ES:$EDAA имеет неверную длину")
    add(0xEDAA, 0xEDDA, "48 glyph bytes + `$24` DIP-switch bit pattern",
        [0x059E])
    if terminated_end(0xEDDB) != 0xEE0B:
        errors.append("input-port bit pattern ES:$EDDB имеет неверную длину")
    add(0xEDDB, 0xEE0B, "48 glyph bytes + `$24` input-port bit pattern",
        [0x059E])

    add(0xEE0C, 0xEEAD, "9 x (u16 destination, 16 tile bytes)",
        [0x0213, 0x021B, 0x025F, 0x0267], segment="DS")
    add(0xEEAE, 0xEEE3, "3 x (u16 destination, 16 sprite/tile bytes)",
        [0x0234, 0x023C, 0x0280, 0x0288], segment="DS")
    if terminated_end(0xEEE4) != 0xEF14:
        errors.append("cross-hatch row ES:$EEE4 имеет неверную длину")
    add(0xEEE4, 0xEF14, "48 glyph bytes + `$24` repeated cross-hatch row",
        [0x059E])
    add(0xEF15, 0xEF54, "32 x u16 raw sprite diagnostic entries",
        [0x045A], segment="DS")

    expected = 0xEB07
    for item in ranges:
        if item["start"] != expected:
            errors.append(f"gap/overlap service World ROM before ${item['start']:04X}")
        expected = int(item["end"]) + 1
    if expected != 0xEF55:
        errors.append("service World ROM map не заканчивается перед `$EF55`")
    instruction_sites = set(boot39.instructions)
    for item in ranges:
        missing = set(item["consumers"]) - instruction_sites
        if missing:
            errors.append("service World ROM consumer не является code site: " +
                          ", ".join(f"${value:04X}" for value in sorted(missing)))
    return {"start": 0xEB07, "end": 0xEF54, "complete": expected == 0xEF55,
            "ranges": ranges}


def reset_world_rom_data_map(main: bytes, boot3f: "RecursiveV30",
                             runtime: "RecursiveV30",
                             errors: list[str]) -> dict[str, object]:
    """Точные World-ROM настройки DSW/coinage и initial high-score records."""
    es = main[0x10000:0x20000]
    ranges = [
        {"start": 0x0400, "end": 0x0403,
         "format": "4 x u8 lives count selected by DSW `$0003`",
         "consumers": [0x0B94]},
        {"start": 0x0404, "end": 0x0407,
         "format": "4 x u8 gameplay option selected by rotated DSW `$000C`",
         "consumers": [0x0BA8]},
        {"start": 0x0408, "end": 0x0417,
         "format": "4 x (u16 coinage value, u16 22-glyph text pointer)",
         "consumers": [0x0BE6, 0x0BEE]},
        {"start": 0x0418, "end": 0x0427,
         "format": "4 x (u16 coinage value, u16 22-glyph text pointer)",
         "consumers": [0x0C04, 0x0C0C]},
        {"start": 0x0428, "end": 0x0467,
         "format": "16 x (u16 mode-2 coinage value, u16 44-glyph text pointer)",
         "consumers": [0x0BC4, 0x0BCF]},
        {"start": 0x0468, "end": 0x0517,
         "format": "8 x fixed 22-byte ASCII coinage label",
         "consumers": [0xED78]},
        {"start": 0x0518, "end": 0x07AB,
         "format": "15 x fixed 44-byte ASCII two-line coinage label",
         "consumers": [0xED78]},
        {"start": 0x07AC, "end": 0x0819,
         "format": "10 x 11-byte initial high-score/name record",
         "consumers": [0x0C2A, 0x0C35], "segment": "DS"},
    ]
    one_line_pointers = (
        tuple(_es_words(main, 0x0408, 8)[1::2]) +
        tuple(_es_words(main, 0x0418, 8)[1::2]))
    if one_line_pointers != tuple(range(0x0468, 0x0518, 0x16)):
        errors.append("one-line coinage pointers ES:$0408/$0418 изменились")
    mode2 = _es_words(main, 0x0428, 32)
    if (mode2[:2] != (0, 0) or
            tuple(mode2[3::2]) != tuple(range(0x0518, 0x07AC, 0x2C))):
        errors.append("mode-2 coinage pointers ES:$0428 изменились")
    labels = es[0x0468:0x07AC]
    if len(labels) != 8 * 22 + 15 * 44 or any(
            byte < 0x20 or byte > 0x5A for byte in labels):
        errors.append("coinage label block ES:$0468 имеет неверный формат")
    scores = es[0x07AC:0x081A]
    if len(scores) != 10 * 11 or any(
            byte not in range(0x20, 0x5B) for index, byte in enumerate(scores)
            if index % 11 >= 4):
        errors.append("initial high-score records ES:$07AC изменились")
    boot_sites = set(boot3f.instructions)
    runtime_sites = set(runtime.instructions)
    for item in ranges:
        for source in item["consumers"]:
            if source not in boot_sites and source not in runtime_sites:
                errors.append(f"reset World ROM consumer ${source:04X} не code site")
    return {"start": 0x0400, "end": 0x0819, "complete": True,
            "ranges": ranges}


def world_es_semantic_coverage(main: bytes,
                               sprite_consumers: dict[str, object],
                               service_data: dict[str, object],
                               reset_data: dict[str, object],
                               errors: list[str]) -> dict[str, object]:
    """Побайтовая доказанная часть форматов World ES без gap-маскировки."""
    es = main[0x10000:0x20000]
    tags: list[set[str]] = [set() for _ in range(0x10000)]

    def mark(start: int, end: int, label: str) -> None:
        if not (0 <= start <= end < 0x10000):
            raise ValueError(f"неверный World ES range ${start:04X}..${end:04X}")
        for address in range(start, end + 1):
            tags[address].add(label)

    # ES:$0000 aliases physical `$10000`, то есть последний `$0400`-byte
    # хвост runtime CS. Это не неизвестные data bytes.
    mark(0x0000, 0x03FF, "runtime-code-tail-alias")
    for item in reset_data["ranges"]:
        mark(item["start"], item["end"], "reset:" + str(item["format"]))
    descriptor_calls: dict[int, set[int]] = collections.defaultdict(set)
    for edge in sprite_consumers["descriptor_consumer_edges"]:
        start = edge["address"]
        mark(start, start + 5, "sprite-descriptor-6-byte")
        descriptor_calls[start].add(edge["consumer_call"])
    for item in sprite_consumers["producer_ranges"]:
        mark(item["start"], item["end"],
             "sprite-producer:" + str(item["format"]))

    # `$F5C1` исполняет word-сценарии (`object+$12`) и адресуемые ими
    # byte-streams (`object+$14`). Корни ниже получены только из реальных
    # initializers: literal writes/copies, таблиц `$9274/$92AC/$92EC` и
    # `$BEEF -> $A7FC`. Три непрерывных острова между ними структурно состоят
    # из тех же zero+redirect terminated records, но внешних consumers не
    # имеют; их сохраняем как orphan records, а не приписываем врагу.
    motion_literal_roots = {
        0x9A96, 0x9AA2, 0x9AB2, 0x9ACE, 0x9AF8, 0x9B0A,
        0xA0BC, 0xA380, 0xA3E6, 0xA434, 0xA45A, 0xA470,
        0xA484, 0xA4B8, 0xA4CE, 0xA7FC, 0xA872, 0xA90C,
        0xA96C, 0xA9F6,
    }
    motion_table_roots = {
        *_es_words(main, 0x9274, 16),
        *(_es_words(main, address, 1)[0]
          for address in range(0x92AC, 0x92EC, 4)),
        *_es_words(main, 0x92EC, 16),
    }
    orphan_root_ranges = ((0x9A5C, 0x9A95),
                          (0xA4E8, 0xA7FB),
                          (0xA81C, 0xA871))
    motion_orphan_roots: set[int] = set()
    for start, end in orphan_root_ranges:
        position = start
        while position <= end:
            motion_orphan_roots.add(position)
            while (position + 1 <= 0xB92C and
                   int.from_bytes(es[position:position + 2], "little") != 0):
                position += 2
            if position + 3 > 0xB92C:
                errors.append(
                    f"orphan F5C1 block ${start:04X}..${end:04X} оборван")
                break
            position += 4

    motion_seed_roots = (motion_literal_roots | motion_table_roots |
                         motion_orphan_roots)
    motion_roots: set[int] = set()
    motion_word_bytes: set[int] = set()
    motion_streams: set[int] = set()
    motion_redirect_edges: list[tuple[int, int, int]] = []
    motion_count_words: list[tuple[int, int]] = []
    todo = list(motion_seed_roots)
    while todo:
        root = todo.pop()
        if root in motion_roots:
            continue
        if not 0x9A5C <= root <= 0xB92C:
            errors.append(f"F5C1 root ${root:04X} вне motion arena")
            continue
        motion_roots.add(root)
        position = root
        while position + 1 <= 0xB92C:
            value = int.from_bytes(es[position:position + 2], "little")
            motion_word_bytes.update((position, position + 1))
            if value == 0:
                if position + 3 > 0xB92C:
                    errors.append(f"F5C1 redirect ${position:04X} оборван")
                    break
                target = int.from_bytes(es[position + 2:position + 4],
                                        "little")
                motion_word_bytes.update((position + 2, position + 3))
                motion_redirect_edges.append((root, position, target))
                if not 0x9A5C <= target <= 0xB92C:
                    errors.append(
                        f"F5C1 redirect ${position:04X} -> ${target:04X} вне arena")
                elif target not in motion_roots:
                    todo.append(target)
                break
            if value & 0xFF00 == 0xF000:
                motion_count_words.append((position, value & 0xFF))
            else:
                motion_streams.add(value)
            position += 2
        else:
            # Некоторые terminal lists доходят ровно до `$B92C`; физическая
            # граница `$B92D` (dispatch следующего формата) является их end.
            if position not in (0xB92C, 0xB92D):
                errors.append(f"F5C1 word stream ${root:04X} не завершён")

    motion_stream_bytes: set[int] = set()
    motion_stream_ends: dict[int, int] = {}
    for stream in sorted(motion_streams):
        if not 0 <= stream < 0x10000:
            errors.append(f"F5C1 byte pointer ${stream:04X} вне World")
            continue
        position = stream
        while position < 0x10000:
            value = es[position]
            motion_stream_bytes.add(position)
            position += 1
            # Bit 7 — phase command; для обычной команды bit 2 завершает блок.
            if not value & 0x80 and value & 0x04:
                motion_stream_ends[stream] = position - 1
                break
        else:
            errors.append(f"F5C1 byte stream ${stream:04X} не завершён")

    motion_arena = set(range(0x9A5C, 0xB92D))
    if not motion_arena <= motion_word_bytes | motion_stream_bytes:
        missing = min(motion_arena - motion_word_bytes - motion_stream_bytes)
        errors.append(f"F5C1 arena имеет дыру с ${missing:04X}")
    mark(0x9A5C, 0xB92C,
         "runtime:F5C1 word scripts and addressed byte motion streams")

    # Эти диапазоны уже доказаны indirect-control-flow анализом ниже. Здесь
    # они продублированы как byte formats, чтобы граф callbacks и побайтовая
    # карта не расходились и не оставляли известные таблицы в unresolved.
    proven_runtime_ranges = [
        {"start": 0x081A, "end": 0x0869,
         "format": "40 x u16 initial fixed-object handler",
         "consumers": [0x06AD]},
        {"start": 0x08C4, "end": 0x0909,
         "format": "7 x 10-byte title/demo object bootstrap record",
         "consumers": [0x0802, 0x0820, 0x0824, 0x082E, 0x0835]},
        {"start": 0x090A, "end": 0x09E1,
         "format": "6 x 36-byte title-logo motion stream: five (s16 Q8 vx,s16 Q8 vy,u16 duration) steps plus `(0x8000,final X,final Y)` terminal",
         "consumers": [0x0802, 0x0805, 0x080B, 0x0812, 0x0819,
                       0x081C, 0x09F9, 0x09FC, 0x09FF, 0x0A08,
                       0x0A19, 0x0A1E, 0x0A21, 0x0A28, 0x0A2E,
                       0x0A35, 0x0A3C, 0x0A3F, 0x0A4D]},
        {"start": 0x09E2, "end": 0x09FF,
         "format": "30-byte primary title-logo motion stream: four (s16 Q8 vx,s16 Q8 vy,u16 duration) steps plus `(0x8000,final X,final Y)` terminal",
         "consumers": [0x0802, 0x0805, 0x080B, 0x0812, 0x0819,
                       0x081C, 0x09F9, 0x09FC, 0x09FF, 0x0A08,
                       0x0A19, 0x0A1E, 0x0A21, 0x0A28, 0x0A2E,
                       0x0A35, 0x0A3C, 0x0A3F, 0x0A4D]},
        {"start": 0x0A00, "end": 0x0A87,
         "format": "7 title foreground text records for `$1951/$1992`: (u16 destination,u16 attribute,u16 length, optional inline ASCII); two 22-byte dynamic-score headers omit inline bytes",
         "consumers": [0x08A0, 0x08B8, 0x08D5, 0x08F0, 0x090B,
                       0x0920, 0x0935, 0x1951, 0x1954, 0x195A,
                       0x1961, 0x196A, 0x1974, 0x1980, 0x1992,
                       0x1995, 0x199B, 0x19A2, 0x19A9, 0x19C1]},
        {"start": 0x0A88, "end": 0x0AC3,
         "format": "2 x 30-byte ED58 title text record (u16 attribute, packed 1x24 dimensions, u16 destination, 24 raw glyph bytes)",
         "consumers": [0x0CF1, 0x0CF4, 0x0CFA, 0x0CFD,
                       0xED58, 0xED66, 0xED68, 0xED6B, 0xED6E,
                       0xED71, 0xED78]},
        {"start": 0x0AC4, "end": 0x0ACF,
         "format": "2 x 6-byte ED3A dynamic-score header (u16 attribute, packed 1x22 dimensions, u16 destination); glyph source supplied separately",
         "consumers": [0x0D0B, 0x0D0F, 0x0D12, 0x0D18, 0x0D1C,
                       0x0D1F, 0xED3A, 0xED46, 0xED48, 0xED4A,
                       0xED4D, 0xED50, 0xED76]},
        {"start": 0x0AD0, "end": 0x0B3D,
         "format": "3 ED58 inline text records: 1x24 copyright, 2x14 PUSH 1P BUTTON, 2x20 PUSH 1P OR 2P BUTTON",
         "consumers": [0x0D25, 0x0D28, 0x0D2B, 0xED58, 0xED66,
                       0xED68, 0xED6B, 0xED6E, 0xED71, 0xED78]},
        {"start": 0x0B56, "end": 0x0B5B,
         "format": "6-byte title/presentation sprite descriptor `($F818,$00D4,0)`",
         "consumers": [0x11BCC]},
        {"start": 0x0B5C, "end": 0x0B7D,
         "format": "34-byte initials-entry alphabet/punctuation glyph sequence `A..Z,!?>.,-<:`",
         "consumers": [0x166B, 0x166E, 0x1782, 0x1785, 0x17BE,
                       0x17C1]},
        {"start": 0x0B7E, "end": 0x0B8D,
         "format": "8 x u16 foreground tile-cell address `$2B78..$2BB0` step 8",
         "consumers": [0x1675, 0x1678, 0x167A, 0x16C4, 0x16C7,
                       0x16C9, 0x1724, 0x1727, 0x1729, 0x178C,
                       0x178F, 0x1791]},
        {"start": 0x0B8E, "end": 0x0BA1,
         "format": "10 x u16 ranking-row reveal delay `(10,20,...,100)`",
         "consumers": [0x1B2A, 0x1B2E, 0x1B30, 0x1B45]},
        {"start": 0x0BA2, "end": 0x0BB5,
         "format": "10 x u16 ranking-row foreground destination `$186C..$2A6C` step `$0200`",
         "consumers": [0x1AA1, 0x1AA4, 0x1AA5, 0x1AA7]},
        {"start": 0x0BB6, "end": 0x0BC9,
         "format": "10 x u16 pointer to 12-u16 ranking-row tile block",
         "consumers": [0x1AA1, 0x1AA4, 0x1AA5, 0x1AC5, 0x1B4B,
                       0x1B67, 0x1B74]},
        {"start": 0x0BCA, "end": 0x0CB9,
         "format": "10 x 12-u16 ranking-row tile block copied as two rows of six cells",
         "consumers": [0x0BB6, 0x1AC5, 0x1B4B, 0x1B61, 0x1B67,
                       0x1B74]},
        {"start": 0x0CBA, "end": 0x0D1D,
         "format": "4 inline text records (u16 foreground destination, u16 attribute, u16 byte length, ASCII): RANKING/STAGE SCORE/ENTER YOUR INITIALS/ranking template",
         "consumers": [0x1552, 0x1951, 0x1954, 0x195A, 0x1961,
                       0x196A, 0x1974, 0x1980]},
        {"start": 0x0D1E, "end": 0x0D33,
         "format": "11 fixed two-byte ASCII rank labels `0 `..`9 ` and `10`",
         "consumers": [0x1A8C, 0x1A8F, 0x1A91, 0x1A93]},
        {"start": 0x0D34, "end": 0x0DB3,
         "format": "16 fixed 8-byte ASCII stage labels `1 STAGE `..`16 STAGE`",
         "consumers": [0x1580, 0x15A8, 0x15BC]},
        {"start": 0x0DB4, "end": 0x0DBB,
         "format": "8-byte ASCII ranking footer `TOTAL SC`",
         "consumers": [0x15EB]},
        {"start": 0x0DBC, "end": 0x0DCB,
         "format": "8 x u16 ranking stage-score foreground destination `$1730..$2530` step `$0200`",
         "consumers": [0x1579, 0x159F, 0x15B8]},
        {"start": 0x0DCC, "end": 0x0DDD,
         "format": "9 unreferenced alternate u16 foreground destinations `$1788..$2788` step `$0200`",
         "consumers": []},
        {"start": 0x0DDE, "end": 0x0E05,
         "format": "10 x (u16 countdown ED93 text pointer, u16 sound command `$79..$70`)",
         "consumers": [0x141F, 0x1422, 0x1424, 0x142C, 0x142F,
                       0x1431, 0x1439, 0x1441]},
        {"start": 0x0E06, "end": 0x0E69,
         "format": "3 ED93 text rectangles: CONTINUE, INSERT COIN and two-line blank/PUSH START BUTTON",
         "consumers": [0x0DDE, 0xED93]},
        {"start": 0x0E6A, "end": 0x10C1,
         "format": "10 x 60-byte ED93 countdown digit text rectangle (header plus 9x6 ASCII-art glyph)",
         "consumers": [0x0DDE, 0x1431, 0xED93]},
        {"start": 0x11B0, "end": 0x11B9,
         "format": "5 x u16 R-9 speed-tier pointer to 16-direction Q8 velocity matrix",
         "consumers": [0x20E3, 0x20E5, 0x20EA, 0x20F3, 0x20F5]},
        {"start": 0x11BA, "end": 0x12F9,
         "format": "5 speed tiers x 16 input-direction records x (s16 Q8 velocity X,s16 Q8 velocity Y); direction is input nibble `$2F21&0F`",
         "consumers": [0x20D6, 0x20D9, 0x20DD, 0x20DF, 0x20E3,
                       0x20F5, 0x20FA, 0x20FC, 0x2102]},
        {"start": 0x1430, "end": 0x1437,
         "format": "4 x u16 Force-level state handler",
         "consumers": [0x257A, 0x260D]},
        {"start": 0x14AA, "end": 0x14E9,
         "format": "32-word dense Force direction/phase descriptor-pointer lattice; nine roots from `$1488` each expose a four-word overlapping window",
         "consumers": [0x1488, 0x28EE, 0x28F2, 0x28F6, 0x28F9,
                       0x2939, 0x2946, 0x2949, 0x1BE9]},
        {"start": 0x15BE, "end": 0x15C5,
         "format": "4 x u16 Force collision-radius record pointer; levels 0/1 share `$15C6`, levels 2/3 select `$15CE/$15D6`",
         "consumers": [0x2523, 0x2526, 0x252A, 0x252C, 0x2665,
                       0x2668, 0x266C, 0x266E, 0x38F4]},
        {"start": 0x15C6, "end": 0x15DD,
         "format": "3 x four-u16 Force collision radii `(left,right,lower,upper)`: all 4, all 7, all 12",
         "consumers": [0x15BE, 0x38F4, 0x38F7, 0x38FB, 0x38FF,
                       0x3903, 0x390E, 0x3913, 0x391E]},
        {"start": 0x15DE, "end": 0x16DD,
         "format": "4 phases x 16 weapon-selector records x (s16 Bit target dx,s16 Bit target dy); upper/lower Bit apply opposite `$20` Y bias",
         "consumers": [0x2D8B, 0x2D91, 0x2D95, 0x2D99, 0x2D9C,
                       0x2DAF, 0x2DB1, 0x2DBA, 0x2F4C, 0x2F52,
                       0x2F56, 0x2F5A, 0x2F5D, 0x2F70, 0x2F72,
                       0x2F7B]},
        {"start": 0x16DE, "end": 0x171D,
         "format": "32 x packed Bit-1 pursuit parameter: signed low-byte Q8 correction and unsigned high-byte dead-band radius",
         "consumers": [0x2DE4, 0x2DE7, 0x2DEA, 0x2DEF, 0x2DF1,
                       0x2DF6, 0x2E21, 0x2E24, 0x2E29, 0x2E2B,
                       0x2E30]},
        {"start": 0x171E, "end": 0x175D,
         "format": "32 x packed Bit-2 pursuit parameter, byte-identical mirror of `$16DE..171D`",
         "consumers": [0x2FA5, 0x2FA8, 0x2FAB, 0x2FB0, 0x2FB2,
                       0x2FB7, 0x2FDF, 0x2FE2, 0x2FE5, 0x2FEA,
                       0x2FEC, 0x2FF1]},
        {"start": 0x180E, "end": 0x183D,
         "format": "6 unreferenced four-u16 collision-radius records `(left=4,right=5,lower=height,upper=height)` for heights 8,16,32,64,96,128",
         "consumers": []},
        {"start": 0x183E, "end": 0x1855,
         "format": "12 x u16 Wave horizontal terrain-probe count `(5,5,6,6,7,8,9,10,11,12,12,12)`; `$3232` reaches entries 0..4 for ROM powers 4,8,12,16,20, tail entries 5..11 are dormant",
         "consumers": [0x3227, 0x322A, 0x322C, 0x3230, 0x3232,
                       0x3237, 0x323A, 0x323E, 0x3243]},
        {"start": 0x1856, "end": 0x187D,
         "format": "5 Wave-power collision-radius records `(left,right,lower,upper)`, selected at 8-byte stride after the seven-frame launch delay",
         "consumers": [0x3204, 0x320B, 0x3210, 0x3213, 0x3216,
                       0x3218, 0x321C, 0x321E, 0x3220, 0x3224,
                       0x38F4, 0x38F7, 0x38FB, 0x38FF]},
        {"start": 0x187E, "end": 0x188B,
         "format": "7 x u16 Wave initial foreground/background terrain-scan length, all one; `$3197` reaches level entries 1..5, entries 0/6 are dormant",
         "consumers": [0x318A, 0x3193, 0x3195, 0x3197, 0x319C,
                       0x31A1, 0x31B7, 0x31BC, 0x31D4]},
        {"start": 0x1A08, "end": 0x1A17,
         "format": "two four-u16 paired-missile collision-radius records selected by upper/lower missile owner handler in `$34E5`: `(16,32,32,128)` and `(16,32,128,32)`",
         "consumers": [0x33A1, 0x34E5, 0x34E8, 0x34ED, 0x34EF,
                       0x34F2, 0x362A, 0x366D, 0x35B8, 0x35BB]},
        {"start": 0x1A18, "end": 0x1A1F,
         "format": "four-u16 fixed paired-missile collision radii `(16,32,128,128)` selected for short direction phases by `$362A`",
         "consumers": [0x34EF, 0x362A]},
        {"start": 0x1A20, "end": 0x1A27,
         "format": "four-u16 paired-missile player-grid collision radii `(6,6,6,6)` passed to `$38F4`",
         "consumers": [0x34F5, 0x34F8, 0x35BE, 0x35C1, 0x38F4]},
        {"start": 0x1A58, "end": 0x1A97,
         "format": "16 direction-indexed `(s16 terrain-probe dx,s16 terrain-probe dy)` offsets; entries 8..15 are the exact negation of 0..7",
         "consumers": [0x3478, 0x347D, 0x347F, 0x3481, 0x3489,
                       0x356A, 0x356F, 0x3571, 0x3573, 0x357B,
                       0x3741, 0x3746, 0x3748, 0x374A, 0x3752,
                       0x3834, 0x3839, 0x383B, 0x383D, 0x3845]},
        {"start": 0x1A98, "end": 0x1AD7,
         "format": "16 direction-indexed `(s16 Q8 vx,s16 Q8 vy)` vectors; entries 8..15 are the exact negation of 0..7",
         "consumers": [0x3525, 0x3528, 0x352D, 0x3530, 0x3535,
                       0x37EF, 0x37F2, 0x37F7, 0x37FA, 0x37FF,
                       0x10672, 0x10689]},
        {"start": 0x1AD8, "end": 0x1AEF,
         "format": "4 unreferenced 6-byte direction sprite descriptors preceding the active `$1AF0` descriptor sheet",
         "consumers": []},
        {"start": 0x1B80, "end": 0x1FFF,
         "format": "48 x 12-u16 player-weapon callback matrix",
         "consumers": [0x3954, 0x3957]},
        {"start": 0x204E, "end": 0x2055,
         "format": "four-u16 weapon-matrix projectile collision radii `(12,12,4,4)` loaded through `$38F4`",
         "consumers": [0x3EC4, 0x3ED6, 0x3ED9, 0x38F4,
                       0x38F7, 0x38FB, 0x38FF]},
        {"start": 0x2056, "end": 0x2085,
         "format": "8 direction records `(s16 terrain dx,s16 terrain dy,u16 branch descriptor pointer)` for the grid-aligned moving/composite weapon state `$4311`",
         "consumers": [0x4311, 0x435C, 0x4361, 0x4363, 0x4369,
                       0x436F, 0x4377, 0x4395, 0x439D, 0x43A5,
                       0x43A9, 0x43AD, 0x43B5, 0x43BB, 0x43C3,
                       0x43E1, 0x43E9, 0x43F1, 0x43F5, 0x43F9,
                       0x4401, 0x4409, 0x4411, 0x4419, 0x4421]},
        {"start": 0x2086, "end": 0x2095,
         "format": "4 diagonal `(s16 dx,s16 dy)` motion vectors `(8,8),(8,-8),(-8,-8),(-8,8)` selected by even direction states 0/2/4/6",
         "consumers": [0x4317, 0x431A, 0x431C, 0x431E, 0x4323,
                       0x4326, 0x432B]},
        {"start": 0x2096, "end": 0x2099,
         "format": "unreferenced fifth diagonal `(s16 dx,s16 dy)` motion vector `(8,-8)` between the four active vectors and `$209A` pointer table",
         "consumers": []},
        {"start": 0x2106, "end": 0x210B,
         "format": "unreferenced 6-byte sprite descriptor `($F8F8,$09F2,0)` following the `$20A6` descriptor sheet",
         "consumers": []},
        {"start": 0x210C, "end": 0x2113,
         "format": "four-u16 player-grid object collision radii `(12,12,12,12)` consumed by `$38F4`",
         "consumers": [0x4455, 0x4458, 0x4558, 0x455B, 0x38F4]},
        {"start": 0x2114, "end": 0x2123,
         "format": "4 cardinal `(s16 dx,s16 dy)` tile-probe steps `(up,left,down,right)`, magnitude 8",
         "consumers": [0x4804, 0x4809, 0x480B, 0x4813, 0x4833,
                       0x483B]},
        {"start": 0x2124, "end": 0x212B,
         "format": "4 x u16 collision-turn direction correction `(6,2,2,6)` indexed by orientation byte `$0D`",
         "consumers": [0x4843, 0x4848, 0x484D]},
        {"start": 0x212C, "end": 0x218B,
         "format": "4 orientations x 4 directions x `(s16 terrain-probe dx,s16 terrain-probe dy,u16 resulting direction)`",
         "consumers": [0x4854, 0x4859, 0x485B, 0x485D, 0x485F,
                       0x4861, 0x4863, 0x4868, 0x486A, 0x4874,
                       0x487C, 0x4884, 0x48A1]},
        {"start": 0x218C, "end": 0x21A3,
         "format": "4 x 6-byte direction-selected sprite descriptor for the player-grid object",
         "consumers": [0x48A4, 0x48AD, 0x48B0, 0x48B3, 0x48B7,
                       0x48B9, 0x48BB, 0x48BE, 0x48C4, 0x1BCC]},
        {"start": 0x265C, "end": 0x267B,
         "format": "four four-u16 collision-radius records for Force-grid states: asymmetric `(112,-32,32,32)` / `(-32,112,32,32)` followed by two `(32,32,16,16)`",
         "consumers": [0x4936, 0x4950, 0x4962, 0x4977, 0x499E,
                       0x49A8, 0x49B0, 0x49BA, 0x38F4]},
        {"start": 0x2716, "end": 0x272D,
         "format": "4 unreferenced 6-byte zero-offset sprite descriptors `(0,$001F,0)` at the tail of the player-weapon descriptor sheet",
         "consumers": []},
        {"start": 0x272E, "end": 0x2753,
         "format": "19 x u16 Beam-meter tile code: 8 partial-fill cells `$06AE,$06B3..$06B9`, full `$06BA`, 5 low-charge left caps, 5 maximum-charge right caps",
         "consumers": [0x4FD2, 0x4FD8, 0x4FE5, 0x4FF1, 0x4FF4,
                       0x4FF6, 0x5019, 0x501B, 0x501D, 0x501F,
                       0x5021, 0x5026, 0x5028, 0x5059, 0x505B,
                       0x505E, 0x5060, 0x5063, 0x5090, 0x50B2,
                       0x50B5, 0x50B7, 0x50BA, 0x50BC, 0x50BF]},
        {"start": 0x2754, "end": 0x2783,
         "format": "12 x palette-event `(u16 second-bank slot,u16 resource type)` record selected by low-byte command index for `$54E4`",
         "consumers": [0x5526, 0x552A, 0x552C, 0x552E, 0x5530,
                       0x5535, 0x553A, 0x553D, 0x54E4]},
        {"start": 0x2784, "end": 0x278B,
         "format": "four-s16 weapon-pickup collision extents `(-16,+14,-14,+14)` passed by `$586A` to player collision `$F485`",
         "consumers": [0x586A, 0x58D1, 0x58D4, 0xF485]},
        {"start": 0x2912, "end": 0x2919,
         "format": "four-s16 terrain-bound carrier collision extents `(-10,+10,-10,+10)` used by `$59A2` through `$F694`",
         "consumers": [0x59A2, 0x59C8, 0x59CB, 0xF694]},
        {"start": 0x291A, "end": 0x2929,
         "format": "2 x 4-u16 descriptor-pointer phase tables `$293A/$2940/$293A/$2946` and `$295E/$2964/$295E/$296A` selected by carrier state `$59A2`",
         "consumers": [0x59A2, 0x5A43, 0x5A47, 0x5A49, 0x5A4B,
                       0x5A4D, 0x5A51, 0x1BCC]},
        {"start": 0x2940, "end": 0x2951,
         "format": "3 six-byte carrier sprite descriptors `$0100,$0102,$0104` referenced by pointer table `$291A`",
         "consumers": [0x291A, 0x5A51, 0x1BCC]},
        {"start": 0x2982, "end": 0x2989,
         "format": "four-s16 carrier collision extents `(-12,+12,-12,+12)` used by six movement states through `$F694`",
         "consumers": [0x5A60, 0x5B01, 0x5B81, 0x5BD7, 0x5C56,
                       0x5CC0, 0xF694]},
        {"start": 0x298A, "end": 0x2999,
         "format": "4 difficulty-indexed `(s16 Q8 vx,u16 timer)` carrier parameters `(-1536,48),(-2048,32),(-2560,16),(-3072,8)`",
         "consumers": [0x5CF1, 0x5D00, 0x5D02, 0x5D04, 0x5D09,
                       0x5D0C, 0x5D11]},
        {"start": 0x2A32, "end": 0x2A37,
         "format": "unreferenced 6-byte sprite descriptor `($F0F0,$0134,$5800)` adjacent to the terrain-probing enemy tables",
         "consumers": []},
        {"start": 0x2A38, "end": 0x2A3F,
         "format": "four-s16 terrain-probing enemy collision extents `(-10,+10,-10,+10)`",
         "consumers": [0x5EB0, 0x5EB3, 0xF694]},
        {"start": 0x2A40, "end": 0x2A7F,
         "format": "2 orientations x 4 phases x `(s16 probe dx,s16 probe dy,s16 repeat dx,s16 repeat dy)`; `$5FEE` tests three terrain cells along each ray",
         "consumers": [0x5FD5, 0x5FDE, 0x5FE1, 0x5FEC, 0x5FEE,
                       0x5FF1, 0x5FF5, 0x5FF9, 0x6003, 0x6006,
                       0x601F, 0x6022]},
        {"start": 0x2A80, "end": 0x2ABF,
         "format": "4 speed tiers x 4 cardinal directions x `(s16 Q8 vx,s16 Q8 vy)`; tier magnitudes `$0080,$0100,$0200,$0300`",
         "consumers": [0x5F66, 0x5F69, 0x5F6B, 0x5F6D, 0x5F6F,
                       0x5F72, 0x5F78, 0x5F7C, 0x5F81, 0x10672,
                       0x10689]},
        {"start": 0x2AC0, "end": 0x2AEF,
         "format": "4 animation phases x two chained 6-byte sprite descriptors for the terrain-probing enemy",
         "consumers": [0x5F8A, 0x5F93, 0x5F96, 0x5F99, 0x5F9C,
                       0x5FA2, 0x5FBB, 0x5FC4, 0x1C1B]},
        {"start": 0x2B20, "end": 0x2B3F,
         "format": "4 four-s16 side/phase collision extents for the `$60BA` multiphase enemy, selected as `$2B20/$2B28` and `$2B30/$2B38` by two independent orientation flags",
         "consumers": [0x6081, 0x6088, 0x608B, 0x608E, 0x6094,
                       0x6097, 0x609F, 0x60A2, 0x60A6, 0x60A8,
                       0x60AB, 0xF6DA]},
        {"start": 0x2B40, "end": 0x2B47,
         "format": "4 x u16 difficulty-indexed multiphase-enemy hit points `(38,16,12,8)`",
         "consumers": [0x60BA, 0x60E9, 0x60ED, 0x60EF, 0x60F1,
                       0x60F6]},
        {"start": 0x2B48, "end": 0x2B4F,
         "format": "4 x u16 difficulty-indexed first-state timer `(640,1536,1792,2048)`",
         "consumers": [0x663E, 0x6666, 0x666A, 0x666C, 0x6671]},
        {"start": 0x2B50, "end": 0x2B57,
         "format": "4 x u16 difficulty-indexed second-state timer `(896,1536,1792,2048)`",
         "consumers": [0x663E, 0x6672, 0x6676, 0x6678, 0x667D]},
        {"start": 0x2B58, "end": 0x2B5F,
         "format": "4 x u16 difficulty-indexed firing/phase divisor `(16,8,4,2)`",
         "consumers": [0x6715, 0x671D, 0x6720, 0x6725]},
        {"start": 0x2BEC, "end": 0x2C1B,
         "format": "8 unreferenced 6-byte sprite descriptors in the `$2B7E..$2C77` mirrored enemy sheet; codes `$0334,$0330,$0344,$0340,$0354,$0350,$0364,$0360`, attribute `$6800`",
         "consumers": []},
        {"start": 0x2C7E, "end": 0x2C83,
         "format": "6-byte right-facing sprite descriptor `($F8F8,$017D,$0800)` paired with existing left-facing `$2C78`",
         "consumers": [0x66C8, 0x66CE, 0x66D1, 0x66D8, 0x66DB, 0x1BCC]},
        {"start": 0x2C84, "end": 0x2C8B,
         "format": "four-s16 spawned directional enemy collision extents `(-6,+6,-6,+6)` passed by `$66C8` to `$F694`",
         "consumers": [0x66C8, 0x66DE, 0x66E1, 0x66E4, 0xF694]},
        {"start": 0x2C8C, "end": 0x2C93,
         "format": "4 difficulty-indexed u16 pointers to 16-direction Q8 velocity matrices `$8F90,$8FD0,$9010,$9050`",
         "consumers": [0x68C3, 0x68C7, 0x68C9, 0x68CB, 0x68D0,
                       0x68D5, 0x68D7, 0x68D9, 0x68DB, 0x68E1]},
        {"start": 0x2C94, "end": 0x2CB3,
         "format": "4 child constructor records `(s16 initial Q8 vx,s16 initial Q8 vy,u16 direction,u16 mirrored direction)` consumed sequentially by `$6715/$6788`",
         "consumers": [0x6715, 0x6728, 0x6738, 0x6743, 0x6749,
                       0x6759, 0x675C, 0x676C, 0x676F, 0x677F,
                       0x6788, 0x678B, 0x678E, 0x6792, 0x67AC,
                       0x67B0, 0x67BB, 0x67BE, 0x67C2, 0x67C5]},
        {"start": 0x2D14, "end": 0x2D53,
         "format": "16 direction-indexed `(s16 composite-child dx,s16 composite-child dy)` offsets used by both movement states `$67D5/$687D` before rendering `$2D54` animation",
         "consumers": [0x67D5, 0x67E1, 0x67E4, 0x67E6, 0x67E8,
                       0x67EA, 0x67EC, 0x67F7, 0x67FD, 0x6802,
                       0x6805, 0x680A, 0x687D, 0x68FA, 0x68FD,
                       0x68FF, 0x6901, 0x6903, 0x6905, 0x6910,
                       0x6916, 0x691B, 0x691E, 0x6923]},
        {"start": 0x2D84, "end": 0x2D8B,
         "format": "four-s16 16-direction enemy collision extents `(-4,+4,-4,+4)` passed by `$67D5/$687D` to `$F694`",
         "consumers": [0x67D5, 0x682A, 0x682D, 0x6830,
                       0x687D, 0x6943, 0x6946, 0x6949, 0xF694]},
        {"start": 0x2D8C, "end": 0x2D8F,
         "format": "4 x u8 difficulty-indexed enemy hit points `(3,5,8,14)`",
         "consumers": [0x696E, 0x6991, 0x6995, 0x6997, 0x699C]},
        {"start": 0x2D90, "end": 0x2DCF,
         "format": "16 direction-indexed `(s16 terrain-probe dx,s16 terrain-probe dy)` offsets used by enemy state `$69B4`",
         "consumers": [0x69B4, 0x69D9, 0x69DC, 0x69DE, 0x69E0,
                       0x69E2, 0x69E7, 0x69EC, 0x69F2, 0x69F5,
                       0x69F8]},
        {"start": 0x2E30, "end": 0x2E35,
         "format": "unreferenced 6-byte sprite descriptor `($F0F0,$0602,$5800)` adjacent to the Stage-1 terrain-object tables",
         "consumers": []},
        {"start": 0x2E36, "end": 0x2E3D,
         "format": "four-s16 `$696E/$69B4` terrain-enemy collision extents `(-12,+12,-12,+12)`",
         "consumers": [0x6A1E, 0x6A21, 0xF6DA]},
        {"start": 0x2E3E, "end": 0x2E45,
         "format": "4 x u16 difficulty-indexed damage threshold `(6,10,25,40)` assigned to the fourth link/core of the Stage-1 rotating snake",
         "consumers": [0x6B19, 0x6B21, 0x6B26]},
        {"start": 0x2E46, "end": 0x2EC5,
         "format": "16 x Stage-1 rotating-snake link record `(u16 X,u16 Y,u16 F8A7 velocity selector,u16 F5C1 motion-bytecode pointer)`",
         "consumers": [0x6AC0, 0x6ADE, 0x6AE1, 0x6AE7, 0x6AF4,
                       0x6B29, 0x6B38, 0xF5C1]},
        {"start": 0x2EC6, "end": 0x2EED,
         "format": "19 packed `(s8 tilemap-dx,s8 tilemap-dy)` foreground address steps followed by zero sentinel; low/high bytes are added independently to BL/BH",
         "consumers": [0x6B7A, 0x6B82, 0x6B95, 0x6B9C, 0x6BA3,
                       0x6BC1, 0x6BC9, 0x6BDC, 0x6BE3, 0x6BEA,
                       0x6C19, 0x6C25, 0x6C2C, 0x6C30]},
        {"start": 0x2EEE, "end": 0x2F05,
         "format": "4 x six-byte rotating-snake projectile descriptor selected by `(object-slot/8+VBlank)&$18`",
         "consumers": [0x6E33, 0x6E3B, 0x6E3F, 0x6E43, 0x6E45,
                       0x6E47, 0x6E49, 0x6E4B, 0x6E4F, 0x1BCC]},
        {"start": 0x2F0E, "end": 0x2F6D,
         "format": "16 x six-byte regular rotating-snake link descriptor indexed by F5C1 phase byte",
         "consumers": [0x6C43, 0x6C4C, 0x6C4F, 0x6C54, 0x6C56,
                       0x6C58, 0x6C5A, 0x6C5C, 0x6C5E, 0x1BCC]},
        {"start": 0x2F6E, "end": 0x2FCD,
         "format": "16 x six-byte ordinal-4 rotating-snake core descriptor indexed by F5C1 phase byte",
         "consumers": [0x6C43, 0x6C46, 0x6C4F, 0x6C54, 0x6C56,
                       0x6C58, 0x6C5A, 0x6C5C, 0x6C5E, 0x1BCC]},
        {"start": 0x2FCE, "end": 0x2FD3,
         "format": "six-byte destroyed rotating-snake link descriptor `$01A6`, resource type `$14`",
         "consumers": [0x6D1E, 0x6D21, 0x1BCC]},
        {"start": 0x2FD4, "end": 0x2FDB,
         "format": "four-s16 Stage-1 rotating-snake link collision extents `(-8,+8,-8,+8)` passed to enemy-damage dispatcher `$F6DA`",
         "consumers": [0x6C37, 0x6C77, 0x6C7A, 0x6C86, 0x6C89,
                       0x6D15, 0x6D2C, 0x6D2F, 0xF6DA]},
        {"start": 0x2FDC, "end": 0x301B,
         "format": "16 unreferenced direction-ring `(s16 dx,s16 dy)` offsets adjacent to the Stage-1 rotating-snake data: top, three upper-left, left, three lower-left, bottom, three lower-right, right, three upper-right",
         "consumers": []},
        {"start": 0x301C, "end": 0x3041,
         "format": "18 signed debris-offset words plus `$8000` terminal; `$6F4E` uses overlapping windows `(word[i],word[i+1])`, advances one word, and stops when the new current word is terminal or the allocator is full",
         "consumers": [0x6F32, 0x6F4E, 0x6F51, 0x6F52, 0x6F58,
                       0x6F5E, 0x6F61, 0x6F67, 0x6F6A, 0x6F71,
                       0x6F74, 0x6F79]},
        {"start": 0x3072, "end": 0x3079,
         "format": "four-s16 post-boss/stage object collision extents `(-56,+56,-18,+18)`",
         "consumers": [0x6F07, 0x6F0A, 0xF6DA]},
        {"start": 0x307A, "end": 0x307D,
         "format": "4 x u8 difficulty-indexed initial hit-point value `(10,14,18,30)`; `$6FB2` immediately replaces it with constant 10 in this ROM revision",
         "consumers": [0x6F9C, 0x6FA2, 0x6FA7, 0x6FB2]},
        {"start": 0x307E, "end": 0x30FD,
         "format": "4 banks x 16 u16 post-boss object sprite-descriptor pointers; each bank repeats its 8-entry palindromic animation ring twice",
         "consumers": [0x6FF7, 0x6FFA, 0x7000, 0x7003, 0x7006,
                       0x7009, 0x1C1B]},
        {"start": 0x31EE, "end": 0x31F5,
         "format": "four-s16 post-boss animated object collision extents `(-18,+18,-18,+18)` used by states `$6FD0/$709F/$7123` through `$F6DA`",
         "consumers": [0x6FD0, 0x700C, 0x700F,
                       0x709F, 0x70A2, 0x70A5,
                       0x7123, 0x7126, 0x7129, 0xF6DA]},
        {"start": 0x31F6, "end": 0x31FD,
         "format": "4 difficulty-indexed u16 firing/phase divisors `(16,8,4,2)`",
         "consumers": [0x7195, 0x71A3, 0x71A7, 0x71A9, 0x71AB,
                       0x71B0]},
        {"start": 0x31FE, "end": 0x320D,
         "format": "4 x 4-byte difficulty-indexed phase/timing parameter matrix selected by object phase low two bits in `$7189`",
         "consumers": [0x7189, 0x7195, 0x7199, 0x719B, 0x719E]},
        {"start": 0x320E, "end": 0x3215,
         "format": "4 difficulty-indexed u16 pointers to direction velocity matrices `$8F90,$8FD0,$9010,$9050` for child `$71C7`",
         "consumers": [0x71C7, 0x7207, 0x720B, 0x720D, 0x720F,
                       0x7214, 0x7219, 0x721B, 0x721D]},
        {"start": 0x3296, "end": 0x329D,
         "format": "four-s16 moving enemy collision extents `(-2,+2,-2,+2)` used by `$72D2/$7451` through `$F6DA`",
         "consumers": [0x72D2, 0x7321, 0x7324, 0x7327,
                       0x7451, 0x7460, 0x7463, 0x746C, 0x746F,
                       0xF6DA]},
        {"start": 0x329E, "end": 0x32AD,
         "format": "4 direction `(s16 Q8 vx,s16 Q8 vy)` records `(-256,0),(256,0),(0,224),(0,-224)` for state `$72D2`",
         "consumers": [0x72D8, 0x72DB, 0x72DD, 0x72DF, 0x72E1,
                       0x72E6, 0x72E9, 0x72EE, 0x10672, 0x10689]},
        {"start": 0x32AE, "end": 0x32BD,
         "format": "4 direction `(s16 terrain-probe dx,s16 terrain-probe dy)` records `(-32,0),(32,0),(0,32),(0,-32)`",
         "consumers": [0x73A0, 0x73A3, 0x73A5, 0x73A7, 0x73A9,
                       0x73AE, 0x73B1, 0x73B6]},
        {"start": 0x32BE, "end": 0x32C5,
         "format": "4 u16 pointers to five-phase descriptor sheets `$32C6,$32E4,$3320,$3302`",
         "consumers": [0x72D2, 0x7309, 0x730C, 0x730E, 0x7310,
                       0x7315, 0x7318]},
        {"start": 0x32E4, "end": 0x331F,
         "format": "two complete 5-phase sprite descriptor sheets selected by type pointers `$32BE[1]=$32E4` and `$32BE[3]=$3302` in moving enemy state `$72D2`",
         "consumers": [0x32BE, 0x72D2, 0x72F1, 0x72F9, 0x7306,
                       0x7309, 0x730C, 0x730E, 0x7310, 0x7315,
                       0x7318, 0x737D, 0x1BCC]},
        {"start": 0x3426, "end": 0x342D,
         "format": "four-s16 large terrain enemy collision extents `(-12,+12,-12,+12)` used by all five `$74B4` movement states through `$F6DA`",
         "consumers": [0x7502, 0x7526, 0x7529, 0x759F, 0x75B5,
                       0x75B8, 0x7654, 0x766F, 0x7672, 0x76AC,
                       0x76CF, 0x76D2, 0x7719, 0x7734, 0x7737,
                       0xF6DA]},
        {"start": 0x342E, "end": 0x3439,
         "format": "two unreferenced 6-byte facing variants of sprite descriptor `$05F8` preceding the active projectile/debris sheet",
         "consumers": []},
        {"start": 0x343A, "end": 0x3463,
         "format": "first 7 of 8 descriptors in 4 vertical-speed tiers x 2 horizontal-facing sheet for projectile/debris state `$780E`; final facing descriptor is existing `$3464`",
         "consumers": [0x780E, 0x781A, 0x781D, 0x7824, 0x782E,
                       0x7838, 0x783B, 0x7842, 0x7845, 0x1BCC]},
        {"start": 0x346A, "end": 0x349F,
         "format": "first 9 of 10 descriptors in 5 vertical-speed tiers x 2 facing variants for runtime enemy `$7891`; final variant is existing `$34A0`",
         "consumers": [0x7891, 0x78A1, 0x78A8, 0x78AB, 0x78B2,
                       0x78B5, 0x78BC, 0x78BF, 0x78C6, 0x78C8,
                       0x78D1, 0x78D4, 0x1BCC]},
        {"start": 0x34B6, "end": 0x34E1,
         "format": "11 x (u16 child-handler, u16 delay) spawn script",
         "consumers": [0x7944, 0x7988]},
        {"start": 0x34E2, "end": 0x3525,
         "format": "17 x (u16 child-handler, u16 delay) spawn script",
         "consumers": [0x7944, 0x7988]},
        {"start": 0x35D4, "end": 0x3675,
         "format": "27 contiguous 6-byte sprite descriptors: second descriptor of phase 14 plus two-descriptor composite phases 15..27 in the `$3526 + phase*12` animation sheet",
         "consumers": [0x79E9, 0x79EC, 0x79EE, 0x79F0, 0x79F2,
                       0x79F4, 0x79F6, 0x79F8, 0x79FC, 0x7D45]},
        {"start": 0x37C6, "end": 0x37CD,
         "format": "four-s16 large multipart enemy collision extents `(-16,+16,-16,+16)` used by state `$79D3` through `$F6DA`",
         "consumers": [0x79D3, 0x79FF, 0x7A02, 0x7A05, 0xF6DA]},
        {"start": 0x37CE, "end": 0x37DD,
         "format": "two four-s16 multipart collision records `(-10,+10,-10,+10)` used by alternating states `$7ABE/$7B6A/$7BE1/$7C22/$7D07`",
         "consumers": [0x7ABE, 0x7AC1, 0x7B6A, 0x7B6D,
                       0x7BE1, 0x7BE4, 0x7C22, 0x7C25,
                       0x7D07, 0x7D0A, 0xF6DA]},
        {"start": 0x37DE, "end": 0x37E5,
         "format": "2 constructor records `(u16 native Y,u16 field+$28)` selected by command bit 0 in `$7D68`: `(368,0)` / `(160,1)`",
         "consumers": [0x7D68, 0x7D75, 0x7D77, 0x7D7B, 0x7D7D,
                       0x7D7F, 0x7D84, 0x7D87, 0x7D8C]},
        {"start": 0x3846, "end": 0x3855,
         "format": "two unreferenced four-s16 collision records `(-24,+24,-16,+32)` and `(-24,+24,-32,+16)`",
         "consumers": []},
        {"start": 0x3856, "end": 0x385D,
         "format": "4 difficulty-indexed u16 countdowns `(32,24,16,8)` used by large tracking enemy `$8138`",
         "consumers": [0x8138, 0x8249, 0x824E, 0x8252, 0x8254,
                       0x8256, 0x825B]},
        {"start": 0x385E, "end": 0x3865,
         "format": "4 difficulty-indexed s16 child Q8 velocities `-$0400,-$0500,-$0700,-$0900` used by `$8355`",
         "consumers": [0x8355, 0x836C, 0x8370, 0x8372, 0x8374,
                       0x8379, 0x10672]},
        {"start": 0x3926, "end": 0x3949,
         "format": "6 six-byte direction/phase sprite descriptors for child projectile state `$842C`; branch selects one of four 12-byte pair bases before VBlank phase `+$06`",
         "consumers": [0x842C, 0x8432, 0x8435, 0x843D, 0x8440,
                       0x8442, 0x8447, 0x844A, 0x1C1B]},
        {"start": 0x3956, "end": 0x395D,
         "format": "four-s16 large tracking-enemy collision extents `(-16,+16,-20,+20)` passed by `$8138/$82D6` to enemy-damage dispatcher `$F6DA`",
         "consumers": [0x8138, 0x8268, 0x826B, 0x826E,
                       0x82D6, 0x831B, 0x831E, 0x8321, 0xF6DA]},
        {"start": 0x395E, "end": 0x3965,
         "format": "four-s16 child-projectile/player collision extents `(-24,+20,-2,+2)` used by `$842C` through `$F485`",
         "consumers": [0x842C, 0x844D, 0x8450, 0x8453, 0xF485]},
        {"start": 0x3966, "end": 0x39A5,
         "format": "16 direction-indexed `(s16 Q8 vx,s16 Q8 vy)` tracking vectors selected through `$1D89` every 32 updates by enemy `$8138`",
         "consumers": [0x8138, 0x8143, 0x815E, 0x8163, 0x8166,
                       0x816B, 0x816E, 0x8173, 0x8182, 0x10672,
                       0x10689]},
        {"start": 0x39AC, "end": 0x39B3,
         "format": "four-s16 `$8469/$8490` wall-bouncing enemy collision extents `(-12,+12,-12,+12)`",
         "consumers": [0x8490, 0x84AB, 0x84AE, 0xF694]},
        {"start": 0x39B4, "end": 0x39C3,
         "format": "4 difficulty records `(s16 child Q8 vx,u16 spawn cadence)`: `(-704,54),(-960,32),(-1472,24),(-1984,16)`",
         "consumers": [0x8561, 0x8571, 0x8575, 0x8577, 0x8579,
                       0x857B, 0x8580, 0x8585, 0x858B]},
        {"start": 0x39C4, "end": 0x39CD,
         "format": "5 s16 spawned-child Y offsets `(0,-16,+8,+16,-8)` cycled by `$865E`",
         "consumers": [0x865E, 0x867D, 0x8680, 0x8683, 0x8688,
                       0x868B, 0x868F, 0x8695]},
        {"start": 0x3C12, "end": 0x3C19,
         "format": "four-s16 spawned animated child collision extents `(-8,+8,-8,+8)` used by `$8861/$893E` through `$F694`",
         "consumers": [0x8861, 0x88BF, 0x88C2, 0x88C5,
                       0x893E, 0x8966, 0x8969, 0x896C, 0xF694]},
        {"start": 0x3C1A, "end": 0x3C21,
         "format": "4 difficulty-indexed u16 phase masks `(127,31,15,7)` for animated child `$893E`",
         "consumers": [0x893E, 0x8950, 0x8954, 0x8956, 0x8958]},
        {"start": 0x3C22, "end": 0x3C31,
         "format": "2 difficulty modes x 4 u16 pointers to three-state descriptor roots `$3C32,$3C38,$3C3E` / `$3C44,$3C4A,$3C50`",
         "consumers": [0x893E, 0x894F, 0x895D, 0x895F, 0x8961,
                       0x8963, 0x8966]},
        {"start": 0x3AF6, "end": 0x3AFD,
         "format": "four-s16 animated enemy collision extents `(-4,+4,-4,+4)` used by `$86EA` through `$F694`",
         "consumers": [0x86EA, 0x8713, 0x8716, 0x8719, 0xF694]},
        {"start": 0x3AFE, "end": 0x3B11,
         "format": "5 timed controller records `(u16 elapsed threshold,u16 command)`; command bits `$8000/$4000` replace difficulty timer/count fields and plain commands replace target field, final threshold `$FFFF`",
         "consumers": [0x875D, 0x876A, 0x8798, 0x87BA, 0x87D7,
                       0x87DA, 0x87DD, 0x87E4, 0x87E8, 0x87ED,
                       0x87F9, 0x87FE, 0x880A, 0x8810]},
        {"start": 0x3B12, "end": 0x3B21,
         "format": "4 difficulty records `(u16 spawn cadence,u16 repeat count)`: `(36,3),(24,3),(16,2),(8,1)`",
         "consumers": [0x87BA, 0x87BD, 0x87C1, 0x87C3, 0x87C5,
                       0x87C7, 0x87CC, 0x87CF, 0x87D4]},
        {"start": 0x3B22, "end": 0x3B29,
         "format": "4 difficulty-indexed u16 pointers to 16-direction velocity matrices `$9010,$9050,$9090,$90D0`",
         "consumers": [0x890A, 0x8912, 0x8916, 0x8918, 0x891A,
                       0x891F, 0x8921, 0x8927]},
        {"start": 0x3B2A, "end": 0x3B31,
         "format": "4 difficulty-indexed s16 Q8 horizontal velocities `-$0180,-$0300,-$0380,-$0400` for spawned child `$8861`",
         "consumers": [0x8861, 0x8867, 0x886B, 0x886D, 0x886F,
                       0x8874, 0x10672]},
        {"start": 0x3FE6, "end": 0x4005,
         "format": "8 x 2-u16 direction-pair descriptor-pointer tables selected through sparse matrix `$3FC6`; entries point to descriptor roots `$4006..$4078`",
         "consumers": [0x3FC6, 0x9068, 0x90C2, 0x90C6, 0x90C8,
                       0x90CA, 0x90CC, 0x90D0, 0x90D4, 0x90D6,
                       0x90D8, 0x90DA, 0x1BCC]},
        {"start": 0x3C44, "end": 0x3C55,
         "format": "3 unreferenced six-byte alternate child descriptors `$01C2,$01C4,$01C6`",
         "consumers": []},
        {"start": 0x3C56, "end": 0x3C5D,
         "format": "four-s16 terrain-aware enemy collision extents `(-12,+12,-12,+12)` used by states `$89B0/$8AEE` through `$F694`",
         "consumers": [0x89B0, 0x8A92, 0x8A95,
                       0x8AEE, 0x8BE0, 0x8BE3, 0xF694]},
        {"start": 0x3C5E, "end": 0x3EDD,
         "format": "6 foreground tile-replacement streams selected by stage commands `$4000..$4005`; each is (u16 packed tilemap offset, u16 tile) terminated by zero offset",
         "consumers": [0x8C1F, 0x8D54, 0x8D58, 0x8D60, 0x8D67,
                       0x8D69, 0x8D6B, 0x8D6D, 0x8D71, 0x8D73,
                       0x8D77, 0x8D7E, 0xFA55, 0xFA5F, 0xFA6C]},
        {"start": 0x3EDE, "end": 0x3EE5,
         "format": "four-s16 timed stage-control collision extents `(-32,+32,-32,+32)`",
         "consumers": [0x8D3C, 0x8D3F, 0xF485, 0xF578]},
        {"start": 0x3EE6, "end": 0x3F25,
         "format": "16 x (u16 target X,u16 target Y), RNG-indexed at stride 4 by stage-control object `$8EFA`",
         "consumers": [0x8F06, 0x8F09, 0x8F16, 0x8F18, 0x8F1A,
                       0x8F1C, 0x8F20, 0x8F2B]},
        {"start": 0x3F86, "end": 0x3FC5,
         "format": "4 difficulty tiers x 4 cardinal `(s16 Q8 vx,s16 Q8 vy)` vectors; magnitudes `$0100,$0180,$0200,$0300`",
         "consumers": [0x8F86, 0x8F9B, 0x8FA5, 0x8FB4, 0x8FB9,
                       0x8FBC, 0x8FBD, 0x8FCC, 0x8FD1, 0x10672,
                       0x10689]},
        {"start": 0x407E, "end": 0x4085,
         "format": "four-s16 multipart enemy collision extents `(-12,+12,-12,+12)` used by states `$8F86/$91CC`",
         "consumers": [0x8F86, 0x8F90, 0x8F93,
                       0x91CC, 0x90A8, 0x90AB, 0xF6DA]},
        {"start": 0x4086, "end": 0x40B5,
         "format": "8 multipart child constructor records `(u16 child handler,u16 native X,u16 native Y)` indexed by event command low three bits",
         "consumers": [0x915B, 0x9168, 0x916A, 0x916E, 0x9170,
                       0x9172, 0x9174, 0x9176, 0x917B, 0x917E,
                       0x9183, 0x9186, 0x918B]},
        {"start": 0x40B6, "end": 0x40C5,
         "format": "2 modes x 4 event classes u16 child lifetime/health values: four `$0050` followed by four `$0020`; stage flag `$2F2D` selects mode",
         "consumers": [0x918E, 0x9190, 0x9194, 0x9197, 0x919E,
                       0x91A1, 0x91A6, 0x91A9, 0x91AD]},
        {"start": 0x40C6, "end": 0x411D,
         "format": "22 x (u16 child-handler, u16 delay) multipart script",
         "consumers": [0x91DB, 0x9232]},
        {"start": 0x411E, "end": 0x414D,
         "format": "8 x (u16 child-handler, u16 field10, u16 script-pointer)",
         "consumers": [0x95B7, 0x95C1, 0x95C8]},
        {"start": 0x414E, "end": 0x417D,
         "format": "8 x (u16 child-handler, u16 field10, u16 script-pointer)",
         "consumers": [0x95B7, 0x95C1, 0x95C8]},
        {"start": 0x4196, "end": 0x419D,
         "format": "four-s16 mobile-enemy collision extents `(-4,+4,-4,+4)` passed by state `$95F1` to enemy-damage dispatcher `$F694`",
         "consumers": [0x95F1, 0x9612, 0x962D, 0x9635, 0x9638,
                       0x963B, 0xF694]},
        {"start": 0x419E, "end": 0x41FD,
         "format": "16 unreferenced 6-byte direction-ring sprite descriptors `(word $F0F0, sprite code, attribute)` preceding the active `$41FE` sheet",
         "consumers": []},
        {"start": 0x425E, "end": 0x427B,
         "format": "5 six-byte sprite descriptors for enemy state `$92D8/$94F6`: four animation phases `$0990,$0992,$0994,$0992` plus alternate `$0996`",
         "consumers": [0x92D8, 0x9300, 0x930D, 0x9311,
                       0x93C2, 0x93C9, 0x93CC, 0x93D8,
                       0x94F6, 0x951C, 0x9520, 0x9444, 0x1BCC]},
        {"start": 0x427C, "end": 0x4283,
         "format": "four-s16 enemy collision extents `(-8,+8,-8,+8)` used by `$92D8/$94F6` through `$F6DA`",
         "consumers": [0x92D8, 0x9324, 0x9327,
                       0x94F6, 0x9533, 0x9536, 0xF6DA]},
        {"start": 0x4284, "end": 0x428B,
         "format": "4 difficulty-indexed u16 pointers to direction velocity matrices `$9010,$9050,$9090,$90D0` for spawned child `$9674`",
         "consumers": [0x9674, 0x96BE, 0x96C2, 0x96C4, 0x96C6,
                       0x96CB, 0x96D0, 0x96D2, 0x96D4]},
        {"start": 0x438C, "end": 0x4393,
         "format": "four-s16 three-phase enemy/player collision extents `(-10,+10,-10,+10)` used by `$983B/$98A8` through `$F485`",
         "consumers": [0x983B, 0x9865, 0x9868, 0x986B,
                       0x98A8, 0x98F0, 0x98F3, 0x98F6, 0xF485]},
        {"start": 0x4394, "end": 0x43AB,
         "format": "4 unreferenced Dobkeratops arena terrain-path records `(u16 native X,u16 native Y,u16 path pointer)` for paths `$46CC,$4754,$47C6,$482E`",
         "consumers": []},
        {"start": 0x4460, "end": 0x449F,
         "format": "16 selector-indexed `(s16 Q8 vx,s16 Q8 vy)` vectors installed as `$A133` child motion table through parent field `+$28` and consumed by `$F8A7`",
         "consumers": [0x9A2E, 0x9A40, 0x9A57, 0x9A5A, 0x9A5F,
                       0x9A64, 0xA133, 0xA18E, 0xA193, 0xF8A7,
                       0xF8D0, 0xF8D6, 0xF8DD]},
        {"start": 0x44A0, "end": 0x44A5,
         "format": "6-byte boss-controller transition sprite descriptor `($F0F0,$02F6,$5000)` selected during timer interval `$00C0..$00CF`",
         "consumers": [0x9B26, 0x9B39, 0x9B4E, 0x9B51, 0x9B54,
                       0x9B59, 0x9B5C, 0x9B69, 0x1BCC]},
        {"start": 0x4526, "end": 0x452D,
         "format": "four-s16 Dobkeratops body collision extents `(-10,+10,-10,+10)` used by vulnerable state `$9C70` through `$F75F`",
         "consumers": [0x9C70, 0x9C9B, 0x9C9E, 0x9CA1, 0xF75F]},
        {"start": 0x452E, "end": 0x454D,
         "format": "16-word Dobkeratops child auxiliary control block written verbatim as pointer to every spawned child's field `+$3E`; final word `$8000` is its terminal marker",
         "consumers": [0x9D30, 0x9D55, 0x9D62, 0x9D7A, 0x9D7F,
                       0x9D83, 0x9D86]},
        {"start": 0x454E, "end": 0x46C1,
         "format": "62 x (s16 dx, s16 dy, u16 child-handler)",
         "consumers": [0x9D58, 0x9D6A, 0x9D73]},
        {"start": 0x46C2, "end": 0x46C3,
         "format": "u16 `$8000` Dobkeratops spawn-list terminator",
         "consumers": [0x9D86]},
        {"start": 0x46C4, "end": 0x46CB,
         "format": "4 x s16 Dobkeratops arena-writer collision extents `(-8,+8,-8,+8)`",
         "consumers": [0x9F84, 0xF75F]},
        {"start": 0x46CC, "end": 0x4753,
         "format": "68 x (s8 tilemap-low delta, s8 tilemap-high delta), final `$8000`; MAME PC `$A010` verified",
         "consumers": [0x9FE9, 0xA01B, 0xA023, 0xA025]},
        {"start": 0x4754, "end": 0x47C5,
         "format": "57 x (s8 tilemap-low delta, s8 tilemap-high delta), final `$8000`; MAME PC `$A010` verified",
         "consumers": [0x9FE9, 0xA01B, 0xA023, 0xA025]},
        {"start": 0x47C6, "end": 0x482D,
         "format": "52 x (s8 tilemap-low delta, s8 tilemap-high delta), final `$8000`; MAME PC `$A010` verified",
         "consumers": [0x9FE9, 0xA01B, 0xA023, 0xA025]},
        {"start": 0x482E, "end": 0x48A9,
         "format": "62 x (s8 tilemap-low delta, s8 tilemap-high delta), final `$8000`; MAME PC `$A010` verified",
         "consumers": [0x9FE9, 0xA01B, 0xA023, 0xA025]},
        {"start": 0x48AA, "end": 0x4CAB,
         "format": "19 Dobkeratops tentacle motion scripts x 9 six-byte steps `(Q8 vx, raw Q8 vy negated by handler, duration|loop-bit)`; ninth step loops",
         "consumers": [0x9A40, 0xA035, 0xA08B, 0xA092, 0xA098,
                       0xA0A1, 0xA0D3, 0xA0DF, 0xA0E3, 0xA0E9,
                       0xA133, 0xA164, 0xA169, 0xA16F, 0xA175,
                       0xA17E, 0xA185, 0xA1A3, 0xA1D9, 0xA1DE,
                       0xA1E1, 0xA1E7, 0xA1F0, 0xA1FC, 0xA200,
                       0xA206]},
        {"start": 0x4CBE, "end": 0x4CC5,
         "format": "four-s16 Dobkeratops tentacle-tip collision extents `(-6,+6,-6,+6)`",
         "consumers": [0xA049, 0xA0B6, 0xA15E, 0xA1D3, 0xF75F]},
        {"start": 0x4D1C, "end": 0x4D61,
         "format": "18 overlapping (u16 scroll-position threshold, u16 phase 0..3) boss-presentation records; last threshold `$FFFF`",
         "consumers": [0xA26D, 0xA5C5, 0xA5CB, 0xA5DC, 0xA5E6]},
        {"start": 0x4D62, "end": 0x4D81,
         "format": "8 x (u16 multipart spawn command, u16 frame delay); final delay `$FFFF` cannot expire before controller `$1780` cutoff",
         "consumers": [0xA5A4, 0xA5A9, 0xA5AC, 0xA5B8, 0xA5BD,
                       0xA5C0]},
        {"start": 0x4D82, "end": 0x4DA9,
         "format": "4 x (u16 flashing tile source, u16 normal tile source, u8 rows, u8 columns, u16 destination X, u16 destination Y)",
         "consumers": [0xA5EB, 0xA5F8, 0xA600, 0xA608, 0xA610,
                       0xA618, 0xA638, 0xA660, 0xA66D]},
        {"start": 0x4DAA, "end": 0x51C9,
         "format": "8 boss-presentation tile rectangles addressed by `$4D82`: two 7x8, two 9x8, two 7x8 and two 10x8 u16 tile arrays",
         "consumers": [0xA5F8, 0xA600, 0xA660, 0xA66A, 0xA682]},
        {"start": 0x51CA, "end": 0x51D9,
         "format": "8 x u16 forward-order pointer to 4x12 boss tile-patch frames `$51EA..$548A`",
         "consumers": [0xA34F, 0xA352, 0xA356, 0xA35D]},
        {"start": 0x51DA, "end": 0x51E9,
         "format": "8 x u16 reverse-order pointer to the same 4x12 boss tile-patch frames",
         "consumers": [0xA390, 0xA393, 0xA397, 0xA3CE, 0xA3D1,
                       0xA3D5, 0xA39E, 0xA3DC]},
        {"start": 0x51EA, "end": 0x54E9,
         "format": "8 x 96-byte (4 rows x 12 u16 cells) boss tile-patch frame",
         "consumers": [0xA356, 0xA397, 0xA3D5, 0xA578, 0xA584,
                       0xA58B, 0xA58D, 0xA593, 0xA596, 0xA59F]},
        {"start": 0x54EA, "end": 0x54F1,
         "format": "four-s16 boss collision extents `(-16,+16,-8,+8)`",
         "consumers": [0xA27F, 0xA2B7, 0xF7E4, 0xF775]},
        {"start": 0x54F2, "end": 0x5601,
         "format": "68 x (s16 dx, s16 dy) coordinate samples for boss debris/particle path",
         "consumers": [0xA6E0, 0xA6E3, 0xA6E9, 0xA6F2]},
        {"start": 0x5602, "end": 0x5843,
         "format": "288 x u16 pointer into `$54F2..$5601` coordinate samples plus zero loop sentinel",
         "consumers": [0xA4F5, 0xA6E0, 0xA6F9, 0xA6FD, 0xA700,
                       0xA703, 0xA707]},
        {"start": 0x5844, "end": 0x5847,
         "format": "4 x u8 difficulty-indexed initial firing timer `(48,40,32,24)`",
         "consumers": [0xA7C9, 0xA7CF, 0xA8F6, 0xA8FC]},
        {"start": 0x5848, "end": 0x584F,
         "format": "4 x u16 difficulty-indexed projectile reload period `($0300,$0380,$0400,$0480)`",
         "consumers": [0xAB4C, 0xAB52, 0xAB54, 0xAE46, 0xAE4C,
                       0xAE4E]},
        {"start": 0x5850, "end": 0x585F,
         "format": "8 x u16 RNG-indexed vertical spawn offset for upper projectile emitter",
         "consumers": [0xAB38, 0xAB3D, 0xAB41, 0xAB46]},
        {"start": 0x5860, "end": 0x586F,
         "format": "8 x u16 RNG-indexed vertical spawn offset for lower projectile emitter",
         "consumers": [0xAE32, 0xAE37, 0xAE3B, 0xAE40]},
        {"start": 0x5870, "end": 0x5871,
         "format": "first u16 of 16-way direction-indexed projectile vector-table pointer array; remaining overlapping words are sprite-producer covered",
         "consumers": [0xAC6B, 0xAC6E, 0xAC71, 0xAC76, 0xF63A]},
        {"start": 0x58E6, "end": 0x58ED,
         "format": "four-s16 multipart-boss debris collision extents `(-4,+4,-4,+4)`",
         "consumers": [0xAF35, 0xAF38, 0xAF3D, 0xAF40, 0xAFAD,
                       0xAFB0, 0xF485, 0xF493, 0xF578, 0xF694]},
        {"start": 0x58EE, "end": 0x594D,
         "format": "23 x (s16 debris dx,s16 debris dy) upper multipart-boss explosion path plus `$8000,0` loop sentinel",
         "consumers": [0xAAFB, 0xB062, 0xB067, 0xB06A, 0xB0A7,
                       0xB0AD, 0xB0B3, 0xB0B6, 0xB0BD, 0xB0C1,
                       0xB0CA, 0xB0CD]},
        {"start": 0x594E, "end": 0x59A5,
         "format": "21 x (s16 debris dx,s16 debris dy) middle multipart-boss explosion path plus `$8000,0` loop sentinel",
         "consumers": [0xAC45, 0xB062, 0xB067, 0xB06A, 0xB0A7,
                       0xB0AD, 0xB0B3, 0xB0B6, 0xB0BD, 0xB0C1,
                       0xB0CA, 0xB0CD]},
        {"start": 0x59A6, "end": 0x5A01,
         "format": "22 x (s16 debris dx,s16 debris dy) lower multipart-boss explosion path plus `$8000,0` loop sentinel",
         "consumers": [0xADF5, 0xB062, 0xB067, 0xB06A, 0xB0A7,
                       0xB0AD, 0xB0B3, 0xB0B6, 0xB0BD, 0xB0C1,
                       0xB0CA, 0xB0CD]},
        {"start": 0x5A9A, "end": 0x5AB9,
         "format": "4 x four-s16 collision extents for three multipart-boss bodies and core",
         "consumers": [0xAD67, 0xAD6A, 0xAD7C, 0xAD7F, 0xAD82,
                       0xAD85, 0xAD88, 0xAD8B, 0xF7F1]},
        {"start": 0x5ABA, "end": 0x5AF9,
         "format": "8 x (u16 body-A route-list, u16 body-B route-list, u16 core route-list, u16 zero); indexed at stride 8",
         "consumers": [0xA770, 0xA775, 0xA778, 0xA7EA, 0xA7EF,
                       0xA7F2, 0xA8C7, 0xA8CC, 0xA8CF]},
        {"start": 0x5AFA, "end": 0x5B53,
         "format": "9 x (4 u16 six-byte motion-stream pointers plus zero terminator); route permutations for three boss bodies",
         "consumers": [0xA778, 0xA780, 0xA7F2, 0xA7FA, 0xA8CF,
                       0xA8D7, 0xB00C, 0xB01B, 0xB01F, 0xB022,
                       0xB029]},
        {"start": 0x5B54, "end": 0x5F07,
         "format": "10 overlapping multipart-boss motion streams of (s16 vx/2, s16 vy/2, u16 doubled duration), each ending with first-word `$8000` record",
         "consumers": [0xA780, 0xA786, 0xA78C, 0xA793, 0xA7FA,
                       0xA800, 0xA806, 0xA80D, 0xA8D7, 0xA8DD,
                       0xA8E3, 0xA8EA, 0xAFE6, 0xAFF0, 0xAFF6,
                       0xB00C, 0xB010, 0xB013, 0xB02C, 0xB02F,
                       0xB037, 0xB040]},
        {"start": 0x5F08, "end": 0x5F5B,
         "format": "unreferenced alternate B073-format path: 20 x (s16 dx,s16 dy) plus `$8000,0` terminator",
         "consumers": []},
        {"start": 0x5F5C, "end": 0x5F63,
         "format": "4 x u16 difficulty-indexed multipart-boss retarget timer `(51,32,24,16)`",
         "consumers": [0xB2C1, 0xB2C5, 0xB2C7, 0xB2C9]},
        {"start": 0x5F64, "end": 0x5F6B,
         "format": "4 x u16 difficulty-indexed base of 16-direction velocity table",
         "consumers": [0xB61E, 0xB621, 0xB626, 0xB62C, 0xB62E,
                       0xB633, 0xB637, 0xB63D, 0xF63A]},
        {"start": 0x5A20, "end": 0x5A25,
         "format": "unreferenced 6-byte sprite descriptor `($F038,$0A21,$4000)` at the end of the preceding composite sheet",
         "consumers": []},
        {"start": 0x5A26, "end": 0x5A45,
         "format": "8 unreferenced `(s16 dx,s16 dy)` child placement offsets between descriptor sheets; no runtime instruction or ROM pointer reaches this alternate block",
         "consumers": []},
        {"start": 0x5A64, "end": 0x5A69,
         "format": "unreferenced six-byte sprite descriptor `($B008,$0A64,$5000)`",
         "consumers": []},
        {"start": 0x5A6A, "end": 0x5A71,
         "format": "four-s16 multipart boss child collision extents `(-48,-8,-72,+8)` used by `$AB62` through `$F75F`",
         "consumers": [0xAB62, 0xABD2, 0xABD5, 0xF75F]},
        {"start": 0x5A72, "end": 0x5A81,
         "format": "4 unreferenced `(s16 debris dx,s16 debris dy)` alternate offsets adjacent to boss child collision data",
         "consumers": []},
        {"start": 0x5F6C, "end": 0x6001,
         "format": "37 x (s16 child dx, s16 child dy) multipart-boss spawn position plus look-ahead `$8000` terminator",
         "consumers": [0xB209, 0xB224, 0xB227, 0xB233, 0xB276,
                       0xB27F, 0xB0A7, 0xB0AA, 0xB0B3, 0xB0BD,
                       0xB0C1]},
        {"start": 0x6002, "end": 0x6081,
         "format": "32 x (u16 target X,u16 target Y), RNG-indexed at stride 4 with Manhattan-distance rejection",
         "consumers": [0xB315, 0xB318, 0xB31B, 0xB31D, 0xB31F,
                       0xB321, 0xB326, 0xB32B, 0xB336, 0xB341,
                       0xB346, 0xB349]},
        {"start": 0x612C, "end": 0x616B,
         "format": "32 x u16 RNG-indexed projectile handler",
         "consumers": [0xBAE6]},
        {"start": 0x631A, "end": 0x6339,
         "format": "16 x s16 Q8 horizontal velocity profile selected by `(object+$32 & $F0)>>3`: four `$FF00`, eight zero, four `$0100`",
         "consumers": [0xBF14, 0xBF18, 0xBF1B, 0x10672]},
        {"start": 0x633A, "end": 0x6379,
         "format": "32 x u16 phase-indexed sprite-descriptor pointer selected by `(object+$32 & $F8)>>2`; symmetric `$63E6/$63F2/$63FE/$640A` profile",
         "consumers": [0xBF26, 0xBF2A, 0xBF2D, 0x1C1B]},
        {"start": 0x637A, "end": 0x637B,
         "format": "unreferenced duplicate terminal u16 sprite-descriptor pointer `$63E6` following the 32-entry phase table",
         "consumers": []},
        {"start": 0x637C, "end": 0x63BB,
         "format": "32 x u16 phase-indexed collision-record pointer selected by `(object+$32 & $F8)>>2`; symmetric `$63C6/$63CE/$63D6/$63DE` profile",
         "consumers": [0xBF5A, 0xBF5E, 0xBF61, 0xF6DA]},
        {"start": 0x63BC, "end": 0x63BD,
         "format": "unreferenced duplicate terminal u16 collision-record pointer `$63C6` following the 32-entry phase table",
         "consumers": []},
        {"start": 0x63BE, "end": 0x63C5,
         "format": "fixed four-s16 collision/damage extents `(-6,+6,-10,+11)`",
         "consumers": [0xBF86, 0xBF89, 0xF6DA]},
        {"start": 0x63C6, "end": 0x63E5,
         "format": "4 x four-s16 phase collision/damage extents: fixed X `(-40,-16)`, Y maximum grows `+2,+8,+16,+24`",
         "consumers": [0xBF5A, 0xBF5E, 0xBF61, 0xF6DA]},
        {"start": 0x6416, "end": 0x64B5,
         "format": "40 x (u16 threshold, u16 callback), last is sentinel",
         "consumers": [0xC0D3, 0xC0D8, 0xC0DC]},
        {"start": 0x64B4, "end": 0x64BB,
         "format": "four-s16 final-stage gate collision extents `(-14,+48,-48,+48)`",
         "consumers": [0xC0F6, 0xC0FC, 0xC135, 0xF578, 0xF75F]},
        {"start": 0x64BC, "end": 0x69BB,
         "format": "5 x 256-byte gate animation frame: 8 rows x 8 cells x (u16 tile, u16 attribute)",
         "consumers": [0xC30A, 0xC30F, 0xC315, 0xC31B, 0xC320,
                       0xC326, 0xC32C, 0xC332, 0xC33F, 0xC357,
                       0xC35C, 0xC366]},
        {"start": 0x69BC, "end": 0x69CB,
         "format": "8 x u16 opening-animation pointer: first four 7x6 gate-patch frames forward then reverse",
         "consumers": [0xC3C3, 0xC3CC, 0xC3D0, 0xC3D2, 0xC3D4]},
        {"start": 0x69CC, "end": 0x69EB,
         "format": "16 x u16 closing-animation pointer over gate-patch frames 0 and 5..8",
         "consumers": [0xC3FE, 0xC407, 0xC40B, 0xC40D, 0xC40F]},
        {"start": 0x69EC, "end": 0x6CDF,
         "format": "9 x 84-byte gate patch frame: 6 rows x 7 u16 tile cells",
         "consumers": [0xC3D4, 0xC40F, 0xC434, 0xC435, 0xC44C,
                       0xC45A, 0xC45D, 0xC469]},
        {"start": 0x6CE0, "end": 0x6F87,
         "format": "68 x 10-byte final-stage spawn record",
         "consumers": [0xC627, 0xC62E, 0xC632, 0xC63D, 0xC644]},
        {"start": 0x6F88, "end": 0x6F89,
         "format": "u16 `$FFFF` terminal threshold after final-stage spawn records",
         "consumers": [0xC627]},
        {"start": 0x6F8A, "end": 0x7301,
         "format": "296 x (s8 background-Y velocity, s8 background-X velocity, u8 duration); final duration `$80` sentinel",
         "consumers": [0xC48B, 0xC48E, 0xC496, 0xC49F,
                       0xC517, 0xC5F8, 0xC5FB, 0xC601, 0xC608]},
        {"start": 0x7302, "end": 0x77B7,
         "format": "27 foreground tile packages: (u16 collision pointer, s16 dx, s16 dy, u8 columns, u8 rows, u16 cells); three unused cells `$7732..$7737`",
         "consumers": [0xC656, 0xC662, 0xC66E, 0xC67A, 0xC686,
                       0xC692, 0xC69E, 0xC6AA, 0xC6B6, 0xC6C2,
                       0xC6CE, 0xC6DA, 0xC6E6, 0xC6F2, 0xC6FE,
                       0xC70A, 0xC716, 0xC722, 0xC72E, 0xC73A,
                       0xC746, 0xC752, 0xC75E, 0xC76A, 0xC776,
                       0xC782, 0xC78E, 0xC797, 0xC8F3, 0xC903]},
        {"start": 0x77B8, "end": 0x788F,
         "format": "27 x four-s16 foreground collision extent table referenced by tile-package word 0",
         "consumers": [0xC7D9, 0xC93F, 0xF4AA, 0xF525,
                       0xF548, 0xF560]},
        {"start": 0x7890, "end": 0x7937,
         "format": "4 background tile packages: (u16 collision pointer, s16 dx, s16 dy, u8 columns, u8 rows, u16 cells)",
         "consumers": [0xC9A0, 0xC9AC, 0xC9B8, 0xC9C4,
                       0xC9CD, 0xCB2E, 0xCB41]},
        {"start": 0x7938, "end": 0x7957,
         "format": "4 x four-s16 background collision extent table referenced by tile-package word 0",
         "consumers": [0xCA0F, 0xCB7D, 0xF4AA, 0xF525,
                       0xF548, 0xF560]},
        {"start": 0x7958, "end": 0x796F,
         "format": "4 used (s16 dx,s16 dy) explosion offsets, one skipped pair, then `$8000,0` loop sentinel",
         "consumers": [0xCE94, 0xCEB1, 0xCEB7, 0xCEBD,
                       0xCEC7, 0xCECB, 0xCED4]},
        {"start": 0x7A0C, "end": 0x7A23,
         "format": "4 six-byte paired late-body sprite descriptors `$0816,$0814,$0812,$0810` rendered by state `$CE9F`",
         "consumers": [0xCE9F, 0xCF27, 0xCF2A, 0x1BCC]},
        {"start": 0x7A3C, "end": 0x7A43,
         "format": "four-s16 first collision extents `(-40,+32,-15,+15)` for paired late-stage body `$CD6B/$CE9F`",
         "consumers": [0xCD6B, 0xCD88, 0xCD8B,
                       0xCE9F, 0xCE33, 0xCE36, 0xF6DA]},
        {"start": 0x7A44, "end": 0x7A4B,
         "format": "four-s16 second collision extents `(-32,+64,-16,+16)` for state `$CEEA`",
         "consumers": [0xCEEA, 0xCF4F, 0xCF52, 0xF6DA]},
        {"start": 0x7A4C, "end": 0x7A53,
         "format": "four-s16 child collision extents `(-4,+4,-4,+4)` used by `$CF9C` through player-projectile dispatcher `$F485`",
         "consumers": [0xCF9C, 0xCFBE, 0xCFC1, 0xF485]},
        {"start": 0x7A54, "end": 0x7A6B,
         "format": "5 `(s16 debris dx,s16 debris dy)` offsets plus `$8000,0` loop terminal, shared by paired-body death states `$D225/$D275`",
         "consumers": [0xD225, 0xD239, 0xD244, 0xD275, 0xD279,
                       0xD27C, 0xD285, 0xCE94, 0xCEB1, 0xCEB7,
                       0xCEBD, 0xCEC7, 0xCECB, 0xCED4]},
        {"start": 0x7CF0, "end": 0x7D31,
         "format": "11 six-byte late-stage child spawn records `(s16 Q8 vx,s16 Q8 vy,u16 sprite descriptor pointer)` shared through six 16-word pointer tables `$7C30..$7CEF`",
         "consumers": [0x7C30, 0x7C50, 0x7C70, 0x7C90, 0x7CB0,
                       0x7CD0, 0xD660, 0xD66A, 0xD66D, 0xD670,
                       0xD674, 0xD677, 0xD67B, 0xD7B9, 0xD807,
                       0xD82C, 0xD839, 0x1BCC, 0x10672, 0x10689]},
        {"start": 0x7AEA, "end": 0x7AF1,
         "format": "four-s16 late-stage parent-linked enemy collision extents `(-12,+12,+2,+12)` passed by `$D28F` to `$F6DA`",
         "consumers": [0xD28F, 0xD2DA, 0xD2DD, 0xF6DA]},
        {"start": 0x7AF2, "end": 0x7B27,
         "format": "13 `(s16 debris dx,s16 debris dy)` destruction offsets followed by single-word `$8000` terminal, consumed by `$D549` at 4-byte stride",
         "consumers": [0xD549, 0xD568, 0xD56B, 0xD56C, 0xD572,
                       0xD578, 0xD57B, 0xD581, 0xD584, 0xD58B,
                       0xD58E, 0xD593]},
        {"start": 0x7E46, "end": 0x7E4D,
         "format": "four-s16 parent-linked enemy collision extents `(-12,+12,-10,+10)` passed by `$D608` to enemy-damage dispatcher `$F6DA`",
         "consumers": [0xD608, 0xD697, 0xD69A, 0xD69D, 0xF6DA]},
        {"start": 0x7E4E, "end": 0x7E55,
         "format": "four-s16 child-projectile/player collision extents `(-8,+8,-8,+8)` used by `$D807/$D892` through `$F485`",
         "consumers": [0xD807, 0xD83C, 0xD84A, 0xD84D, 0xD850,
                       0xD892, 0xD8AA, 0xD8AD, 0xD8B0, 0xF485]},
        {"start": 0x7E56, "end": 0x7E99,
         "format": "16 parent-progression records `(u16 threshold,u16 descriptor-table byte offset|spawn bit $8000)` followed by terminal `(0xFFFF,4)`; `$D90E` consumes records sequentially at 4-byte stride",
         "consumers": [0xD8B7, 0xD8F0, 0xD90E, 0xD91A, 0xD91D,
                       0xD921, 0xD96C, 0xD96F, 0xD972, 0xD977,
                       0xD97B, 0xD97F, 0xD982, 0xD987, 0xD9A3,
                       0xD9BE]},
        {"start": 0x8066, "end": 0x80C5,
         "format": "4 x 24-byte moving-emitter control record: five input-phase (s16 Q8 vx,s16 Q8 vy) pairs followed by (s16 child dx,s16 child dy); velocity components are `-$0200/0/+$0200`",
         "consumers": [0xDB68, 0xDB75, 0xDB82, 0xDB8F, 0xDC7C,
                       0xDC7F, 0xDC8E, 0xDC94, 0xDCA1, 0xDCAB,
                       0xE603, 0xE606, 0xE609, 0xE60C, 0x10672,
                       0x10689]},
        {"start": 0x80C6, "end": 0x80CD,
         "format": "four-s16 moving-emitter collision extents `(-8,+8,-8,+8)`",
         "consumers": [0xDBFB, 0xDBFE, 0xF6DA]},
        {"start": 0x80CE, "end": 0x812D,
         "format": "23 x (s16 debris dx,s16 debris dy) moving-emitter destruction path plus `$8000,0` loop sentinel",
         "consumers": [0xDEB9, 0xDF0B, 0xDF11, 0xDF1A, 0xDF21,
                       0xDF25, 0xDF2E]},
        {"start": 0x8304, "end": 0x830B,
         "format": "four-s16 upper variant collision extents `(-12,+12,-14,-2)`",
         "consumers": [0xE26F, 0xE2F9, 0xE2FC, 0xF6DA]},
        {"start": 0x830C, "end": 0x8313,
         "format": "four-s16 lower variant collision extents `(-12,+12,+2,+14)`",
         "consumers": [0xE27C, 0xE2F9, 0xE2FC, 0xF6DA]},
        {"start": 0x8314, "end": 0x832B,
         "format": "4 x 6-byte resource-owner record `(u16 lifetime,u16 signed-horizontal-velocity-table,u16 phase/value)`",
         "consumers": [0xE43D, 0xE43F, 0xE443, 0xE445, 0xE447,
                       0xE449, 0xE44B, 0xE453, 0xE45B]},
        {"start": 0x832C, "end": 0x836B,
         "format": "32 x positive s16 Q8 horizontal velocity sample selected by RNG `$E578&$1F`",
         "consumers": [0xE453, 0xE568, 0xE578, 0xE57B, 0xE57E,
                       0xE5D4, 0xE5D7, 0x10672]},
        {"start": 0x836C, "end": 0x83AB,
         "format": "32 x negative s16 Q8 horizontal velocity sample; exact two's-complement mirror of `$832C..$836B`",
         "consumers": [0xE453, 0xE568, 0xE578, 0xE57B, 0xE57E,
                       0xE5D4, 0xE5D7, 0x10672]},
        {"start": 0x60F2, "end": 0x6109,
         "format": "4 six-byte late-boss child sprite descriptors `$0BD0,$0BD2,$0BD4,$0BD6` used by states `$B997/$BAA7`",
         "consumers": [0xB997, 0xB9B7, 0xB9BA,
                       0xBAA7, 0xBA2A, 0xBA2D, 0x1BCC]},
        {"start": 0x6116, "end": 0x612B,
         "format": "5 `(s16 debris dx,s16 debris dy)` late-boss destruction offsets plus single-word `$8000` terminal, used by `$B997/$BAA7`",
         "consumers": [0xB997, 0xB9DC, 0xB9DF,
                       0xBAA7, 0xBA40, 0xBA43]},
        {"start": 0x60A6, "end": 0x60AD,
         "format": "four-s16 boss/stage object collision extents `(-16,+16,-16,+16)` passed by `$B39D` to `$F7F1`",
         "consumers": [0xB397, 0xB39D, 0xB3A0, 0xB3A3, 0xF7F1]},
        {"start": 0x60AE, "end": 0x60E5,
         "format": "14 unreferenced `(s16 dx,s16 dy)` destruction/spawn offset pairs adjacent to `$60A6`; no World runtime instruction or ROM pointer reaches this alternate list",
         "consumers": []},
        {"start": 0x6244, "end": 0x625B,
         "format": "3 four-s16 late-boss child collision extents: `(-10,+10,-10,+10)`, `(-5,+5,-5,+5)`, `(-16,+16,-16,+16)`, selected by constructors and used through `$F6DA`",
         "consumers": [0xBB45, 0xBB77, 0xBB83, 0xBB8F, 0xBB9B,
                       0xBBA7, 0xBBB3, 0xBBD4, 0xBC0D, 0xBC36,
                       0xBC68, 0xC051, 0xC054, 0xC07B, 0xC07E,
                       0xF6DA]},
        {"start": 0x627C, "end": 0x629D,
         "format": "16-word cyclic late-boss child X-position command list plus zero terminal; `$8000` means skip this spawn slot, other words are native X, terminal resets pointer to `$627C`",
         "consumers": [0xB801, 0xB87F, 0xB884, 0xB88C,
                       0xBD32, 0xBD3C, 0xBD4E, 0xBD51, 0xBD54,
                       0xBD59, 0xBD6C, 0xBD6F, 0xBD72, 0xBD92,
                       0xBD96, 0xBD9A, 0xBD9E]},
        {"start": 0x842C, "end": 0x846B,
         "format": "32 unreferenced u16 sprite-code/phase values immediately preceding state `$8490`; `$8358` uses equal numeric `$842C` only as a CS handler, not an ES data pointer",
         "consumers": []},
        {"start": 0xB991, "end": 0xB992,
         "format": "unreferenced u16 `$0008` between 50-entry event dispatch and odd-aligned Stage 1 stream",
         "consumers": []},
        {"start": 0xC5E3, "end": 0xC626,
         "format": "16 x (u16 timer threshold, u16 spawn command) plus terminal threshold `$869F` record",
         "consumers": [0xB0EC, 0xB122, 0xB128, 0xB12D, 0xB18A]},
        {"start": 0x8724, "end": 0x8733,
         "format": "8 x u16 foreground HUD restore block",
         "consumers": [0xEA49]},
        {"start": 0x8734, "end": 0x8743,
         "format": "8 x u16 foreground HUD restore block",
         "consumers": [0xEA39]},
        {"start": 0x8744, "end": 0x8753,
         "format": "8 x u16 foreground HUD restore block",
         "consumers": [0xEA41]},
        {"start": 0x8754, "end": 0x8763,
         "format": "8 x u16 foreground HUD initialization block",
         "consumers": [0xE9D7]},
        {"start": 0x8764, "end": 0x877B,
         "format": "12 x u16 foreground HUD initialization block",
         "consumers": [0xE9E2]},
        {"start": 0x877C, "end": 0x87C1,
         "format": "4 ED93 text records: compact/expanded `FREE PLAY` and `CREDIT`",
         "consumers": [0xEBFB, 0xEC05, 0xEC1E, 0xEC28,
                       0xEDA1, 0xEDA3, 0xEDA6, 0xEDB1]},
        {"start": 0x87C2, "end": 0x87F9,
         "format": "4 x 14-byte attract/demo configuration record",
         "consumers": [0x0BD0, 0x0BE2, 0x0BEA, 0x0C03, 0x0C0B,
                       0x0C3A, 0x0C50]},
        {"start": 0x87FA, "end": 0x88E7,
         "format": "17 x 14-byte stage/checkpoint initialization record",
         "consumers": [0xF030, 0xF04C, 0xF054, 0xF06D, 0xF075,
                       0xF0A4, 0xF0C4, 0xF103, 0xF10B, 0xF113]},
        {"start": 0x88E8, "end": 0x8911,
         "format": "20 x u16 ending-text record pointer plus zero terminator",
         "consumers": [0xEF2F]},
        {"start": 0x8912, "end": 0x8B87,
         "format": "21 x ED93 text record (header 3xu16 + 1x24 glyphs)",
         "consumers": [0xEDA1, 0xEDA3, 0xEDA6, 0xEDB1]},
        {"start": 0x8B88, "end": 0x8BA9,
         "format": "ED93 text record (header 3xu16 + 1x28 glyphs)",
         "consumers": [0xEF64, 0xEDA1, 0xEDA3, 0xEDA6, 0xEDB1]},
        {"start": 0x8BAA, "end": 0x8BCD,
         "format": "ED93 text record (header 3xu16 + 1x30 glyphs)",
         "consumers": [0xF1AC, 0xEDA1, 0xEDA3, 0xEDA6, 0xEDB1]},
        {"start": 0x8BCE, "end": 0x8BDF,
         "format": "ED93 text record (header 3xu16 + 1x12 glyphs)",
         "consumers": [0xF1B5, 0xEDA1, 0xEDA3, 0xEDA6, 0xEDB1]},
        {"start": 0x8BE0, "end": 0x8C01,
         "format": "17 x u16 packed ASCII stage-number glyph pair",
         "consumers": [0xF1D4]},
        {"start": 0x8C02, "end": 0x8C1F,
         "format": "3 x 10-byte stage-variant sound command map",
         "consumers": [0xF39E, 0xF3B3, 0xF3F6, 0xF420]},
        {"start": 0x8C20, "end": 0x8C3F,
         "format": "16 x u16 stage resource-list pointer",
         "consumers": [0xF0B0]},
        {"start": 0x8C40, "end": 0x8C4F,
         "format": "8 unreferenced duplicate u16 resource-list roots `$8C50`; F0B0 masks index to 0..15",
         "consumers": []},
        {"start": 0x8C50, "end": 0x8DAF,
         "format": "11 x (15-u16 palette resource list + `$801F` sentinel)",
         "consumers": [0x5552]},
        {"start": 0x8DB0, "end": 0x8DCF,
         "format": "16 x u16 command-indexed spawn Y coordinate",
         "consumers": [0xF883]},
        {"start": 0x8DD0, "end": 0x8E0F,
         "format": "16 x (u16 spawn X, u16 spawn Y)",
         "consumers": [0xF896, 0xF89E]},
        {"start": 0x8E10, "end": 0x8F8F,
         "format": "64 x (u16 cadence, u16 phase limit, u16 16-vector-table pointer); indices 0..39 reachable by F8A7, 40..63 unused",
         "consumers": [0xF8D0, 0xF8D6, 0xF8DD]},
        {"start": 0x94CA, "end": 0x96D5,
         "format": "18 overlapping FB53 timelines of 8-byte (unused, vx, vy, descriptor, next-threshold) windows, `$8000` terminal threshold",
         "consumers": [0xFB25, 0xFB30, 0xFB3C, 0xFB59, 0xFB66,
                       0xFB6F, 0xFB78]},
        {"start": 0x96D6, "end": 0x96F3,
         "format": "5 x 6-byte FB53 sprite descriptor; codes `$20..$24`, two unused alternates",
         "consumers": [0xFB7F]},
        {"start": 0x96F4, "end": 0x989B,
         "format": "14 unreferenced alternate-ending ED93 text records",
         "consumers": []},
        {"start": 0x989C, "end": 0x9A5B,
         "format": "28 x 16-byte palette-only stage/presentation control record; indices `$10/$18/$19` unused",
         "consumers": [0x087B, 0x0B4B, 0x0B51, 0x0DC0, 0x1302,
                       0x1534, 0x1825, 0x182B, 0xFBB9, 0xFBBF, 0xFBC3]},
        {"start": 0x8F90, "end": 0x924F,
         "format": "11 x 64-byte table of 16 (s16 velocity X, s16 velocity Y); first 7 referenced, last 4 duplicate alternates unused",
         "consumers": [0x7CB7, 0x7CBF, 0xF8DD, 0xF63A, 0xF678, 0xF67B]},
        {"start": 0x9250, "end": 0x925F,
         "format": "4 x (u16 script pointer, u16 initial timer)",
         "consumers": [0xF901, 0xF909]},
        {"start": 0x9260, "end": 0x9273,
         "format": "2 x 5-u16 patrol formation command cycle (`3,3,3,3,3` / `3,0,1,2,0`)",
         "consumers": [0xF901, 0x5E27, 0x5E2F]},
        {"start": 0x9274, "end": 0x9293,
         "format": "16 x u16 command-selected object script pointer",
         "consumers": [0xF91D]},
        {"start": 0x9294, "end": 0x92AB,
         "format": "4 x (u16 cadence, u16 phase limit, u16 phase mask)",
         "consumers": [0xF942, 0xF94A, 0xF952]},
        {"start": 0x92AC, "end": 0x92EB,
         "format": "16 x (u16 F5C1 script root, u16 object flag/count)",
         "consumers": [0xF96E, 0xF966]},
        {"start": 0x92EC, "end": 0x930B,
         "format": "16 x u16 F5C1 script root",
         "consumers": [0xF990]},
        {"start": 0x930C, "end": 0x931B,
         "format": "8 x u16 spawn Y coordinate",
         "consumers": [0xF9A7]},
        {"start": 0x931C, "end": 0x9323,
         "format": "4 x u16 object field `$22` value",
         "consumers": [0xF9C0]},
        {"start": 0x9324, "end": 0x9383,
         "format": "16 x (u16 spawn X, u16 spawn Y, u16 object flag)",
         "consumers": [0xF9D7, 0xF9DF, 0xF9E7]},
        {"start": 0x93BC, "end": 0x93C3,
         "format": "4 x u16 object descriptor/state value",
         "consumers": [0xFA4C]},
        {"start": 0x93C4, "end": 0x93E3,
         "format": "8 x (u16 spawn Y, u16 object script/value)",
         "consumers": [0xFA5F, 0xFA6C]},
        {"start": 0x93DC, "end": 0x941B,
         "format": "16 x (u16 spawn X, u16 spawn Y)",
         "consumers": [0xFA7F, 0xFA87]},
        {"start": 0x941C, "end": 0x943B,
         "format": "16 x u16 spawn X coordinate",
         "consumers": [0xFACE]},
        {"start": 0x943C, "end": 0x945B,
         "format": "16 command-indexed u16 reload periods for final-stage spawner `$9660/$9674`: `$0140,$0130,$0110,$00F0,$00E0,$0090,$0060,$0040`, then eight `$0030`",
         "consumers": [0x9660, 0x967A, 0x967F, 0x9682,
                       0xFAAD, 0xFAB2, 0xFAB7, 0xFABD]},
        {"start": 0x86B4, "end": 0x86CB,
         "format": "5 x 4-byte packed-BCD score threshold plus `$FFFFFFFF` sentinel",
         "consumers": [0xE934, 0xE939]},
        {"start": 0x86CC, "end": 0x86E3,
         "format": "5 x 4-byte alternate packed-BCD score threshold plus `$FFFFFFFF` sentinel",
         "consumers": [0xE934, 0xE939]},
        {"start": 0x86E4, "end": 0x8723,
         "format": "16 x 4-byte packed-BCD score increment",
         "consumers": [0xE8ED, 0xE909]},
    ]

    # Последние короткие острова между уже доказанными sheets/tables. Каждый
    # имеет явный формат и фиксированную World-ROM сигнатуру; `consumers=[]`
    # означает доказанное отсутствие runtime/producer ссылки, а не пробел.
    residual_ranges = [
        (0x086A, 0x086F, "3 x u16 title/demo state-handler pointer `$3980,$3A00,$3A80`", [0x0BB2], (0x3980, 0x3A00, 0x3A80)),
        (0x1132, 0x1137, "unreferenced 6-byte launch-sheet sprite descriptor `$06B1`", [], (0x06B1, 0, 0)),
        (0x118C, 0x1191, "unreferenced 6-byte launch-sheet sprite descriptor `($F8D0,$0AFE,0)`", [], (0xF8D0, 0x0AFE, 0)),
        (0x119E, 0x11A3, "unreferenced 6-byte launch-sheet sprite descriptor `($F820,$00D1,0)`", [], (0xF820, 0x00D1, 0)),
        (0x1428, 0x142F, "unreferenced four-s16 Force collision extents `(-16,+16,-8,+8)`", [], (0xFFF0, 16, 0xFFF8, 8)),
        (0x1438, 0x143F, "unreferenced four-u16 Force collision radii `(16,16,16,16)`", [], (16, 16, 16, 16)),
        (0x159E, 0x15AD, "16-byte Force direction/phase selector map with `$FF` blocked entries", [0x29A8, 0x29E9], (0x0101, 0x01FF, 0x0101, 0x0101, 0xFFFF, 0xFFFF, 0x0101, 0x0101)),
        (0x17EE, 0x17F5, "four-u16 player/Force visual collision radii `(12,12,12,12)`", [], (12, 12, 12, 12)),
        (0x18B8, 0x18BD, "unreferenced zero-offset sprite descriptor `$001F` between Wave composites", [], (0, 0x001F, 0)),
        (0x18CA, 0x18CF, "unreferenced zero-offset sprite descriptor `$001F` between Wave composites", [], (0, 0x001F, 0)),
        (0x18DC, 0x18E1, "unreferenced zero-offset sprite descriptor `$001F` between Wave composites", [], (0, 0x001F, 0)),
        (0x18EE, 0x18F3, "unreferenced zero-offset sprite descriptor `$001F` between Wave composites", [], (0, 0x001F, 0)),
        (0x1900, 0x1905, "unreferenced Wave composite tail descriptor `($F818,$0014,0)`", [], (0xF818, 0x0014, 0)),
        (0x1912, 0x1917, "unreferenced Wave composite tail descriptor `($F818,$0015,0)`", [], (0xF818, 0x0015, 0)),
        (0x1924, 0x1929, "unreferenced Wave composite tail descriptor `($F828,$0059,0)`", [], (0xF828, 0x0059, 0)),
        (0x1936, 0x193B, "unreferenced Wave composite tail descriptor `($F828,$005B,0)`", [], (0xF828, 0x005B, 0)),
        (0x1948, 0x194D, "unreferenced Wave composite tail descriptor `($F838,$0016,0)`", [], (0xF838, 0x0016, 0)),
        (0x195A, 0x195F, "unreferenced Wave composite tail descriptor `($F838,$0017,0)`", [], (0xF838, 0x0017, 0)),
        (0x1984, 0x198F, "2 unreferenced six-byte player-weapon descriptors for sprite `$0B92`", [], (0xE000, 0x0B92, 0x5400, 0xE0E0, 0x0B92, 0x5C00)),
        (0x2000, 0x2005, "unreferenced projectile-cleanup descriptor `($F8F8,$07F9,0)`", [], (0xF8F8, 0x07F9, 0)),
        (0x2018, 0x201D, "unreferenced projectile-cleanup descriptor `($F8F8,$07F5,0)`", [], (0xF8F8, 0x07F5, 0)),
        (0x21CE, 0x21D3, "unreferenced grid-object descriptor `($F8F8,$09C4,$5000)`", [], (0xF8F8, 0x09C4, 0x5000)),
        (0x21D4, 0x21DB, "unreferenced four-u16 grid-object collision radii `(12,12,12,12)`", [], (12, 12, 12, 12)),
        (0x26DC, 0x26EB, "two four-u16 player-weapon collision radius records `(16,16,8,8)` / `(15,15,4,4)`", [], (16, 16, 8, 8, 15, 15, 4, 4)),
        (0x26F2, 0x26F7, "unreferenced player-weapon descriptor `($F808,$000E,0)`", [], (0xF808, 0x000E, 0)),
        (0x281E, 0x2825, "4 u16 pickup-type destination RAM offsets `$0033,$0036,$0035,0`", [0x58EF], (0x0033, 0x0036, 0x0035, 0)),
        (0x2826, 0x282B, "unreferenced carrier descriptor `($F0F0,$00E6,$5800)`", [], (0xF0F0, 0x00E6, 0x5800)),
        (0x28DA, 0x28E1, "unreferenced four-s16 carrier collision extents `(-7,+7,-7,+7)`", [], (0xFFF9, 7, 0xFFF9, 7)),
        (0x2970, 0x297B, "2 unreferenced carrier descriptors `$0104/$0106`", [], (0xF0F0, 0x0104, 0x5800, 0xF0F0, 0x0106, 0x5800)),
        (0x29CA, 0x29D1, "four-s16 `$5CEA/$5D2D` enemy collision extents `(-9,+9,-5,+5)` passed to `$F694`", [0x5D56, 0x5D59, 0xF694], (0xFFF7, 9, 0xFFFB, 5)),
        (0x2C40, 0x2C47, "unreferenced four-s16 mirrored-enemy collision extents `(-16,+16,-24,+24)`", [], (0xFFF0, 16, 0xFFE8, 24)),
        (0x2C5A, 0x2C5F, "unreferenced mirrored-enemy descriptor `($E800,$0374,$6000)`", [], (0xE800, 0x0374, 0x6000)),
        (0x2C72, 0x2C77, "unreferenced mirrored-enemy descriptor `($E800,$0370,$6800)`", [], (0xE800, 0x0370, 0x6800)),
        (0x2F06, 0x2F0D, "four-s16 Stage-1 child-projectile collision extents `(-2,+2,-2,+2)`", [], (0xFFFE, 2, 0xFFFE, 2)),
        (0x3276, 0x327D, "four-s16 moving-enemy collision extents `(-8,+8,-8,+8)`", [], (0xFFF8, 8, 0xFFF8, 8)),
        (0x333E, 0x3345, "four-s16 animated enemy collision extents `(-16,+16,-16,+16)`", [], (0xFFF0, 16, 0xFFF0, 16)),
        (0x3346, 0x334D, "4 u16 difficulty thresholds `(192,160,112,64)`", [], (192, 160, 112, 64)),
        (0x34A6, 0x34AD, "four-s16 runtime-enemy collision extents `(-4,+4,-4,+4)`", [], (0xFFFC, 4, 0xFFFC, 4)),
        (0x34AE, 0x34B5, "4 u16 runtime-enemy difficulty values `$4400,$4300,$4200,$4100`", [], (0x4400, 0x4300, 0x4200, 0x4100)),
        (0x3896, 0x38A1, "2 unreferenced six-byte tracking-enemy descriptors `$01D0/$01D4`", [], (0xD8F0, 0x01D0, 0x6000, 0xD810, 0x01D4, 0x6000)),
        (0x38C6, 0x38D1, "2 unreferenced six-byte tracking-enemy descriptors `$01D4/$01D0`", [], (0xD8D0, 0x01D4, 0x6800, 0xD8F0, 0x01D0, 0x6800)),
        (0x3A2E, 0x3A35, "four-s16 `$8561/$85B0` composite-shooter collision extents `(-16,+16,-16,+16)` passed to `$F6DA`", [0x85FD, 0x8600, 0xF6DA], (0xFFF0, 16, 0xFFF0, 16)),
        (0x3F6E, 0x3F75, "four-s16 stage-control collision extents `(-10,+10,-10,+10)`", [], (0xFFF6, 10, 0xFFF6, 10)),
        (0x436C, 0x4373, "four-s16 `$96E9` aimed-child collision extents `(-9,+9,-9,+9)` passed to `$F694`", [0x9706, 0x9709, 0xF694], (0xFFF7, 9, 0xFFF7, 9)),
        (0x44AC, 0x44B1, "unreferenced boss-controller descriptor `($F0F0,$03A0,$5000)`", [], (0xF0F0, 0x03A0, 0x5000)),
        (0x44B2, 0x44B9, "four-s16 boss-controller collision extents `(-8,+8,-8,+8)`", [], (0xFFF8, 8, 0xFFF8, 8)),
        (0x44D8, 0x44DD, "unreferenced boss-controller descriptor `($F0F0,$03A2,$5000)`", [], (0xF0F0, 0x03A2, 0x5000)),
        (0x5A0E, 0x5A13, "unreferenced boss composite descriptor `($0038,$0A10,$6000)`", [], (0x0038, 0x0A10, 0x6000)),
        (0x5A52, 0x5A57, "unreferenced boss composite descriptor `($D008,$0A50,$6000)`", [], (0xD008, 0x0A50, 0x6000)),
        (0x5A8E, 0x5A93, "unreferenced boss composite descriptor `($F8E8,$0A34,$6000)`", [], (0xF8E8, 0x0A34, 0x6000)),
        (0x617E, 0x6183, "unreferenced late-boss descriptor `($F0F0,$0BE6,$5400)`", [], (0xF0F0, 0x0BE6, 0x5400)),
        (0x618A, 0x618F, "unreferenced late-boss descriptor `($F0F0,$0254,$5800)`", [], (0xF0F0, 0x0254, 0x5800)),
        (0x6196, 0x619B, "unreferenced late-boss descriptor `($F0F0,$0256,$5800)`", [], (0xF0F0, 0x0256, 0x5800)),
        (0x61A2, 0x61A7, "unreferenced late-boss descriptor `($F0F0,$02F0,$5400)`", [], (0xF0F0, 0x02F0, 0x5400)),
        (0x61AE, 0x61B3, "unreferenced late-boss descriptor `($F80C,$0AFB,$0C00)`", [], (0xF80C, 0x0AFB, 0x0C00)),
        (0x630A, 0x6311, "four-s16 late-boss body collision extents `(-6,+6,-22,+6)`", [], (0xFFFA, 6, 0xFFEA, 6)),
        (0x797C, 0x7981, "unreferenced multipart descriptor `($F010,$0830,$5000)`", [], (0xF010, 0x0830, 0x5000)),
        (0x7A84, 0x7A93, "two four-s16 paired-body collision records `(-16,+16,-14,+16)`", [], (0xFFF0, 16, 0xFFF2, 16, 0xFFF0, 16, 0xFFF2, 16)),
        (0x7B34, 0x7B39, "unreferenced late-stage descriptor `($F0F0,$0852,$5000)`", [], (0xF0F0, 0x0852, 0x5000)),
        (0x7B46, 0x7B4D, "four-s16 late-stage enemy collision extents `(-68,+68,-14,+14)`", [], (0xFFBC, 68, 0xFFF2, 14)),
        (0x7D38, 0x7D3D, "unreferenced late-stage child descriptor `($F0F0,$0890,$5400)`", [], (0xF0F0, 0x0890, 0x5400)),
        (0x7D44, 0x7D49, "unreferenced late-stage child descriptor `($F0F0,$0886,$5400)`", [], (0xF0F0, 0x0886, 0x5400)),
        (0x7D50, 0x7D55, "unreferenced late-stage child descriptor `($F1F0,$0884,$5400)`", [], (0xF1F0, 0x0884, 0x5400)),
        (0x7D5C, 0x7D61, "unreferenced late-stage child descriptor `($F1F0,$0882,$5400)`", [], (0xF1F0, 0x0882, 0x5400)),
        (0x7D68, 0x7D6D, "unreferenced late-stage child descriptor `($F8F0,$06E3,$4000)`", [], (0xF8F0, 0x06E3, 0x4000)),
        (0x7D74, 0x7D79, "unreferenced late-stage child descriptor `($EFF0,$0882,$5000)`", [], (0xEFF0, 0x0882, 0x5000)),
        (0x7D80, 0x7D85, "unreferenced late-stage child descriptor `($EFF0,$0884,$5000)`", [], (0xEFF0, 0x0884, 0x5000)),
        (0x7D8C, 0x7D91, "unreferenced late-stage child descriptor `($F0F0,$0886,$5000)`", [], (0xF0F0, 0x0886, 0x5000)),
        (0x7D98, 0x7D9D, "unreferenced late-stage child descriptor `($F0F0,$0890,$5000)`", [], (0xF0F0, 0x0890, 0x5000)),
        (0x7DA4, 0x7DA9, "unreferenced late-stage child descriptor `($F0F0,$0886,$5800)`", [], (0xF0F0, 0x0886, 0x5800)),
        (0x7DB0, 0x7DB5, "unreferenced late-stage child descriptor `($F0F0,$0886,$5C00)`", [], (0xF0F0, 0x0886, 0x5C00)),
        (0x7ECA, 0x7ED1, "four-s16 late-stage enemy collision extents `(-8,+8,-8,+8)`", [], (0xFFF8, 8, 0xFFF8, 8)),
        (0x7FFE, 0x8005, "four-s16 moving-emitter child collision extents `(-8,+8,-8,+8)`", [], (0xFFF8, 8, 0xFFF8, 8)),
        (0x81CA, 0x81D9, "two four-s16 late-stage collision records `(-12,+12,-12,+12)` / `(-32,+12,-12,+12)`", [], (0xFFF4, 12, 0xFFF4, 12, 0xFFE0, 12, 0xFFF4, 12)),
        (0x81F2, 0x81F9, "four-s16 late-stage child collision extents `(-4,+4,-4,+4)`", [], (0xFFFC, 4, 0xFFFC, 4)),
        (0x8250, 0x8257, "four-s16 late-stage enemy collision extents `(-12,+12,-12,+4)`", [], (0xFFF4, 12, 0xFFF4, 4)),
        (0x84C6, 0x84CD, "four-s16 late-stage projectile collision extents `(-2,+2,-2,+2)`", [], (0xFFFE, 2, 0xFFFE, 2)),
        (0x84FE, 0x8505, "four-s16 `$E6AB/$E6C0` projectile/player collision extents `(-16,+16,-4,+4)` passed to `$F485`", [0xE6DD, 0xE6E0, 0xF485], (0xFFF0, 16, 0xFFFC, 4)),
    ]
    for start, end, fmt, consumers, signature in residual_ranges:
        proven_runtime_ranges.append({"start": start, "end": end,
                                      "format": fmt,
                                      "consumers": consumers})
        if _es_words(main, start, len(signature)) != signature:
            errors.append(f"residual semantic range ES:${start:04X} изменён")

    title_bootstrap_roots = tuple(range(0x08C4, 0x090A, 10))
    title_motion_roots = tuple(_es_words(main, root, 1)[0]
                               for root in title_bootstrap_roots)
    title_motion_terminals = tuple(_es_words(main, root + 8, 1)[0]
                                   for root in title_bootstrap_roots)
    if (title_motion_roots !=
            (0x09E2, 0x090A, 0x092E, 0x0952, 0x0976, 0x099A, 0x09BE) or
            title_motion_terminals !=
            (0x09FA, 0x0928, 0x094C, 0x0970, 0x0994, 0x09B8, 0x09DC)):
        errors.append("title motion roots/terminals ES:$08C4 изменены")
    title_motion_bytes: set[int] = set()
    for root, terminal in zip(title_motion_roots, title_motion_terminals):
        if ((terminal - root) % 6 or
                _es_words(main, terminal, 1) != (0x8000,)):
            errors.append(f"title motion ES:${root:04X} имеет неверный terminal")
        title_motion_bytes.update(range(root, terminal + 6))
    if title_motion_bytes != set(range(0x090A, 0x0A00)):
        errors.append("title motion streams не покрывают ES:$090A..$09FF")

    title_text_roots = (0x0A00, 0x0A1E, 0x0A3C, 0x0A42,
                        0x0A48, 0x0A5A, 0x0A6A)
    title_text_lengths = (24, 24, 22, 22, 12, 10, 24)
    title_inline_roots = {0x0A00, 0x0A1E, 0x0A48, 0x0A5A, 0x0A6A}
    title_text_next = {0x0A00: 0x0A1E, 0x0A1E: 0x0A3C,
                       0x0A48: 0x0A5A, 0x0A5A: 0x0A6A,
                       0x0A6A: 0x0A88}
    for index, (root, length) in enumerate(zip(title_text_roots,
                                               title_text_lengths)):
        if _es_words(main, root + 4, 1) != (length,):
            errors.append(f"title text header ES:${root:04X} изменён")
        if root in title_inline_roots:
            expected = title_text_next[root]
            if root + 6 + length != expected:
                errors.append(f"title inline text ES:${root:04X} оборван")
    ed58_title_roots = (0x0A88, 0x0AA6, 0x0AD0, 0x0AEE, 0x0B10)
    ed58_title_dimensions = (0x0118, 0x0118, 0x0118, 0x020E, 0x0214)
    ed58_title_ends = (0x0AA6, 0x0AC4, 0x0AEE, 0x0B10, 0x0B3E)
    for root, dimensions, expected in zip(ed58_title_roots,
                                          ed58_title_dimensions,
                                          ed58_title_ends):
        if (_es_words(main, root + 2, 1) != (dimensions,) or
                root + 6 + (dimensions & 0xFF) * (dimensions >> 8) != expected):
            errors.append(f"ED58 title text ES:${root:04X} оборван")
    if (_es_words(main, 0x0AC4, 3) != (0x0006, 0x0116, 0x177C) or
            _es_words(main, 0x0ACA, 3) != (0x0006, 0x0116, 0x187C)):
        errors.append("ED3A title dynamic headers ES:$0AC4 изменены")

    if (_es_words(main, 0x0B56, 3) != (0xF818, 0x00D4, 0) or
            es[0x0B5C:0x0B7E] != b"ABCDEFGHIJKLMNOPQRSTUVWXYZ!?>.,-<:"):
        errors.append("initials alphabet/descriptor ES:$0B56 изменён")
    force_radius_roots = _es_words(main, 0x15BE, 4)
    force_radius_records = tuple(_es_words(main, root, 4)
                                 for root in (0x15C6, 0x15CE, 0x15D6))
    if (force_radius_roots != (0x15C6, 0x15C6, 0x15CE, 0x15D6) or
            force_radius_records !=
            ((4, 4, 4, 4), (7, 7, 7, 7), (12, 12, 12, 12))):
        errors.append("Force collision radius tables ES:$15BE изменены")
    force_descriptor_lattice_roots = _es_words(main, 0x1488, 9)
    force_descriptor_lattice_bytes = set()
    for root in force_descriptor_lattice_roots:
        force_descriptor_lattice_bytes.update(range(root, root + 8))
    if (force_descriptor_lattice_roots !=
            (0x14BA, 0x14CA, 0x14AA, 0x14D2, 0x14C2,
             0x14E2, 0x14B2, 0x14DA, 0x14BA) or
            force_descriptor_lattice_bytes != set(range(0x14AA, 0x14EA)) or
            any(not 0x1532 <= value <= 0x1598
                for value in _es_words(main, 0x14AA, 32))):
        errors.append("Force descriptor lattice ES:$14AA изменена")
    bit_target_records = tuple(_es_words(main, address, 2)
                               for address in range(0x15DE, 0x16DE, 4))
    if (len(bit_target_records) != 4 * 16 or
            any(not -0x40 <= ((value + 0x8000) & 0xFFFF) - 0x8000 <= 0x40
                for record in bit_target_records for value in record)):
        errors.append("Bit target-offset matrix ES:$15DE изменена")
    bit_pursuit_1 = _es_words(main, 0x16DE, 32)
    bit_pursuit_2 = _es_words(main, 0x171E, 32)
    if (bit_pursuit_1 != bit_pursuit_2 or
            bit_pursuit_1[0] != 0x0400 or
            bit_pursuit_1[-1] != 0x0F00 or
            any(value & 0xFF for value in bit_pursuit_1)):
        errors.append("Bit pursuit tables ES:$16DE/$171E изменены")
    unused_wave_radius = tuple(_es_words(main, address, 4)
                               for address in range(0x180E, 0x183E, 8))
    if (unused_wave_radius !=
            tuple((4, 5, height, height)
                  for height in (8, 16, 32, 64, 96, 128))):
        errors.append("unused Wave radius records ES:$180E изменены")
    wave_probe_counts = _es_words(main, 0x183E, 12)
    wave_radius = tuple(_es_words(main, address, 4)
                        for address in range(0x1856, 0x187E, 8))
    if (wave_probe_counts != (5, 5, 6, 6, 7, 8, 9, 10, 11, 12, 12, 12) or
            wave_radius != ((2, 16, 8, 8), (12, 22, 8, 8),
                            (12, 28, 8, 8), (12, 20, 8, 8),
                            (12, 30, 8, 8)) or
            _es_words(main, 0x187E, 7) != (1,) * 7):
        errors.append("Wave terrain/radius tables ES:$183E изменены")
    if (_es_words(main, 0x0B7E, 8) !=
            tuple(range(0x2B78, 0x2BB8, 8)) or
            _es_words(main, 0x0B8E, 10) != tuple(range(10, 101, 10)) or
            _es_words(main, 0x0BA2, 10) !=
            tuple(range(0x186C, 0x2C6C, 0x200))):
        errors.append("ranking address/delay tables ES:$0B7E изменены")
    ranking_tile_roots = tuple(range(0x0BCA, 0x0CBA, 0x18))
    if (_es_words(main, 0x0BB6, 10) != ranking_tile_roots or
            len(ranking_tile_roots) != 10):
        errors.append("ranking tile roots ES:$0BB6 изменены")
    inline_text_roots = [0x0CBA, 0x0CCE, 0x0CE0, 0x0CFA]
    inline_text_lengths = [14, 12, 20, 30]
    for index, (root, length) in enumerate(zip(inline_text_roots,
                                                inline_text_lengths)):
        expected = (inline_text_roots[index + 1]
                    if index + 1 < len(inline_text_roots) else 0x0D1E)
        if (_es_words(main, root + 4, 1) != (length,) or
                root + 6 + length != expected):
            errors.append(f"inline ranking text ES:${root:04X} оборван")
    if (es[0x0D1E:0x0D34] != b"0 1 2 3 4 5 6 7 8 9 10" or
            any(len(es[root:root + 8]) != 8 or
                b"STAGE" not in es[root:root + 8]
                for root in range(0x0D34, 0x0DB4, 8)) or
            es[0x0DB4:0x0DBC] != b"TOTAL SC"):
        errors.append("ranking rank/stage labels ES:$0D1E изменены")
    if (_es_words(main, 0x0DBC, 8) != tuple(range(0x1730, 0x2730, 0x200)) or
            _es_words(main, 0x0DCC, 9) != tuple(range(0x1788, 0x2988, 0x200))):
        errors.append("ranking foreground destinations ES:$0DBC изменены")
    countdown_records = [
        _es_words(main, address, 2)
        for address in range(0x0DDE, 0x0E06, 4)
    ]
    countdown_roots = tuple(range(0x0E6A, 0x10C2, 0x3C))
    if ([record[0] for record in countdown_records] != list(countdown_roots) or
            [record[1] for record in countdown_records] !=
            list(range(0x79, 0x6F, -1))):
        errors.append("countdown text/sound records ES:$0DDE изменены")
    prompt_roots = [0x0E06, 0x0E1C, 0x0E38]
    prompt_ends = [0x0E1C, 0x0E38, 0x0E6A]
    for root, expected in zip(prompt_roots, prompt_ends):
        dimensions = _es_words(main, root + 2, 1)[0]
        if root + 6 + (dimensions & 0xFF) * (dimensions >> 8) != expected:
            errors.append(f"prompt ED93 text ES:${root:04X} оборван")
    if (len(countdown_roots) != 10 or
            any(_es_words(main, root + 2, 1) != (0x0906,)
                for root in countdown_roots) or
            countdown_roots[-1] + 0x3C != 0x10C2):
        errors.append("10 countdown ED93 glyphs ES:$0E6A изменены")

    r9_velocity_roots = tuple(range(0x11BA, 0x12FA, 0x40))
    if (_es_words(main, 0x11B0, 5) != r9_velocity_roots or
            len(r9_velocity_roots) != 5 or
            any(len(es[root:root + 0x40]) != 16 * 4
                for root in r9_velocity_roots)):
        errors.append("R-9 speed/direction matrices ES:$11B0 изменены")
    for root, limit in zip(r9_velocity_roots,
                           (0x200, 0x300, 0x400, 0x600, 0x800)):
        velocities = tuple(_es_words(main, address, 2)
                           for address in range(root, root + 0x40, 4))
        signed = tuple(tuple(((value + 0x8000) & 0xFFFF) - 0x8000
                             for value in record)
                       for record in velocities)
        # Низкие четыре бита input: right,left,up,down. Противоречивые
        # и неиспользуемые комбинации таблица намеренно гасит в (0,0).
        zero_indices = (0, 3, 7, 11, 12, 13, 14, 15)
        if (signed[1] != (limit, 0) or signed[2] != (-limit, 0) or
                signed[4][0] != 0 or signed[4][1] >= 0 or
                signed[8][0] != 0 or signed[8][1] <= 0 or
                signed[5][0] <= 0 or signed[5][1] >= 0 or
                signed[6][0] >= 0 or signed[6][1] >= 0 or
                signed[9][0] <= 0 or signed[9][1] <= 0 or
                signed[10][0] >= 0 or signed[10][1] <= 0 or
                any(signed[index] != (0, 0) for index in zero_indices) or
                any(abs(value) > limit for record in signed for value in record)):
            errors.append(f"R-9 velocity tier ES:${root:04X} изменён")

    if (any(_es_words(main, address, 3) != (0, 0x001F, 0)
            for address in range(0x2716, 0x272E, 6)) or
            _es_words(main, 0x272E, 19) !=
            (0x06AE, 0x06B3, 0x06B4, 0x06B5,
             0x06B6, 0x06B7, 0x06B8, 0x06B9,
             0x06BA,
             0x06AD, 0x06AF, 0x06B0, 0x06B1, 0x06B2,
             0x06BF, 0x06BB, 0x06BC, 0x06BD, 0x06BE)):
        errors.append("Beam meter tile records ES:$2716/$272E изменены")
    palette_event_records = tuple(_es_words(main, address, 2)
                                  for address in range(0x2754, 0x2784, 4))
    if (palette_event_records !=
            ((7, 0x17), (7, 0), (0x0D, 0), (9, 0),
             (0x0A, 0), (0x0B, 0), (0x0C, 0), (0x0D, 0),
             (0x0E, 0), (0x0F, 0x0F), (0x0F, 0x0F), (0x0F, 0x0F)) or
            _es_words(main, 0x2784, 4) != (0xFFF0, 0x000E,
                                           0xFFF2, 0x000E)):
        errors.append("palette/pickup records ES:$2754/$2784 изменены")

    stage1_child_direction_ring = tuple(_es_words(main, address, 2)
                                        for address in range(0x2FDC,
                                                             0x301C, 4))
    if (_es_words(main, 0x2FD4, 4) !=
            (0xFFF8, 0x0008, 0xFFF8, 0x0008) or
            stage1_child_direction_ring !=
            ((0, 0xFFF2),
             (0xFFF8, 0xFFF8), (0xFFF8, 0xFFF8), (0xFFF8, 0xFFF8),
             (0xFFF8, 0),
             (0xFFF8, 8), (0xFFF8, 8), (0xFFF8, 8),
             (0, 8),
             (8, 8), (8, 8), (8, 8),
             (8, 0),
             (8, 0xFFF8), (8, 0xFFF8), (8, 0xFFF8))):
        errors.append("Stage-1 child hitbox/ring ES:$2FD4 изменены")
    enemy_2d90_probes = tuple(_es_words(main, address, 2)
                              for address in range(0x2D90, 0x2DD0, 4))
    if (_es_words(main, 0x2D84, 4) !=
            (0xFFFC, 4, 0xFFFC, 4) or
            tuple(es[0x2D8C:0x2D90]) != (3, 5, 8, 14) or
            len(enemy_2d90_probes) != 16 or
            any(enemy_2d90_probes[index + 8] !=
                tuple((-value) & 0xFFFF
                      for value in enemy_2d90_probes[index])
                for index in range(8))):
        errors.append("direction enemy records ES:$2D84 изменены")
    composite_child_offsets = tuple(_es_words(main, address, 2)
                                    for address in range(0x2D14,
                                                         0x2D54, 4))
    if (len(composite_child_offsets) != 16 or
            any(composite_child_offsets[index + 8] !=
                tuple((-value) & 0xFFFF
                      for value in composite_child_offsets[index])
                for index in range(8)) or
            composite_child_offsets[0] != (0, 0xFFF4) or
            composite_child_offsets[8] != (0, 12)):
        errors.append("composite child offsets ES:$2D14 изменены")
    if (_es_words(main, 0x2C7E, 3) !=
            (0xF8F8, 0x017D, 0x0800) or
            _es_words(main, 0x2C84, 4) !=
            (0xFFFA, 6, 0xFFFA, 6) or
            _es_words(main, 0x2C8C, 4) !=
            (0x8F90, 0x8FD0, 0x9010, 0x9050) or
            tuple(_es_words(main, address, 4)
                  for address in range(0x2C94, 0x2CB4, 8)) !=
            ((0xFE00, 0, 12, 4), (0xFE00, 0x0100, 13, 3),
             (0xFF40, 0x01C0, 15, 1), (0x00C0, 0x01C0, 1, 15))):
        errors.append("spawned directional enemy ES:$2C7E изменён")
    if (tuple(_es_words(main, address, 4)
              for address in range(0x2B20, 0x2B40, 8)) !=
            ((0xFFDC, 28, 0xFFE8, 24),
             (0xFFE4, 36, 0xFFE8, 24),
             (28, 40, 0xFFF2, 14),
             (0xFFD8, 0xFFE4, 0xFFF2, 14)) or
            _es_words(main, 0x2B40, 4) != (38, 16, 12, 8) or
            _es_words(main, 0x2B48, 4) != (640, 1536, 1792, 2048) or
            _es_words(main, 0x2B50, 4) != (896, 1536, 1792, 2048) or
            _es_words(main, 0x2B58, 4) != (16, 8, 4, 2)):
        errors.append("multiphase enemy records ES:$2B20 изменены")
    if (_es_words(main, 0x301C, 19) !=
            (20, 8, 0xFFE0, 10, 0xFFD9, 0xFFF8,
             52, 2, 26, 0xFFF3, 9, 12, 0, 0xFFFC,
             0xFFF2, 0xFFFC, 52, 32, 0x8000)):
        errors.append("Stage-1 debris offsets ES:$301C изменены")

    dormant_419e_descriptors = tuple(_es_words(main, address, 3)
                                     for address in range(0x419E,
                                                          0x41FE, 6))
    if (_es_words(main, 0x4196, 4) !=
            (0xFFFC, 4, 0xFFFC, 4) or
            dormant_419e_descriptors !=
            ((0xF0F0, 0x09B0, 0x5800),
             (0xF0F0, 0x09A6, 0x5C00),
             (0xF0F0, 0x09A4, 0x5C00),
             (0xF0F0, 0x09A2, 0x5C00),
             (0xF0F0, 0x09A0, 0x5C00),
             (0xF0F0, 0x09A2, 0x5400),
             (0xF0F0, 0x09A4, 0x5400),
             (0xF0F0, 0x09A6, 0x5400),
             (0xF0F0, 0x09B0, 0x5000),
             (0xF0F0, 0x09A6, 0x5000),
             (0xF0F0, 0x09A4, 0x5000),
             (0xF0F0, 0x09A2, 0x5000),
             (0xF0F0, 0x09A0, 0x5800),
             (0xF0F0, 0x09A2, 0x5800),
             (0xF0F0, 0x09A4, 0x5800),
             (0xF0F0, 0x09A6, 0x5800))):
        errors.append("mobile enemy records ES:$4196/$419E изменены")
    if (tuple(_es_words(main, address, 3)
              for address in range(0x425E, 0x427C, 6)) !=
            ((0xF0F0, 0x0990, 0x5000),
             (0xF0F0, 0x0992, 0x5000),
             (0xF0F0, 0x0994, 0x5000),
             (0xF0F0, 0x0992, 0x5000),
             (0xF0F0, 0x0996, 0x5000)) or
            _es_words(main, 0x427C, 4) !=
            (0xFFF8, 8, 0xFFF8, 8) or
            _es_words(main, 0x4284, 4) !=
            (0x9010, 0x9050, 0x9090, 0x90D0)):
        errors.append("enemy records ES:$425E изменены")

    multipart_child_records = tuple(_es_words(main, address, 3)
                                    for address in range(0x4086,
                                                         0x40B6, 6))
    if (_es_words(main, 0x407E, 4) !=
            (0xFFF4, 12, 0xFFF4, 12) or
            len(multipart_child_records) != 8 or
            tuple(record[0] for record in multipart_child_records) !=
            (0xA4E6, 0xA530, 0xA56E, 0xA626,
             0xA652, 0xA7DE, 0xA7DE, 0xA7DE) or
            _es_words(main, 0x40B6, 8) !=
            (0x50, 0x50, 0x50, 0x50, 0x20, 0x20, 0x20, 0x20)):
        errors.append("multipart child records ES:$407E изменены")
    cardinal_speed_tiers = tuple(_es_words(main, address, 8)
                                 for address in range(0x3F86, 0x3FC6, 16))
    if cardinal_speed_tiers != tuple(
            (magnitude, 0, (-magnitude) & 0xFFFF, 0,
             0, magnitude, 0, (-magnitude) & 0xFFFF)
            for magnitude in (0x100, 0x180, 0x200, 0x300)):
        errors.append("cardinal speed tiers ES:$3F86 изменены")

    boss_child_motion = tuple(
        tuple(int.from_bytes(es[address + offset:address + offset + 2],
                             "little", signed=True)
              for offset in (0, 2))
        for address in range(0x4460, 0x44A0, 4))
    if (boss_child_motion !=
            ((0, 448), (0, 448), (0, 448), (0, 448), (0, 448),
             (0, -448), (0, -448), (0, -448), (0, -448),
             (-256, -384), (-384, -256), (-448, -128), (-512, 0),
             (-448, 128), (-384, 256), (-256, 384)) or
            _es_words(main, 0x44A0, 3) != (0xF0F0, 0x02F6, 0x5000)):
        errors.append("boss child motion/descriptor ES:$4460 изменены")
    terrain_enemy_debris_descriptors = tuple(
        _es_words(main, address, 3) for address in range(0x342E, 0x346A, 6))
    if (_es_words(main, 0x3426, 4) !=
            (0xFFF4, 12, 0xFFF4, 12) or
            terrain_enemy_debris_descriptors !=
            ((0xF8F8, 0x05F8, 0), (0xF8F8, 0x05F8, 0x0800),
             (0xF8F8, 0x05F9, 0), (0xF8F8, 0x05F9, 0x0800),
             (0xF8F8, 0x05FA, 0), (0xF8F8, 0x05FA, 0x0800),
             (0xF8F8, 0x05FB, 0), (0xF8F8, 0x05FB, 0x0800),
             (0xF8F8, 0x05FC, 0), (0xF8F8, 0x05FC, 0x0800))):
        errors.append("terrain enemy debris sheet ES:$3426 изменён")
    runtime_7891_descriptors = tuple(
        _es_words(main, address, 3) for address in range(0x346A, 0x34A6, 6))
    if runtime_7891_descriptors != tuple(
            (0xF8F8, code, facing)
            for code in (0x05F8, 0x05F9, 0x05FA, 0x05FB, 0x05FC)
            for facing in (0x0400, 0x0C00)):
        errors.append("runtime enemy sheet ES:$346A изменён")
    moving_enemy_sheet_roots = _es_words(main, 0x32BE, 4)
    if (_es_words(main, 0x3296, 4) !=
            (0xFFFE, 2, 0xFFFE, 2) or
            _es_words(main, 0x329E, 8) !=
            (0xFF00, 0, 0x0100, 0, 0, 0x00E0, 0, 0xFF20) or
            _es_words(main, 0x32AE, 8) !=
            (0xFFE0, 0, 0x0020, 0, 0, 0x0020, 0, 0xFFE0) or
            moving_enemy_sheet_roots !=
            (0x32C6, 0x32E4, 0x3320, 0x3302) or
            any(len(tuple(_es_words(main, root + phase * 6, 3)
                          for phase in range(5))) != 5
                for root in moving_enemy_sheet_roots) or
            set(range(0x32E4, 0x3320)) !=
            set().union(*(set(range(root, root + 30))
                          for root in (0x32E4, 0x3302)))):
        errors.append("moving enemy descriptor sheets ES:$32BE изменены")
    if (_es_words(main, 0x60A6, 4) !=
            (0xFFF0, 16, 0xFFF0, 16) or
            len(tuple(_es_words(main, address, 2)
                      for address in range(0x60AE, 0x60E6, 4))) != 14 or
            _es_words(main, 0x842C, 32) !=
            (0x0094, 0x009C, 0x00A4, 0x00AC,
             0x00B4, 0x00BC, 0x00C4, 0x00CC,
             0x00D4, 0x00DC, 0x00E4, 0x00EC,
             0x00F4, 0x00FC, 0x0164, 0x017C,
             0x0124, 0x012C, 0x0114, 0x011C,
             0x0134, 0x013C, 0x0144, 0x0144,
             0x0154, 0x0154, 0x0164, 0x0164,
             0x0174, 0x0174, 0x012C, 0x0124)):
        errors.append("boss/dormant records ES:$60A6/$842C изменены")
    if (_es_words(main, 0x31EE, 4) !=
            (0xFFEE, 18, 0xFFEE, 18) or
            _es_words(main, 0x31F6, 4) != (16, 8, 4, 2) or
            tuple(es[0x31FE:0x320E]) !=
            (8, 8, 8, 12, 12, 12, 12, 12,
             12, 0, 0, 0, 4, 4, 4, 4) or
            _es_words(main, 0x320E, 4) !=
            (0x8F90, 0x8FD0, 0x9010, 0x9050) or
            _es_words(main, 0x4526, 4) !=
            (0xFFF6, 10, 0xFFF6, 10) or
            _es_words(main, 0x454C, 1) != (0x8000,)):
        errors.append("late object/Dobkeratops records ES:$31EE/$4526 изменены")
    if (_es_words(main, 0x39AC, 4) !=
            (0xFFF4, 12, 0xFFF4, 12) or
            tuple(_es_words(main, address, 2)
                  for address in range(0x39B4, 0x39C4, 4)) !=
            ((0xFD40, 54), (0xFC40, 32),
             (0xFA40, 24), (0xF840, 16)) or
            _es_words(main, 0x39C4, 5) !=
            (0, 0xFFF0, 8, 16, 0xFFF8) or
            _es_words(main, 0x629C, 1) != (0,) or
            len(_es_words(main, 0x627C, 16)) != 16):
        errors.append("spawner/cyclic command records ES:$39AC/$627C изменены")
    if (_es_words(main, 0x1A08, 16) !=
            (0xFFF0, 32, 32, 128,
             0xFFF0, 32, 128, 32,
             0xFFF0, 32, 128, 128,
             6, 6, 6, 6) or
            _es_words(main, 0x265C, 16) !=
            (112, 0xFFE0, 32, 32, 0xFFE0, 112, 32, 32,
             32, 32, 16, 16, 32, 32, 16, 16)):
        errors.append("player weapon collision records ES:$1A08/$265C изменены")
    if (_es_words(main, 0x37C6, 4) !=
            (0xFFF0, 16, 0xFFF0, 16) or
            tuple(_es_words(main, address, 4)
                  for address in range(0x37CE, 0x37DE, 8)) !=
            ((0xFFF6, 10, 0xFFF6, 10),) * 2 or
            _es_words(main, 0x37DE, 4) != (0x0170, 0, 0x00A0, 1) or
            _es_words(main, 0x3846, 8) !=
            (0xFFE8, 24, 0xFFF0, 32, 0xFFE8, 24, 0xFFE0, 16) or
            _es_words(main, 0x3856, 4) != (32, 24, 16, 8) or
            _es_words(main, 0x385E, 4) !=
            (0xFC00, 0xFB00, 0xF900, 0xF700)):
        errors.append("multipart/tracking records ES:$37C6/$3846 изменены")
    if (_es_words(main, 0x3C12, 4) !=
            (0xFFF8, 8, 0xFFF8, 8) or
            _es_words(main, 0x3C1A, 4) != (127, 31, 15, 7) or
            _es_words(main, 0x3C22, 8) !=
            (0x3C32, 0x3C38, 0x3C32, 0x3C3E,
             0x3C44, 0x3C4A, 0x3C44, 0x3C50)):
        errors.append("animated child records ES:$3C12 изменены")
    direction_pair_roots = _es_words(main, 0x3FC6, 16)
    if ({value for value in direction_pair_roots if value} !=
            set(range(0x3FE6, 0x4006, 4)) or
            any(not 0x4006 <= value <= 0x4078
                for value in _es_words(main, 0x3FE6, 16))):
        errors.append("direction pair pointer tables ES:$3FC6 изменены")
    if (_es_words(main, 0x438C, 4) !=
            (0xFFF6, 10, 0xFFF6, 10) or
            tuple(_es_words(main, address, 3)
                  for address in range(0x4394, 0x43AC, 6)) !=
            ((0x02E4, 0x015C, 0x46CC),
             (0x033C, 0x011C, 0x4754),
             (0x033C, 0x00EC, 0x47C6),
             (0x02E4, 0x00BC, 0x482E))):
        errors.append("Dobkeratops arena records ES:$438C изменены")

    tracking_vectors = tuple(_es_words(main, address, 2)
                             for address in range(0x3966, 0x39A6, 4))
    signed_tracking_vectors = tuple(
        tuple(((value + 0x8000) & 0xFFFF) - 0x8000 for value in record)
        for record in tracking_vectors)
    if (_es_words(main, 0x3956, 4) !=
            (0xFFF0, 16, 0xFFEC, 20) or
            _es_words(main, 0x395E, 4) !=
            (0xFFE8, 20, 0xFFFE, 2) or
            len(tracking_vectors) != 16 or
            any(signed_tracking_vectors[index + 8] !=
                tuple(-value for value in signed_tracking_vectors[index])
                for index in range(8))):
        errors.append("tracking enemy vectors ES:$3956/$3966 изменены")
    if (_es_words(main, 0x3AF6, 4) !=
            (0xFFFC, 4, 0xFFFC, 4) or
            tuple(_es_words(main, address, 2)
                  for address in range(0x3AFE, 0x3B12, 4)) !=
            ((8, 0x00D0), (16, 0x8024), (64, 0x4003),
             (0x00C0, 0x0110), (0xFFFF, 0x0130)) or
            tuple(_es_words(main, address, 2)
                  for address in range(0x3B12, 0x3B22, 4)) !=
            ((36, 3), (24, 3), (16, 2), (8, 1)) or
            _es_words(main, 0x3B22, 4) !=
            (0x9010, 0x9050, 0x9090, 0x90D0) or
            _es_words(main, 0x3B2A, 4) !=
            (0xFE80, 0xFD00, 0xFC80, 0xFC00)):
        errors.append("animated enemy control records ES:$3AF6 изменены")

    weapon_direction_records = tuple(_es_words(main, address, 3)
                                     for address in range(0x2056,
                                                          0x2086, 6))
    if (_es_words(main, 0x204E, 4) != (12, 12, 4, 4) or
            tuple(record[:2] for record in weapon_direction_records) !=
            ((0, 0xFFF8), (0xFFF8, 0), (0xFFF8, 0), (0, 8),
             (0, 8), (8, 0), (8, 0), (0, 0xFFF8)) or
            _es_words(main, 0x2086, 8) !=
            (8, 8, 8, 0xFFF8, 0xFFF8, 0xFFF8, 0xFFF8, 8) or
            _es_words(main, 0x2096, 2) != (8, 0xFFF8)):
        errors.append("weapon direction records ES:$204E изменены")

    direction_probe_offsets = tuple(_es_words(main, address, 2)
                                    for address in
                                    range(0x1A58, 0x1A98, 4))
    direction_velocities = tuple(_es_words(main, address, 2)
                                 for address in
                                 range(0x1A98, 0x1AD8, 4))
    if (len(direction_probe_offsets) != 16 or
            any(direction_probe_offsets[index + 8] !=
                tuple((-value) & 0xFFFF
                      for value in direction_probe_offsets[index])
                for index in range(8)) or
            direction_probe_offsets[0] != (0, 0xFFF4) or
            direction_probe_offsets[4] != (0xFFF4, 0) or
            direction_probe_offsets[8] != (0, 12) or
            direction_probe_offsets[12] != (12, 0)):
        errors.append("direction terrain-probe offsets ES:$1A58 изменены")
    if (len(direction_velocities) != 16 or
            any(direction_velocities[index + 8] !=
                tuple((-value) & 0xFFFF
                      for value in direction_velocities[index])
                for index in range(8)) or
            direction_velocities[0] != (0, 0x0480) or
            direction_velocities[4] != (0x0480, 0) or
            direction_velocities[8] != (0, 0xFB80) or
            direction_velocities[12] != (0xFB80, 0)):
        errors.append("direction Q8 velocity vectors ES:$1A98 изменены")
    unreferenced_direction_descriptors = tuple(
        _es_words(main, address, 3)
        for address in range(0x1AD8, 0x1AF0, 6)
    )
    if unreferenced_direction_descriptors != (
            (0xF8F8, 0x000C, 0), (0xFAF8, 0x000D, 0),
            (0xF8F8, 0x000C, 0x0400),
            (0xF6F8, 0x000D, 0)):
        errors.append("unreferenced direction descriptors ES:$1AD8 изменены")

    if (_es_words(main, 0x2106, 3) != (0xF8F8, 0x09F2, 0) or
            _es_words(main, 0x210C, 4) != (12, 12, 12, 12)):
        errors.append("player-grid object descriptor/radii ES:$2106 изменены")
    cardinal_probe_steps = tuple(_es_words(main, address, 2)
                                 for address in range(0x2114, 0x2124, 4))
    if (cardinal_probe_steps !=
            ((0, 0xFFF8), (0xFFF8, 0), (0, 8), (8, 0)) or
            _es_words(main, 0x2124, 4) != (6, 2, 2, 6)):
        errors.append("player-grid cardinal tables ES:$2114 изменены")
    grid_probe_records = tuple(_es_words(main, address, 3)
                               for address in range(0x212C, 0x218C, 6))
    if (len(grid_probe_records) != 16 or
            any(record[0] not in (0, 8, 0xFFF8) or
                record[1] not in (0, 8, 0xFFF8) or
                record[2] not in (0, 2, 4, 6)
                for record in grid_probe_records)):
        errors.append("player-grid terrain probe matrix ES:$212C изменена")
    grid_descriptors = tuple(_es_words(main, address, 3)
                             for address in range(0x218C, 0x21A4, 6))
    if grid_descriptors != (
            (0xF8F8, 0x08F4, 0), (0xF8F8, 0x08F5, 0),
            (0xF8F8, 0x08F4, 0x0400),
            (0xF8F8, 0x08F5, 0x0800)):
        errors.append("player-grid direction descriptors ES:$218C изменены")

    if (_es_words(main, 0x2A32, 3) != (0xF0F0, 0x0134, 0x5800) or
            _es_words(main, 0x2A38, 4) !=
            (0xFFF6, 10, 0xFFF6, 10)):
        errors.append("terrain-probing enemy header ES:$2A32 изменён")
    terrain_probe_records = tuple(_es_words(main, address, 4)
                                  for address in range(0x2A40, 0x2A80, 8))
    if terrain_probe_records != (
            (28, 12, 0, 0xFFF4),
            (0xFFF4, 0xFFE8, 12, 0),
            (0xFFE8, 12, 0, 0xFFF4),
            (0xFFF4, 24, 12, 0),
            (24, 12, 0, 0xFFF4),
            (0xFFF4, 0xFFE8, 12, 0),
            (0xFFE4, 12, 0, 0xFFF4),
            (0xFFF4, 24, 12, 0)):
        errors.append("terrain-probe ray records ES:$2A40 изменены")
    cardinal_tiers = tuple(tuple(_es_words(main, address, 2)
                                 for address in range(root, root + 16, 4))
                           for root in range(0x2A80, 0x2AC0, 16))
    expected_cardinal_tiers = tuple(
        ((limit, 0), (0, (-limit) & 0xFFFF),
         ((-limit) & 0xFFFF, 0), (0, limit))
        for limit in (0x80, 0x100, 0x200, 0x300)
    )
    if cardinal_tiers != expected_cardinal_tiers:
        errors.append("terrain-prober cardinal velocity tiers ES:$2A80 изменены")
    probe_sprite_descriptors = tuple(_es_words(main, address, 3)
                                     for address in
                                     range(0x2AC0, 0x2AF0, 6))
    if (len(probe_sprite_descriptors) != 8 or
            tuple(record[0] for record in probe_sprite_descriptors) !=
            (0xD8E0, 0xD800) * 4 or
            any(record[2] != 0x6000 for record in probe_sprite_descriptors)):
        errors.append("terrain-prober sprite frames ES:$2AC0 изменены")

    if (_es_words(main, 0x2E30, 3) != (0xF0F0, 0x0602, 0x5800) or
            _es_words(main, 0x2E36, 4) !=
            (0xFFF4, 12, 0xFFF4, 12) or
            _es_words(main, 0x2E3E, 4) != (6, 10, 25, 40)):
        errors.append("Stage-1 terrain-object header ES:$2E30 изменён")
    terrain_child_records = tuple(_es_words(main, address, 4)
                                  for address in range(0x2E46, 0x2EC6, 8))
    terrain_motion_roots = tuple(record[3]
                                 for record in terrain_child_records)
    if (len(terrain_child_records) != 16 or
            any(not (0x02D0 <= record[0] <= 0x0390 and
                     0x00B0 <= record[1] <= 0x0160 and
                     record[2] in (0, 0x10, 0x20, 0x30))
                for record in terrain_child_records) or
            terrain_motion_roots !=
            (0xB78C, 0xB7AF, 0xB7CC, 0xB7F5,
             0xB819, 0xB83B, 0xB860, 0xB887,
             0xB8AB, 0xB8CE, 0xB8F1, 0xB68C,
             0xB6B0, 0xB6D4, 0xB6F7, 0xB719)):
        errors.append("Stage-1 terrain child records ES:$2E46 изменены")
    packed_tilemap_steps = _es_words(main, 0x2EC6, 20)
    if (packed_tilemap_steps[-1] != 0 or
            any((word >> 8) != 1 or (word & 0xFF) not in (0, 4, 0xFC)
                for word in packed_tilemap_steps[:-1])):
        errors.append("Stage-1 terrain tilemap walk ES:$2EC6 изменён")

    if (_es_words(main, 0x3072, 4) !=
            (0xFFC8, 0x0038, 0xFFEE, 0x0012) or
            tuple(es[0x307A:0x307E]) != (10, 14, 18, 30)):
        errors.append("post-boss object collision/difficulty ES:$3072 изменены")
    post_boss_pointer_banks = tuple(
        _es_words(main, address, 16)
        for address in range(0x307E, 0x30FE, 0x20)
    )
    descriptor_roots_30fe = set(range(0x30FE, 0x31EE, 6))
    if (len(post_boss_pointer_banks) != 4 or
            any(bank[:8] != bank[8:] or
                any(pointer not in descriptor_roots_30fe for pointer in bank)
                for bank in post_boss_pointer_banks)):
        errors.append("post-boss descriptor pointer banks ES:$307E изменены")

    composite_descriptors_35d4 = tuple(_es_words(main, address, 3)
                                       for address in
                                       range(0x35D4, 0x3676, 6))
    if (len(composite_descriptors_35d4) != 27 or
            any(record[2] not in (0x6000, 0x6400, 0x6800, 0x6C00)
                for record in composite_descriptors_35d4) or
            composite_descriptors_35d4[:3] !=
            ((0xE806, 0x04A0, 0x6000),
             (0xE6E6, 0x04A4, 0x6000),
             (0xE606, 0x04B0, 0x6000)) or
            composite_descriptors_35d4[-2:] !=
            ((0xE0EA, 0x0444, 0x6800),
             (0xE00A, 0x0440, 0x6800))):
        errors.append("composite animation descriptors ES:$35D4 изменены")

    tile_replacement_roots = (0x3C5E, 0x3CC6, 0x3D2E,
                              0x3DC2, 0x3E56, 0x3E9A)
    # `$FA55` кладёт в object+$30 второй word записей `$93C4`; только
    # команды 0..5 реально встречаются у event handler `$8C12`.
    if tuple(_es_words(main, 0x93C6 + index * 4, 1)[0]
             for index in range(6)) != tile_replacement_roots:
        errors.append("tile-replacement roots ES:$93C6 изменены")
    tile_replacement_bytes: set[int] = set()
    for root in tile_replacement_roots:
        position = root
        while position + 3 <= 0x3EDD:
            tile_replacement_bytes.update(range(position, position + 4))
            if _es_words(main, position, 1) == (0,):
                if _es_words(main, position + 2, 1) != (0,):
                    errors.append(
                        f"tile-replacement ES:${root:04X} имеет ненулевой terminal tile")
                break
            position += 4
        else:
            errors.append(f"tile-replacement ES:${root:04X} без zero terminal")
    if tile_replacement_bytes != set(range(0x3C5E, 0x3EDE)):
        errors.append("tile-replacement streams не покрывают ES:$3C5E..$3EDD")
    if (_es_words(main, 0x3EDE, 4) !=
            (0xFFE0, 0x0020, 0xFFE0, 0x0020) or
            len(es[0x3EE6:0x3F26]) != 16 * 4):
        errors.append("stage-control collision/targets ES:$3EDE изменены")

    checkpoint_stage_ids = _es_words(main, 0x87FA, 17 * 7)[6::7]
    if checkpoint_stage_ids != (1, 1, 1, 1, 2, 2, 3, 4, 4, 5, 5, 6,
                                6, 7, 7, 8, 1):
        errors.append("17-record checkpoint table ES:$87FA изменилась")
    ending_pointers = _es_words(main, 0x88E8, 21)
    if (ending_pointers[-1] != 0 or len(set(ending_pointers[:-1])) != 19 or
            min(ending_pointers[:-1]) != 0x8912 or
            max(ending_pointers[:-1]) != 0x8B6A):
        errors.append("ending text pointer list ES:$88E8 изменился")
    if _es_words(main, 0x46C4, 4) != (0xFFF8, 8, 0xFFF8, 8):
        errors.append("Dobkeratops arena-writer extents ES:$46C4 изменились")
    for root, count in BOSS_TERRAIN_PATHS.items():
        if _es_words(main, root + (count - 1) * 2, 1) != (0x8000,):
            errors.append(f"boss terrain path ES:${root:04X} потерял sentinel")
    tentacle_motion_roots = tuple(range(0x48AA, 0x4CAC, 0x36))
    if (len(tentacle_motion_roots) != 19 or
            tentacle_motion_roots[-1] != 0x4C76):
        errors.append("Dobkeratops tentacle motion roots ES:$48AA изменены")
    for root in tentacle_motion_roots:
        durations = _es_words(main, root + 4, 9 * 3)[::3]
        if (len(durations) != 9 or
                any(value & 0x8000 for value in durations[:-1]) or
                not durations[-1] & 0x8000 or
                any((value & 0x0FFF) == 0 for value in durations)):
            errors.append(f"tentacle motion script ES:${root:04X} неверен")
    if _es_words(main, 0x4CBE, 4) != (0xFFFA, 6, 0xFFFA, 6):
        errors.append("tentacle-tip collision extents ES:$4CBE изменены")

    presentation_records = [
        _es_words(main, address, 2)
        for address in range(0x4D1C, 0x4D64, 4)
    ]
    if (len(presentation_records) != 18 or
            presentation_records[-1] != (0xFFFF, 2) or
            [record[0] for record in presentation_records[:-1]] !=
            sorted(record[0] for record in presentation_records[:-1]) or
            {record[1] for record in presentation_records} != {0, 1, 2, 3}):
        errors.append("boss presentation timeline ES:$4D1C изменена")
    multipart_schedule = [
        _es_words(main, address, 2)
        for address in range(0x4D62, 0x4D82, 4)
    ]
    if (multipart_schedule !=
            [(2, 0x03C0), (3, 0x0240), (1, 0x0280), (0, 0x0280),
             (3, 0x0240), (2, 0x03C0), (0, 0x0280), (1, 0xFFFF)] or
            sum(delay for _command, delay in multipart_schedule[:-1]) >=
            0x1780):
        errors.append("boss multipart schedule ES:$4D62 изменён")
    presentation_layouts = [
        _es_words(main, address, 5)
        for address in range(0x4D82, 0x4DAA, 10)
    ]
    normal_tile_roots = [record[1] for record in presentation_layouts]
    flashing_tile_roots = [record[0] for record in presentation_layouts]
    dimensions = [record[2] for record in presentation_layouts]
    if (normal_tile_roots != [0x4DAA, 0x4E1A, 0x4EAA, 0x4F1A] or
            flashing_tile_roots != [0x4FBA, 0x502A, 0x50BA, 0x512A] or
            dimensions != [0x0708, 0x0908, 0x0708, 0x0A08]):
        errors.append("boss tile layout records ES:$4D82 изменены")
    for roots, expected_end in ((normal_tile_roots, 0x4FB9),
                                (flashing_tile_roots, 0x51C9)):
        for index, root in enumerate(roots):
            size = 2 * (dimensions[index] & 0xFF) * (dimensions[index] >> 8)
            expected = (roots[index + 1]
                        if index + 1 < len(roots) else expected_end + 1)
            if root + size != expected:
                errors.append(f"boss tile rectangle ES:${root:04X} оборван")
    tile_patch_roots = tuple(range(0x51EA, 0x54EA, 0x60))
    if (_es_words(main, 0x51CA, 8) != tile_patch_roots or
            _es_words(main, 0x51DA, 8) != tuple(reversed(tile_patch_roots))):
        errors.append("boss tile-patch pointer tables ES:$51CA изменены")
    if (_es_words(main, 0x54EA, 4) != (0xFFF0, 0x0010,
                                      0xFFF8, 0x0008)):
        errors.append("boss collision extents ES:$54EA изменены")
    particle_samples = set(range(0x54F2, 0x5602, 4))
    particle_path = _es_words(main, 0x5602, 289)
    if (particle_path[-1] != 0 or
            set(particle_path[:-1]) != particle_samples or
            any(pointer not in particle_samples for pointer in particle_path[:-1])):
        errors.append("boss particle pointer path ES:$5602 изменён")
    if (tuple(es[0x5844:0x5848]) != (48, 40, 32, 24) or
            _es_words(main, 0x5848, 4) !=
            (0x0300, 0x0380, 0x0400, 0x0480) or
            _es_words(main, 0x5850, 8) !=
            (8, 40, 24, 8, 40, 24, 8, 40) or
            _es_words(main, 0x5860, 8) !=
            (12, 31, 31, 12, 12, 31, 12, 31)):
        errors.append("boss difficulty/RNG projectile tables ES:$5844 изменены")
    if _es_words(main, 0x58E6, 4) != (0xFFFC, 4, 0xFFFC, 4):
        errors.append("multipart debris collision extents ES:$58E6 изменены")
    debris_path_roots = (0x58EE, 0x594E, 0x59A6)
    debris_path_ends = (0x594E, 0x59A6, 0x5A02)
    debris_path_counts = (23, 21, 22)
    for root, expected_end, count in zip(debris_path_roots,
                                         debris_path_ends,
                                         debris_path_counts):
        position = root
        coordinate_count = 0
        while position < expected_end:
            record = _es_words(main, position, 2)
            position += 4
            if record == (0x8000, 0):
                break
            coordinate_count += 1
        if position != expected_end or coordinate_count != count:
            errors.append(f"multipart debris path ES:${root:04X} изменён")
    multipart_collision_records = [
        _es_words(main, address, 4)
        for address in range(0x5A9A, 0x5ABA, 8)
    ]
    if (len(multipart_collision_records) != 4 or
            multipart_collision_records[-1] !=
            (0xFFD0, 0xFFF0, 0xFFF8, 0)):
        errors.append("multipart-boss collision extents ES:$5A9A изменены")
    route_list_roots = tuple(range(0x5AFA, 0x5B54, 10))
    route_selectors = [
        _es_words(main, address, 4)
        for address in range(0x5ABA, 0x5AFA, 8)
    ]
    if (len(route_selectors) != 8 or
            any(record[3] != 0 or
                any(pointer not in route_list_roots for pointer in record[:3])
                for record in route_selectors)):
        errors.append("multipart route selectors ES:$5ABA изменены")
    motion_record_roots: set[int] = set()
    for root in route_list_roots:
        record = _es_words(main, root, 5)
        if record[-1] != 0:
            errors.append(f"multipart route list ES:${root:04X} без zero")
        motion_record_roots.update(record[:-1])
    multipart_motion_bytes: set[int] = set()
    for root in motion_record_roots:
        position = root
        while position + 5 <= 0x5F07:
            multipart_motion_bytes.update(range(position, position + 6))
            if _es_words(main, position, 1) == (0x8000,):
                break
            position += 6
        else:
            errors.append(f"multipart motion stream ES:${root:04X} без `$8000`")
    if (motion_record_roots !=
            {0x5B54, 0x5B5C, 0x5BC4, 0x5C2C, 0x5C94,
             0x5CFC, 0x5D64, 0x5DCC, 0x5E34, 0x5E9C} or
            multipart_motion_bytes != set(range(0x5B54, 0x5F08))):
        errors.append("multipart motion streams не покрывают ES:$5B54..$5F07")
    if (_es_words(main, 0x5F58, 2) != (0x8000, 0) or
            len(es[0x5F08:0x5F5C]) != 20 * 4 + 4):
        errors.append("alternate B073 path ES:$5F08 изменён")
    if (_es_words(main, 0x5F5C, 4) != (51, 32, 24, 16) or
            _es_words(main, 0x5F64, 4) !=
            (0x8FD0, 0x9050, 0x9090, 0x90D0)):
        errors.append("multipart difficulty/vector tables ES:$5F5C изменены")
    if (len(es[0x5F6C:0x6000]) != 37 * 4 or
            _es_words(main, 0x6000, 1) != (0x8000,) or
            len(es[0x6002:0x6082]) != 32 * 4):
        errors.append("multipart spawn/target coordinates ES:$5F6C изменены")
    if _es_words(main, 0x631A, 16) != (
            (0xFF00,) * 4 + (0,) * 8 + (0x0100,) * 4):
        errors.append("phase-object Q8 velocity table ES:$631A изменена")
    phase_sprite_pointers = _es_words(main, 0x633A, 32)
    if (phase_sprite_pointers !=
            ((0x63E6,) * 9 + (0x63F2,) + (0x63FE,) +
             (0x640A,) * 3 + (0x63FE,) + (0x63F2,) +
             (0x63E6,) * 16) or
            _es_words(main, 0x637A, 1) != (0x63E6,)):
        errors.append("phase-object sprite pointer table ES:$633A изменена")
    phase_collision_pointers = _es_words(main, 0x637C, 32)
    if (phase_collision_pointers !=
            ((0x63C6,) * 9 + (0x63CE,) + (0x63D6,) +
             (0x63DE,) * 3 + (0x63D6,) + (0x63CE,) +
             (0x63C6,) * 16) or
            _es_words(main, 0x63BC, 1) != (0x63C6,)):
        errors.append("phase-object collision pointer table ES:$637C изменена")
    if (_es_words(main, 0x63BE, 4) !=
            (0xFFFA, 6, 0xFFF6, 11) or
            tuple(_es_words(main, address, 4)
                  for address in range(0x63C6, 0x63E6, 8)) !=
            ((0xFFD8, 0xFFF0, 0xFFE8, 2),
             (0xFFD8, 0xFFF0, 0xFFE8, 8),
             (0xFFD8, 0xFFF0, 0xFFE8, 16),
             (0xFFD8, 0xFFF0, 0xFFE8, 24))):
        errors.append("phase-object collision records ES:$63BE изменены")
    if _es_words(main, 0x64B4, 4) != (0xFFF2, 0x0030,
                                      0xFFD0, 0x0030):
        errors.append("final-stage gate collision extents ES:$64B4 изменены")
    gate_frames = tuple(range(0x64BC, 0x69BC, 0x100))
    if gate_frames != (0x64BC, 0x65BC, 0x66BC, 0x67BC, 0x68BC):
        errors.append("gate 8x8 frame roots ES:$64BC изменены")
    for root in gate_frames:
        attributes = _es_words(main, root + 2, 64 * 2)[::2]
        if len(es[root:root + 0x100]) != 0x100 or not set(attributes) <= {
                0x0082, 0x0083}:
            errors.append(f"gate 8x8 frame ES:${root:04X} имеет неверный формат")
    gate_patch_roots = tuple(range(0x69EC, 0x6CE0, 0x54))
    if (gate_patch_roots !=
            (0x69EC, 0x6A40, 0x6A94, 0x6AE8, 0x6B3C,
             0x6B90, 0x6BE4, 0x6C38, 0x6C8C) or
            _es_words(main, 0x69BC, 8) !=
            (gate_patch_roots[0], gate_patch_roots[1],
             gate_patch_roots[2], gate_patch_roots[3],
             gate_patch_roots[3], gate_patch_roots[2],
             gate_patch_roots[1], gate_patch_roots[0]) or
            _es_words(main, 0x69CC, 16) !=
            (gate_patch_roots[0], gate_patch_roots[5],
             gate_patch_roots[6], gate_patch_roots[7],
             gate_patch_roots[8], gate_patch_roots[8],
             gate_patch_roots[8], gate_patch_roots[8],
             gate_patch_roots[8], gate_patch_roots[8],
             gate_patch_roots[8], gate_patch_roots[8],
             gate_patch_roots[7], gate_patch_roots[6],
             gate_patch_roots[5], gate_patch_roots[0])):
        errors.append("gate 7x6 patch pointer animations ES:$69BC изменены")
    if any(len(es[root:root + 0x54]) != 6 * 7 * 2
           for root in gate_patch_roots):
        errors.append("gate 7x6 patch frames ES:$69EC оборваны")

    def verify_ed93_records(starts: list[int], expected_end: int) -> None:
        ends = []
        for start in starts:
            dimensions = int.from_bytes(es[start + 2:start + 4], "little")
            size = (dimensions & 0xFF) * (dimensions >> 8)
            ends.append(start + 5 + size)
        if max(ends) != expected_end:
            errors.append(f"ED93 record block не заканчивается на ${expected_end:04X}")

    verify_ed93_records(list(range(0x8912, 0x8B88, 30)), 0x8B87)
    verify_ed93_records([0x8B88], 0x8BA9)
    verify_ed93_records([0x8BAA], 0x8BCD)
    verify_ed93_records([0x8BCE], 0x8BDF)
    all_resource_roots = _es_words(main, 0x8C20, 24)
    resource_roots = all_resource_roots[:11]
    if resource_roots != tuple(range(0x8C50, 0x8DB0, 0x20)):
        errors.append("stage resource roots ES:$8C20 изменились")
    if any(_es_words(main, root, 16)[-1] != 0x801F
           for root in resource_roots):
        errors.append("stage resource list не завершается `$801F`")
    if all_resource_roots[11:] != (0x8C50,) * 13:
        errors.append("fallback resource roots ES:$8C36..$8C4F изменились")
    if (_es_words(main, 0x9260, 5) != (3, 3, 3, 3, 3) or
            _es_words(main, 0x926A, 5) != (3, 0, 1, 2, 0)):
        errors.append("patrol command cycles ES:$9260 изменились")
    projectile_records = [
        _es_words(main, address, 3)
        for address in range(0x8E10, 0x8F90, 6)
    ]
    if (len(projectile_records) != 64 or
            {record[2] for record in projectile_records[:40]} -
            {0, 0x8F90, 0x8FD0, 0x9010, 0x9050, 0x9090,
             0x90D0, 0x9110}):
        errors.append("F8A7 projectile parameter matrix ES:$8E10 изменена")
    vector_roots = tuple(range(0x8F90, 0x9250, 0x40))
    if (len(vector_roots) != 11 or
            any(es[left:left + 0x40] != es[right:right + 0x40]
                for left, right in zip(vector_roots[:4], vector_roots[7:]))):
        errors.append("последние четыре vector tables ES:$9150 не дублируют первые")
    timeline_roots = []
    position = 0x945C
    while position < 0x94CA:
        root = int.from_bytes(es[position:position + 2], "little")
        if root == 0:
            break
        timeline_roots.append(root)
        position += 6
    if (timeline_roots != [0x94CA, 0x94DC, 0x94EE, 0x9520, 0x9542,
                           0x9564, 0x9586, 0x95B0, 0x95C2, 0x95D4,
                           0x95E6, 0x95F8, 0x962A, 0x963C, 0x9666,
                           0x9688, 0x96B2, 0x96C4] or
            int.from_bytes(es[position:position + 2], "little") != 0):
        errors.append("FB10 timeline root table ES:$945C изменилась")
    timeline_bytes: set[int] = set()
    for root in timeline_roots:
        position = root
        while position + 9 <= 0x96D5:
            timeline_bytes.update(range(position, position + 10))
            if int.from_bytes(es[position + 8:position + 10],
                              "little") == 0x8000:
                break
            position += 8
        else:
            errors.append(f"FB53 timeline ${root:04X} не имеет `$8000`")
    if timeline_bytes != set(range(0x94CA, 0x96D6)):
        errors.append("FB53 timelines не покрывают ровно ES:$94CA..$96D5")
    if [int.from_bytes(es[address + 2:address + 4], "little")
        for address in range(0x96D6, 0x96F4, 6)] != list(range(0x20, 0x25)):
        errors.append("FB53 descriptor codes ES:$96D6 изменились")

    alternate = []
    position = 0x96F4
    while position < 0x989C:
        alternate.append(position)
        dimensions = int.from_bytes(es[position + 2:position + 4], "little")
        position += 6 + (dimensions & 0xFF) * (dimensions >> 8)
    if len(alternate) != 14 or position != 0x989C:
        errors.append("alternate ending text ES:$96F4 не равно 14 ED93 records")
    presentation_indices = {0x1B, 0x17, 0x1A, 0x11}
    stage_palette_indices: set[int] = set()
    for _stage, first, last in STAGE_RANGES:
        for address in range(first, last + 1, 4):
            command = int.from_bytes(es[address + 2:address + 4], "little")
            if ((command >> 9) & 0x7E) == 0x40:
                stage_palette_indices.add(command & 0xFF)
    if (stage_palette_indices | presentation_indices !=
            set(range(28)) - {0x10, 0x18, 0x19}):
        errors.append("28 palette-control records ES:$989C имеют неполный consumer index")
    terminal_spawn_records = [
        _es_words(main, address, 2)
        for address in range(0xC5E3, 0xC627, 4)
    ]
    if (len(terminal_spawn_records) != 17 or
            [record[0] for record in terminal_spawn_records[:-1]] !=
            list(range(0, 0x640, 0x64)) or
            terminal_spawn_records[-1] != (0x869F, 0x2000)):
        errors.append("terminal spawn table ES:$C5E3 изменилась")
    if (_es_words(main, 0x6F88, 1) != (0xFFFF,) or
            len(es[0x6F8A:0x7302]) != 296 * 3 or
            es[0x7301] != 0x80 or
            any(es[address + 2] == 0x80
                for address in range(0x6F8A, 0x72FF, 3))):
        errors.append("final-stage scroll script ES:$6F88..$7301 изменился")
    foreground_packages = [
        0x7302, 0x7322, 0x7366, 0x737E, 0x7398, 0x73AC, 0x73C6,
        0x73F6, 0x7426, 0x7446, 0x7466, 0x7486, 0x74A6, 0x74F6,
        0x753A, 0x756C, 0x75B0, 0x75F0, 0x761C, 0x7644, 0x766A,
        0x769A, 0x76D2, 0x76F2, 0x7712, 0x7738, 0x776A,
    ]
    foreground_collisions = list(range(0x77B8, 0x7890, 8))
    if [_es_words(main, root, 1)[0] for root in foreground_packages] != \
            foreground_collisions:
        errors.append("27 foreground package collision roots изменились")
    for index, root in enumerate(foreground_packages):
        dimensions = _es_words(main, root + 6, 1)[0]
        end = root + 7 + 2 * (dimensions & 0xFF) * (dimensions >> 8)
        expected = (foreground_packages[index + 1] - 1
                    if index + 1 < len(foreground_packages) else 0x77B7)
        # `$7732..$7737` — три неадресуемых cell words между двумя пакетами.
        if root == 0x7712:
            expected -= 6
        if end != expected:
            errors.append(f"foreground tile package ES:${root:04X} оборван")
    background_packages = [0x7890, 0x78B0, 0x78E8, 0x7910]
    if ([_es_words(main, root, 1)[0] for root in background_packages] !=
            list(range(0x7938, 0x7958, 8))):
        errors.append("4 background package collision roots изменились")
    for index, root in enumerate(background_packages):
        dimensions = _es_words(main, root + 6, 1)[0]
        end = root + 7 + 2 * (dimensions & 0xFF) * (dimensions >> 8)
        expected = (background_packages[index + 1] - 1
                    if index + 1 < len(background_packages) else 0x7937)
        if end != expected:
            errors.append(f"background tile package ES:${root:04X} оборван")
    if (_es_words(main, 0x796C, 2) != (0x8000, 0) or
            len(es[0x7958:0x7970]) != 6 * 4):
        errors.append("explosion offset loop ES:$7958 изменился")
    if (_es_words(main, 0x7A3C, 4) !=
            (0xFFD8, 32, 0xFFF1, 15) or
            _es_words(main, 0x7A44, 4) !=
            (0xFFE0, 64, 0xFFF0, 16) or
            _es_words(main, 0x7A4C, 4) !=
            (0xFFFC, 4, 0xFFFC, 4) or
            tuple(_es_words(main, address, 2)
                  for address in range(0x7A54, 0x7A6C, 4)) !=
            ((3, 14), (0xFFF4, 19), (14, 0xFFEA),
             (0xFFF0, 0xFFF3), (5, 0xFFFD), (0x8000, 0))):
        errors.append("paired late-body records ES:$7A3C изменены")
    late_spawn_roots = tuple(range(0x7CF0, 0x7D32, 6))
    late_spawn_pointer_values = {
        value
        for root in (0x7C30, 0x7C50, 0x7C70,
                     0x7C90, 0x7CB0, 0x7CD0)
        for value in _es_words(main, root, 16)
        if value
    }
    if (late_spawn_roots !=
            (0x7CF0, 0x7CF6, 0x7CFC, 0x7D02, 0x7D08, 0x7D0E,
             0x7D14, 0x7D1A, 0x7D20, 0x7D26, 0x7D2C) or
            late_spawn_pointer_values != set(late_spawn_roots) or
            any(not 0x7D32 <= _es_words(main, root + 4, 1)[0] <= 0x7DAA
                for root in late_spawn_roots)):
        errors.append("late child spawn records ES:$7CF0 изменены")
    if (_es_words(main, 0x7AEA, 4) !=
            (0xFFF4, 12, 2, 12) or
            _es_words(main, 0x7B26, 1) != (0x8000,) or
            len(tuple(_es_words(main, address, 2)
                      for address in range(0x7AF2, 0x7B26, 4))) != 13):
        errors.append("late enemy debris records ES:$7AEA изменены")
    late_enemy_timeline = tuple(_es_words(main, address, 2)
                                for address in range(0x7E56, 0x7E9A, 4))
    if (_es_words(main, 0x7E46, 4) !=
            (0xFFF4, 12, 0xFFF6, 10) or
            _es_words(main, 0x7E4E, 4) !=
            (0xFFF8, 8, 0xFFF8, 8) or
            late_enemy_timeline !=
            ((0x0000, 0x0004), (0x06D0, 0x0006),
             (0x070C, 0x0004), (0x0748, 0x8004),
             (0x0810, 0x8004), (0x0844, 0x0006),
             (0x0878, 0x0000), (0x08D0, 0x8000),
             (0x0968, 0x8000), (0x09B8, 0x000A),
             (0x0B80, 0x0008), (0x0BE4, 0x8008),
             (0x0C48, 0x8008), (0x0D22, 0x000A),
             (0x0E00, 0x0000), (0x0E64, 0x8000),
             (0xFFFF, 0x0004))):
        errors.append("late enemy hitboxes/timeline ES:$7E46 изменены")
    emitter_control_roots = tuple(range(0x8066, 0x80C6, 0x18))
    emitter_control_records = tuple(_es_words(main, root, 12)
                                    for root in emitter_control_roots)
    if (emitter_control_roots != (0x8066, 0x807E, 0x8096, 0x80AE) or
            any(any(value not in (0, 0x0200, 0xFE00)
                    for value in record[:10])
                for record in emitter_control_records) or
            tuple(record[10:] for record in emitter_control_records) !=
            ((0, 0xFFFD), (0, 3), (0, 0xFFFD), (0, 3))):
        errors.append("moving-emitter control records ES:$8066 изменены")
    if _es_words(main, 0x80C6, 4) != (0xFFF8, 8, 0xFFF8, 8):
        errors.append("moving-emitter collision extents ES:$80C6 изменены")
    debris_position = 0x80CE
    debris_count = 0
    while debris_position < 0x812E:
        record = _es_words(main, debris_position, 2)
        debris_position += 4
        if record == (0x8000, 0):
            break
        debris_count += 1
    if debris_position != 0x812E or debris_count != 23:
        errors.append("moving-emitter debris path ES:$80CE изменён")
    if (_es_words(main, 0x8304, 4) !=
            (0xFFF4, 12, 0xFFF2, 0xFFFE) or
            _es_words(main, 0x830C, 4) !=
            (0xFFF4, 12, 2, 14)):
        errors.append("upper/lower collision extents ES:$8304 изменены")
    resource_owner_records = tuple(_es_words(main, address, 3)
                                   for address in range(0x8314, 0x832C, 6))
    if resource_owner_records != (
            (0x0160, 0x836C, 6),
            (0x8000, 0x832C, 10),
            (0x0890, 0x836C, 6),
            (0x0890, 0x836C, 6)):
        errors.append("resource-owner records ES:$8314 изменены")
    positive_horizontal = _es_words(main, 0x832C, 32)
    negative_horizontal = _es_words(main, 0x836C, 32)
    if (any(value not in (0x00C0, 0x0100, 0x0180,
                          0x0240, 0x0300)
            for value in positive_horizontal) or
            negative_horizontal !=
            tuple((-value) & 0xFFFF for value in positive_horizontal)):
        errors.append("RNG horizontal velocity tables ES:$832C изменены")

    for item in proven_runtime_ranges:
        mark(item["start"], item["end"], "runtime:" + str(item["format"]))

    # Exact interpreter-owned arrays.  They are kept in the same explicit
    # format/consumer contract as all smaller runtime ranges: byte coverage by
    # itself is not enough for the strict semantic completion criterion.
    interpreter_ranges = [
        {"start": 0xB92D, "end": 0xB990,
         "format": "50 x u16 stage-event handler pointer",
         "consumers": [0x1BC6, 0xFB06]},
        {"start": 0xB993, "end": 0xC5E2,
         "format": "788 x 4-byte stage event (u16 distance, u16 command)",
         "consumers": [0x1BB0, 0x1BBA]},
        {"start": 0xC627, "end": 0xD68E,
         "format": "2100 x u16 foreground metatile descriptor: 14-bit index plus flip X/Y",
         "consumers": [0xEA95]},
        {"start": 0xD68F, "end": 0xEB06,
         "format": "2620 x u16 background metatile descriptor: 14-bit index plus flip X/Y",
         "consumers": [0xEB02]},
        {"start": 0xEF55, "end": 0xFFFF,
         "format": "4267 erased `$FF` bytes with no consumers",
         "consumers": []},
    ]
    for item in interpreter_ranges[:-1]:
        mark(item["start"], item["end"], str(item["format"]))
    for item in service_data["ranges"]:
        mark(item["start"], item["end"], "service:" + str(item["format"]))
    if any(byte != 0xFF for byte in es[0xEF55:]):
        errors.append("World ES erased tail `$EF55..$FFFF` изменился")
    mark(0xEF55, 0xFFFF, str(interpreter_ranges[-1]["format"]))

    def runs(predicate) -> list[dict[str, object]]:
        result = []
        start = 0
        current = predicate(tags[0])
        for address in range(1, 0x10000):
            value = predicate(tags[address])
            if value != current:
                result.append({"start": start, "end": address - 1,
                               "classification": current})
                start = address
                current = value
        result.append({"start": start, "end": 0xFFFF,
                       "classification": current})
        return result

    classified_runs = runs(lambda value: "+".join(sorted(value)) if value
                           else "unresolved")
    unresolved_runs = [item for item in classified_runs
                       if item["classification"] == "unresolved"]
    known_byte_count = sum(bool(value) for value in tags)
    return {
        "known_byte_count": known_byte_count,
        "unresolved_byte_count": 0x10000 - known_byte_count,
        "complete": known_byte_count == 0x10000,
        "classified_runs": classified_runs,
        "unresolved_runs": unresolved_runs,
        "sprite_descriptor_addresses": len(descriptor_calls),
        "sprite_descriptor_consumers": [
            {"address": address, "consumer_calls": sorted(calls)}
            for address, calls in sorted(descriptor_calls.items())
        ],
        "motion_bytecode": {
            "arena_start": 0x9A5C,
            "arena_end": 0xB92C,
            "literal_roots": sorted(motion_literal_roots),
            "table_roots": sorted(motion_table_roots),
            "orphan_roots": sorted(motion_orphan_roots),
            "all_roots": sorted(motion_roots),
            "word_byte_count": len(motion_word_bytes),
            "byte_streams": sorted(motion_streams),
            "byte_stream_byte_count": len(motion_stream_bytes),
            "count_words": [[address, count]
                            for address, count in motion_count_words],
            "redirect_edges": [[root, address, target]
                               for root, address, target
                               in motion_redirect_edges],
            "stream_ends": [[start, end]
                            for start, end in sorted(motion_stream_ends.items())],
        },
        "proven_runtime_ranges": proven_runtime_ranges,
        "interpreter_ranges": interpreter_ranges,
    }


def entropy(data: bytes) -> float:
    counts = collections.Counter(data)
    size = len(data)
    return -sum((count / size) * math.log2(count / size)
                for count in counts.values()) if size else 0.0


@dataclass(frozen=True)
class Range:
    start: int
    end: int
    kind: str
    meaning: str
    evidence: str


@dataclass(frozen=True)
class Instruction:
    address: int
    size: int
    raw: str
    mnemonic: str
    operands: str


@dataclass(frozen=True)
class Z80Instruction:
    address: int
    size: int
    raw: str
    flow: str
    target: int | None


class RecursiveV30:
    """Консервативный обход только доказанных прямых переходов V30.

    Capstone x86-16 используется для общей 8086 части. NEC opcode `0F 20`
    декодируется отдельно: на V30 это двухбайтный `ADD4S`, тогда как Capstone
    ошибочно поглощает следующий ModR/M byte как `MOV r32,CRx`.
    """

    def __init__(self, image: bytes, physical_base: int, logical_size: int,
                 seeds: set[int], function_seeds: set[int] | None = None) -> None:
        self.image = image
        self.physical_base = physical_base
        self.logical_size = logical_size
        self.seeds = set(seeds)
        self.function_entries = set(function_seeds or seeds)
        self.md = Cs(CS_ARCH_X86, CS_MODE_16)
        self.md.detail = True
        self.instructions: dict[int, Instruction] = {}
        self.owners: dict[int, int] = {}
        self.calls: set[tuple[int, int]] = set()
        self.jumps: set[tuple[int, int]] = set()
        self.far_calls: set[tuple[int, int, int]] = set()
        self.far_jumps: set[tuple[int, int, int]] = set()
        self.data_refs: set[tuple[int, str, int]] = set()
        self.invalid: set[int] = set()
        self.conflicts: set[tuple[int, int, int]] = set()

    def _one(self, address: int):
        physical = self.physical_base + address
        if not 0 <= address < self.logical_size or physical >= len(self.image):
            return None
        return next(self.md.disasm(self.image[physical:physical + 15],
                                   address, count=1), None)

    def run(self) -> None:
        queue = collections.deque(sorted(self.seeds))
        queued = set(queue)
        while queue:
            entry = queue.popleft()
            pc = entry
            while 0 <= pc < self.logical_size:
                if pc in self.instructions:
                    break
                physical = self.physical_base + pc
                if self.image[physical:physical + 2] == b"\x0f\x20":
                    record = Instruction(pc, 2, "0f 20", "add4s", "")
                    self.instructions[pc] = record
                    for byte_address in range(pc, min(self.logical_size,
                                                       pc + record.size)):
                        previous = self.owners.setdefault(byte_address, pc)
                        if previous != pc:
                            self.conflicts.add((byte_address, previous, pc))
                    pc += record.size
                    continue
                insn = self._one(pc)
                if insn is None or not insn.size:
                    self.invalid.add(pc)
                    break
                record = Instruction(pc, insn.size, insn.bytes.hex(" "),
                                     insn.mnemonic, insn.op_str)
                self.instructions[pc] = record
                for byte_address in range(pc, min(self.logical_size,
                                                   pc + insn.size)):
                    previous = self.owners.setdefault(byte_address, pc)
                    if previous != pc:
                        self.conflicts.add((byte_address, previous, pc))

                for operand in insn.operands:
                    if operand.type != X86_OP_MEM:
                        continue
                    mem = operand.mem
                    if mem.base == 0 and mem.index == 0 and 0 <= mem.disp <= 0xFFFF:
                        space = "ES" if mem.segment == X86_REG_ES else "DS"
                        self.data_refs.add((pc, space, mem.disp & 0xFFFF))

                is_call = insn.group(CS_GRP_CALL)
                is_jump = insn.group(CS_GRP_JUMP)
                far = None
                if (insn.mnemonic in ("lcall", "ljmp") and
                        len(insn.operands) >= 2 and
                        insn.operands[0].type == X86_OP_IMM and
                        insn.operands[1].type == X86_OP_IMM):
                    far = (insn.operands[0].imm & 0xFFFF,
                           insn.operands[1].imm & 0xFFFF)
                    if is_call:
                        self.far_calls.add((pc, far[0], far[1]))
                    else:
                        self.far_jumps.add((pc, far[0], far[1]))
                direct = None
                if (far is None and insn.operands and
                        insn.operands[0].type == X86_OP_IMM):
                    direct = insn.operands[0].imm & 0xFFFF
                if is_call and direct is not None:
                    self.calls.add((pc, direct))
                    self.seeds.add(direct)
                    self.function_entries.add(direct)
                    if direct not in queued:
                        queue.append(direct)
                        queued.add(direct)
                elif is_jump and direct is not None:
                    self.jumps.add((pc, direct))
                    if direct not in queued:
                        queue.append(direct)
                        queued.add(direct)

                next_pc = pc + insn.size
                stop = (insn.mnemonic.startswith("ret") or
                        insn.mnemonic in ("iret", "hlt") or
                        (is_jump and insn.mnemonic in ("jmp", "ljmp")))
                if stop:
                    break
                pc = next_pc

    def functions(self) -> list[dict[str, object]]:
        entries = sorted(address for address in self.function_entries
                         if address in self.instructions)
        result = []
        for index, start in enumerate(entries):
            limit = entries[index + 1] if index + 1 < len(entries) else self.logical_size
            addresses = sorted(address for address in self.instructions
                               if start <= address < limit)
            if not addresses:
                continue
            end = max(address + self.instructions[address].size - 1
                      for address in addresses)
            result.append({
                "entry": start,
                "physical": self.physical_base + start,
                "end": end,
                "instruction_count": len(addresses),
                "direct_calls": sorted({target for source, target in self.calls
                                        if start <= source <= end}),
            })
        return result

    def listing(self) -> list[dict[str, object]]:
        """Вернуть воспроизводимый полный список достигнутых инструкций."""
        return [asdict(self.instructions[address])
                for address in sorted(self.instructions)]


def discover_object_handler_edges(image: bytes, analysis: RecursiveV30
                                  ) -> set[tuple[int, int, str]]:
    """Найти буквальные записи handler в поле `+0` текущего/нового object.

    BP — текущая 64-byte object record, SI/IX — запись, возвращённая
    allocator `$03A6`. Запись immediate word по нулевому displacement является
    state edge, недоступным обычному графу CALL/JMP.
    """
    md = Cs(CS_ARCH_X86, CS_MODE_16)
    md.detail = True
    result = set()
    for address in sorted(analysis.instructions):
        if address == 0x556C:
            # `$556C: MOV [SI],$801F` завершает palette record list.
            continue
        physical = analysis.physical_base + address
        insn = next(md.disasm(image[physical:physical + 15], address, count=1),
                    None)
        if insn is None or insn.mnemonic != "mov" or len(insn.operands) != 2:
            continue
        destination, source = insn.operands
        if destination.type != X86_OP_MEM or source.type != X86_OP_IMM:
            continue
        mem = destination.mem
        if mem.disp != 0 or mem.index != 0 or mem.base not in (X86_REG_BP,
                                                               X86_REG_SI):
            continue
        target = source.imm & 0xFFFF
        physical_target = analysis.physical_base + target
        if not 0 <= target < analysis.logical_size:
            continue
        # Нулевой handler — явный inactive/delete marker. Нельзя фильтровать
        # по первому opcode byte: `$6B4F` законно начинается с `$FF` (`DEC
        # word [BP+$34]`). Старый тест терял первый instruction этого state.
        if target in (0x0000, 0xFFFF):
            continue
        if target in analysis.owners and analysis.owners[target] != target:
            # Immediate совпал с interior byte уже доказанной инструкции;
            # пример — palette sentinel `$801F` в `$556C`, не handler.
            continue
        owner = "current-object" if mem.base == X86_REG_BP else "new-object"
        result.add((address, target, owner))

    for address, target in ADJACENT_FIXED_HANDLER_TARGET_BY_SITE.items():
        if address not in analysis.instructions:
            continue
        insn = analysis._one(address)
        if insn is None or insn.mnemonic != "mov" or len(insn.operands) != 2:
            raise ValueError(f"изменён adjacent fixed handler producer ${address:04X}")
        destination, source = insn.operands
        if (destination.type != X86_OP_MEM or source.type != X86_OP_IMM or
                destination.mem.base != X86_REG_BP or
                destination.mem.index != 0 or destination.mem.disp != 0x20 or
                (source.imm & 0xFFFF) != target):
            raise ValueError(f"изменён adjacent fixed handler edge ${address:04X}")
        result.add((address, target, "next-fixed-object"))
    return result


def expand_v30_state_graph(image: bytes, physical_base: int, logical_size: int,
                           seeds: set[int]) -> tuple[RecursiveV30,
                                                     set[tuple[int, int, str]],
                                                     set[int]]:
    """Повторять traversal, пока ROM-записи object handler не замкнутся."""
    function_seeds = set(seeds)
    all_edges: set[tuple[int, int, str]] = set()
    while True:
        analysis = RecursiveV30(image, physical_base, logical_size,
                                function_seeds, function_seeds)
        analysis.run()
        edges = discover_object_handler_edges(image, analysis)
        all_edges |= edges
        targets = {target for _source, target, _owner in edges}
        new_targets = targets - function_seeds
        if not new_targets:
            return analysis, all_edges, function_seeds
        function_seeds |= new_targets


def discover_boot39_state_entries(image: bytes, analysis: RecursiveV30
                                  ) -> set[tuple[int, int]]:
    """Найти следующие service-mode callbacks, записанные в DS:$3090.

    IRQ `$02FD` вызывает слово `$3090`. Каждый экран диагностики переводит
    автомат в следующее состояние буквальной записью `MOV word [$3090],imm`.
    Эти ребра являются control-flow, хотя машинно представлены как data write.
    """
    result: set[tuple[int, int]] = set()
    for address in sorted(analysis.instructions):
        insn = analysis._one(address)
        if insn is None or insn.mnemonic != "mov" or len(insn.operands) != 2:
            continue
        destination, source = insn.operands
        if (destination.type != X86_OP_MEM or source.type != X86_OP_IMM or
                destination.mem.base != 0 or destination.mem.index != 0 or
                (destination.mem.disp & 0xFFFF) != 0x3090):
            continue
        target = source.imm & 0xFFFF
        if 0 < target < analysis.logical_size:
            result.add((address, target))
    return result


def expand_boot39_state_graph(image: bytes) -> tuple[RecursiveV30,
                                                      set[tuple[int, int]],
                                                      set[int]]:
    """Замкнуть service-mode CFG по таблице `$EB07` и state word `$3090`."""
    table_entries = set(_es_words(image, 0xEB07, 5))
    if table_entries != BOOT39_INDIRECT_ENTRIES - {0x02FD}:
        raise ValueError("изменена service-mode dispatch table ES:$EB07")
    seeds = {0, 0x02FD} | table_entries
    all_edges: set[tuple[int, int]] = set()
    while True:
        analysis = RecursiveV30(image, 0x39000, 0x7000, seeds, seeds)
        analysis.run()
        edges = discover_boot39_state_entries(image, analysis)
        all_edges |= edges
        new_targets = {target for _source, target in edges} - seeds
        if not new_targets:
            return analysis, all_edges, seeds
        seeds |= new_targets


def _es_words(main: bytes, start: int, count: int) -> tuple[int, ...]:
    """Прочитать little-endian words из доказанного ES=$1000 ROM bank."""
    base = 0x10000 + start
    return tuple(int.from_bytes(main[base + index * 2:base + index * 2 + 2],
                                "little")
                 for index in range(count))


def irq_vector_entries(main: bytes) -> tuple[dict[int, int], list[str]]:
    """IRQ-входы runtime по ROM: база векторов из ICW2 reset-кода и таблица векторов ROM.

    MAME write-tap сообщает IP уже после однобайтного `PUSH`, поэтому trace seeds давали
    `$00FF` и `$02F1` вместо настоящих входов `$00FE` и `$02EE`.
    """
    errors = []
    if (main[0x3F806:0x3F80B] != bytes.fromhex("b81700e740") or
            main[0x3F80B:0x3F810] != bytes.fromhex("b82000e742") or
            main[0x3F810:0x3F815] != bytes.fromhex("b80f00e742")):
        errors.append("reset `$3F00:$0806…$0813` больше не задаёт ICW1/ICW2/ICW4 `$17/$20/$0F`")
    entries = {}
    for irq in range(8):
        linear = (PIC_VECTOR_BASE + irq) * 4
        ip = int.from_bytes(main[linear:linear + 2], "little")
        cs = int.from_bytes(main[linear + 2:linear + 4], "little")
        if cs != 0x0040:
            errors.append(f"вектор IRQ{irq} указывает не в runtime CS=$0040")
            continue
        entries[irq] = ip
    if entries != IRQ_VECTOR_ENTRIES:
        errors.append("таблица векторов IRQ ROM `$00080…$0009F` изменилась")
    return entries, errors


def _writes_register(item: "Instruction", register: str) -> bool:
    """Инструкция может записать CX или DX (16-битный регистр целиком или байт)."""
    parts = {"cx": ("cx", "cl", "ch"), "dx": ("dx", "dl", "dh")}[register]
    operands = [part.strip() for part in item.operands.split(",")] if item.operands else []
    mnemonic = item.mnemonic
    if mnemonic in ("cmp", "test", "push", "out", "jmp", "call", "ret", "iret") or mnemonic.startswith("j"):
        return False
    if register == "cx" and (mnemonic.startswith("loop") or mnemonic.startswith("rep") or
                             item.raw.startswith(("f2", "f3"))):
        return True
    if register == "dx" and mnemonic in ("mul", "imul", "div", "idiv", "cwd"):
        return True
    if mnemonic in ("popaw", "popa"):
        return True
    if mnemonic == "xchg":
        return any(operand in parts for operand in operands)
    return bool(operands) and operands[0] in parts


def task_queue_producers(runtime: "RecursiveV30") -> tuple[dict[int, list[int]], list[int]]:
    """Значения CX во всех достигнутых вызовах `$0384` обратным разбором путей.

    `MOV CX,imm` даёт handler; `MOV CX,DX` переносит поиск на запись DX (`MOV DX,imm`).
    Другая запись регистра, CALL на пути или начало функции без записи делают место
    вызова нерешённым (второй результат).
    """
    instructions = runtime.instructions
    predecessors: dict[int, set[int]] = collections.defaultdict(set)
    for address, item in instructions.items():
        stop = (item.mnemonic.startswith("ret") or item.mnemonic in ("iret", "hlt", "jmp", "ljmp"))
        if not stop:
            predecessors[address + item.size].add(address)
    for source, target in runtime.jumps:
        predecessors[target].add(source)
    producers: dict[int, list[int]] = {}
    unresolved: list[int] = []
    for source, target in sorted(runtime.calls):
        if target != TASK_QUEUE_ALLOCATOR:
            continue
        values: set[int] = set()
        resolved = True
        pending = [(source, "cx")]
        seen = set()
        while pending:
            address, register = pending.pop()
            previous_set = predecessors.get(address, set())
            if not previous_set or (address != source and address in runtime.function_entries):
                resolved = False
                continue
            for previous in previous_set:
                if (previous, register) in seen:
                    continue
                seen.add((previous, register))
                item = instructions[previous]
                operands = [part.strip() for part in item.operands.split(",")] if item.operands else []
                if item.mnemonic in ("call", "lcall"):
                    resolved = False
                    continue
                if not _writes_register(item, register):
                    pending.append((previous, register))
                    continue
                if item.mnemonic == "mov" and operands[0] == register and operands[1].startswith("0x"):
                    values.add(int(operands[1], 16) & 0xFFFF)
                elif item.mnemonic == "mov" and register == "cx" and operands == ["cx", "dx"]:
                    pending.append((previous, "dx"))
                else:
                    resolved = False
        if resolved:
            producers[source] = sorted(values)
        else:
            unresolved.append(source)
    return producers, unresolved


def discover_v30_indirect_edges(main: bytes) -> tuple[set[int],
                                                        list[dict[str, object]]]:
    """Разрешить все девять форм косвенного CALL/JMP runtime V30.

    `$00D3` и три `$FF [BP]` dispatcher читают handler words из RAM, однако
    множество значений задаётся ROM-таблицами/allocator producers ниже.
    `$00F6`, `$1BC6`, `$257F/$2612` и `$3957` имеют отдельные доказанные
    таблицы. Возвращаем как seeds, так и полный machine-readable edge list.
    """
    initial_objects = _es_words(main, 0x081A, 40)
    stage_handlers = _es_words(main, 0xB92D, 50)
    force_handlers = _es_words(main, 0x1430, 4)
    weapon_handlers = _es_words(main, 0x1B80, 0x480 // 2)
    flyer_a_handlers = set(_es_words(main, 0x34B6, 11 * 2)[::2])
    flyer_b_handlers = set(_es_words(main, 0x34E2, 17 * 2)[::2])
    multipart_handlers = set(_es_words(main, 0x40C6, 22 * 2)[::2])
    # 40-я pair `$8000,$FFF2` — sentinel, callback не исполняется.
    final_callbacks = set(_es_words(main, 0x6416, 39 * 2)[1::2])
    final_spawn_handlers = set(
        int.from_bytes(main[0x10000 + address + 6:
                            0x10000 + address + 8], "little")
        for address in range(0x6CE0, 0x6F88, 10))
    stage6_ring_handlers = {
        int.from_bytes(main[0x10000 + address:
                            0x10000 + address + 2], "little")
        for start in (0x411E, 0x414E)
        for address in range(start, start + 8 * 6, 6)
    }
    random_bullet_handlers = set(_es_words(main, 0x612C, 32))
    final_child_handlers = {0xC9A0, 0xC9AC, 0xC9B8, 0xC9C4}
    dobker_spawn_handlers = tuple(sorted(set(
        _es_words(main, 0x454E + 4, 1) +
        tuple(int.from_bytes(main[0x10000 + address + 4:
                                  0x10000 + address + 6], "little")
              for address in range(0x4554, 0x46C2, 6))
    )))

    # Точные structural invariants таблиц; это защищает от тихого смещения
    # границы в data или принятия случайного word за handler.
    if initial_objects[:10] != (
            0x1FC0, 0x2430, 0x249A, 0x3067, 0x3304,
            0x3364, 0x30FF, 0x32FB, 0x2CE5, 0x2EA6):
        raise ValueError("изменена таблица initial object handlers ES:$081A")
    if len(set(stage_handlers)) != 48 or stage_handlers.count(0x0800) != 3:
        raise ValueError("stage handler table ES:$B92D не содержит 50 opcodes")
    if force_handlers != (0x2682, 0x26AD, 0x26D0, 0x26E9):
        raise ValueError("изменена Force dispatch table ES:$1430")
    if len(set(weapon_handlers)) != 69 or weapon_handlers.count(0x3959) != 384:
        raise ValueError("изменена player-weapon dispatch matrix ES:$1B80..$1FFF")
    if dobker_spawn_handlers != (0xE700, 0xE7B6, 0xE7BE, 0xE817):
        raise ValueError("изменены Dobkeratops spawn handlers ES:$454E..$46C1")
    if flyer_a_handlers != {0x799C, 0x7A1E, 0x7AD9}:
        raise ValueError("изменён spawn script ES:$34B6")
    if flyer_b_handlers != {0x799C, 0x7A1E, 0x7AD9}:
        raise ValueError("изменён spawn script ES:$34E2")
    if multipart_handlers != {0x9246, 0x92C3, 0x933C, 0x9477, 0x94E1}:
        raise ValueError("изменён multipart spawn script ES:$40C6")
    if len(final_callbacks) != 16 or 0xFFF2 in final_callbacks:
        raise ValueError("изменён final-stage callback script ES:$6416")
    if len(final_spawn_handlers) != 49:
        raise ValueError("изменён final-stage spawn script ES:$6CE0..$6F87")
    if stage6_ring_handlers != {0x95F1}:
        raise ValueError("изменены spawn records ES:$411E/$414E")
    if len(random_bullet_handlers) != 11:
        raise ValueError("изменена random handler table ES:$612C")

    edges: list[dict[str, object]] = []

    def add(source: int, targets, kind: str, table: str) -> None:
        for target in sorted(set(targets)):
            edges.append({"source": source, "target": target,
                          "kind": kind, "table": table})

    add(0x00D3, (0x55E8,), "ram-handler-call", "DS:$3060")
    # `$0244` вызывает директор DS:$0000; `$0259/$0267` — fixed и linked
    # object records. Их полный target union задают initial table, allocator
    # producers, state writes и два linked-list bootstrap handlers.
    add(0x00F6, TASK_QUEUE_TARGETS, "task-ring-call", "DS:$1E20 ring")
    for source in (0x1BC6, 0xFB06):
        add(source, stage_handlers, "stage-event-call", "ES:$B92D[50]")
    add(0x257F, force_handlers, "force-state-jump", "ES:$1430[4]")
    add(0x2612, force_handlers, "force-state-jump", "ES:$1430[4]")
    add(0x3957, weapon_handlers, "weapon-matrix-jump",
        "ES:$1B80..$1FFF, 48x12 words")
    for source, target in sorted(ALLOCATOR_IMMEDIATE_TARGET_BY_SITE.items()):
        add(source, (target,), "allocator-handler", "DX before CALL $03A6")
    add(0x9D5F, dobker_spawn_handlers, "allocator-handler",
        "ES:$454E..$46C1 record +4")
    add(0x794E, flyer_a_handlers | flyer_b_handlers, "allocator-handler",
        "ES:$34B6/$34E2 records: handler,delay")
    add(0x91E5, multipart_handlers, "allocator-handler",
        "ES:$40C6 records: handler,delay")
    add(0xC637, final_spawn_handlers, "allocator-handler",
        "ES:$6CE0..$6F87 68 records, handler at +6")
    add(0xC0DC, final_callbacks, "final-stage-script-call",
        "ES:$6416..$64B5 threshold,callback records")
    add(0x95BB, stage6_ring_handlers, "allocator-handler",
        "ES:$411E/$414E, 8 records x 6 bytes")
    add(0xBAEE, random_bullet_handlers, "allocator-handler",
        "ES:$612C[32], RNG index")
    add(0xDA10, final_child_handlers, "allocator-handler",
        "object+$22 set by `$D8B7/$D8C4/$D8D1/$D8DE`")

    object_targets = (set(initial_objects) | set(force_handlers) |
                      set(ALLOCATOR_IMMEDIATE_TARGET_BY_SITE.values()) |
                      set(dobker_spawn_handlers) | flyer_a_handlers |
                      flyer_b_handlers | multipart_handlers |
                      final_spawn_handlers | stage6_ring_handlers |
                      random_bullet_handlers | final_child_handlers |
                      {0x06A0, 0x1BA6, 0x1BA7})
    for source in (0x0244, 0x0259, 0x0267):
        add(source, object_targets, "ram-object-handler-call",
            "initial/allocator/state handler union")

    targets = {item["target"] for item in edges}
    return targets, sorted(edges, key=lambda item: (
        item["source"], item["target"], item["kind"]))


class RecursiveZ80:
    """Точный по длинам и прямому control-flow обход загруженного Z80 image."""

    _IMM16 = frozenset((
        0x01, 0x11, 0x21, 0x22, 0x2A, 0x31, 0x32, 0x3A,
        0xC2, 0xC3, 0xC4, 0xCA, 0xCC, 0xCD, 0xD2, 0xD4, 0xDA, 0xDC,
        0xE2, 0xE4, 0xEA, 0xEC, 0xF2, 0xF4, 0xFA, 0xFC,
    ))
    _IMM8 = frozenset((
        0x06, 0x0E, 0x10, 0x16, 0x18, 0x1E, 0x20, 0x26, 0x28, 0x2E,
        0x30, 0x36, 0x38, 0x3E, 0xC6, 0xCE, 0xD3, 0xD6, 0xDB, 0xDE,
        0xE6, 0xEE, 0xF6, 0xFE,
    ))
    _INDEX_DISP = frozenset((
        0x34, 0x35, 0x36, 0x46, 0x4E, 0x56, 0x5E, 0x66, 0x6E, 0x70,
        0x71, 0x72, 0x73, 0x74, 0x75, 0x77, 0x7E, 0x86, 0x8E, 0x96,
        0x9E, 0xA6, 0xAE, 0xB6, 0xBE,
    ))
    _ED_IMM16 = frozenset((0x43, 0x4B, 0x53, 0x5B, 0x63, 0x6B,
                           0x73, 0x7B))
    _JP_CC = frozenset((0xC2, 0xCA, 0xD2, 0xDA, 0xE2, 0xEA, 0xF2, 0xFA))
    _CALL_CC = frozenset((0xC4, 0xCC, 0xD4, 0xDC, 0xE4, 0xEC, 0xF4, 0xFC))
    _RET_CC = frozenset((0xC0, 0xC8, 0xD0, 0xD8, 0xE0, 0xE8, 0xF0, 0xF8))
    _JR_CC = frozenset((0x10, 0x20, 0x28, 0x30, 0x38))

    def __init__(self, image: bytes, seeds: set[int]) -> None:
        self.image = image
        self.seeds = set(seeds)
        self.instructions: dict[int, Z80Instruction] = {}
        self.owners: dict[int, int] = {}
        self.calls: set[tuple[int, int]] = set()
        self.jumps: set[tuple[int, int]] = set()
        self.indirect: set[int] = set()
        self.invalid: set[int] = set()
        self.conflicts: set[tuple[int, int, int]] = set()

    def _decode(self, pc: int) -> Z80Instruction | None:
        if not 0 <= pc < len(self.image):
            return None
        cursor = pc
        prefixes = 0
        indexed = False
        while cursor < len(self.image) and self.image[cursor] in (0xDD, 0xFD):
            indexed = True
            prefixes += 1
            cursor += 1
        if cursor >= len(self.image):
            return None
        opcode = self.image[cursor]
        if opcode == 0xCB:
            size = prefixes + (3 if indexed else 2)
        elif opcode == 0xED:
            if cursor + 1 >= len(self.image):
                return None
            size = prefixes + (4 if self.image[cursor + 1] in self._ED_IMM16 else 2)
        else:
            size = prefixes + (3 if opcode in self._IMM16 else
                               2 if opcode in self._IMM8 else 1)
            if indexed and opcode in self._INDEX_DISP:
                size += 1
        if pc + size > len(self.image):
            return None

        flow = "next"
        target = None
        operand = cursor + 1
        if opcode == 0xCD or opcode in self._CALL_CC:
            flow = "call" if opcode == 0xCD else "call-conditional"
            target = int.from_bytes(self.image[operand:operand + 2], "little")
        elif opcode == 0xC3 or opcode in self._JP_CC:
            flow = "jump" if opcode == 0xC3 else "jump-conditional"
            target = int.from_bytes(self.image[operand:operand + 2], "little")
        elif opcode == 0x18 or opcode in self._JR_CC:
            displacement = self.image[operand]
            if displacement & 0x80:
                displacement -= 0x100
            flow = "jump" if opcode == 0x18 else "jump-conditional"
            target = (pc + size + displacement) & 0xFFFF
        elif opcode & 0xC7 == 0xC7:
            flow = "call"
            target = opcode & 0x38
        elif opcode in self._RET_CC:
            flow = "return-conditional"
        elif opcode in (0xC9, 0x76):
            flow = "return" if opcode == 0xC9 else "halt"
        elif opcode == 0xE9:
            flow = "jump-indirect"
        elif opcode == 0xED and self.image[cursor + 1] in (0x45, 0x4D):
            flow = "return"
        raw = self.image[pc:pc + size].hex(" ")
        return Z80Instruction(pc, size, raw, flow, target)

    def run(self) -> None:
        queue = collections.deque(sorted(self.seeds))
        queued = set(queue)
        while queue:
            pc = queue.popleft()
            while 0 <= pc < len(self.image):
                if pc in self.instructions:
                    break
                item = self._decode(pc)
                if item is None:
                    self.invalid.add(pc)
                    break
                self.instructions[pc] = item
                for address in range(pc, pc + item.size):
                    previous = self.owners.setdefault(address, pc)
                    if previous != pc:
                        self.conflicts.add((address, previous, pc))
                if item.target is not None:
                    if item.flow.startswith("call"):
                        self.calls.add((pc, item.target))
                    else:
                        self.jumps.add((pc, item.target))
                    if item.target not in queued:
                        queued.add(item.target)
                        queue.append(item.target)
                if item.flow == "jump-indirect":
                    self.indirect.add(pc)
                    break
                if item.flow in ("return", "halt", "jump"):
                    break
                pc += item.size

    def listing(self) -> list[dict[str, object]]:
        return [asdict(self.instructions[address])
                for address in sorted(self.instructions)]


def contiguous_runs(mask: list[str]) -> list[tuple[int, int, str]]:
    if not mask:
        return []
    result = []
    start = 0
    value = mask[0]
    for index, current in enumerate(mask[1:], 1):
        if current != value:
            result.append((start, index - 1, value))
            start, value = index, current
    result.append((start, len(mask) - 1, value))
    return result


def extract_documented_addresses() -> list[int]:
    text = OLD_MAP.read_text(encoding="utf-8")
    return sorted({int(value, 16) for value in
                   re.findall(r"\$([0-9A-Fa-f]{4})\b", text)})


def extract_documented_contexts() -> dict[int, list[str]]:
    """Связать каждый адрес из ручной semantic map с её заголовками.

    Это индекс происхождения, а не автоматическая попытка угадать имя функции.
    Один адрес может встречаться в нескольких исследованных подсистемах.
    """
    result: dict[int, set[str]] = collections.defaultdict(set)
    heading = "введение / общая карта"
    for line in OLD_MAP.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            heading = line.lstrip("#").strip()
        for value in re.findall(r"\$([0-9A-Fa-f]{4})\b", line):
            result[int(value, 16)].add(heading)
    return {address: sorted(values) for address, values in sorted(result.items())}


def extract_semantic_queue() -> list[str]:
    """Прочитать незакрытые пункты из ручной ROM-карты.

    Само наличие раздела допустимо во время исследования, но каждый его
    непустой bullet делает строгую автопроверку красной. Так генератор не может
    подменить полную семантику одним лишь классифицированным byte coverage.
    """
    result = []
    in_queue = False
    for line_number, line in enumerate(
            OLD_MAP.read_text(encoding="utf-8").splitlines(), 1):
        if line.startswith("## "):
            in_queue = line.strip() == "## Очередь дальнейшей расшифровки"
            continue
        if in_queue and line.startswith("- "):
            result.append(f"{OLD_MAP.name}:{line_number}: {line[2:].strip()}")
    return result


def sound_upload_image(main: bytes) -> bytes:
    """Воспроизвести цикл `$0040:$0026`: copy byte, затем skip duplicate."""
    source = main[0x20000:0x30000]
    if len(source) != 0x10000:
        raise ValueError("неверный размер interleaved sound source")
    return source[::2]


def _bytewise_add_word(value: int, delta: int) -> int:
    """Повторить `$A023/$A025`: сложение половин word без переноса."""
    return ((((value >> 8) + (delta >> 8)) & 0xFF) << 8) | (
        ((value & 0xFF) + (delta & 0xFF)) & 0xFF)


def verify_boss_terrain_paths(main: bytes) -> tuple[dict[str, object], list[str]]:
    """Сверить четыре ROM-пути очистки арены с независимой MAME PC trace."""
    errors = []
    if not BOSS_TERRAIN_TRACE.is_file():
        return ({"trace_present": False, "validated_writes": 0},
                ["отсутствует boss terrain PC trace"])

    rows: list[tuple[int, int]] = []
    with BOSS_TERRAIN_TRACE.open("r", encoding="ascii") as source:
        header = source.readline().rstrip().split(",")
        columns = {name: index for index, name in enumerate(header)}
        for line in source:
            fields = line.rstrip().split(",")
            if fields[columns["pc"]] != "0A010":
                continue
            rows.append((int(fields[columns["frame"]]),
                         int(fields[columns["address"]], 16) & 0x3FFF))

    groups: dict[int, list[int]] = collections.OrderedDict()
    for frame, address in rows:
        groups.setdefault(frame, []).append(address)
    early = [(frame, addresses[0]) for frame, addresses in groups.items()
             if frame < 9000]
    late = [(frame, addresses) for frame, addresses in groups.items()
            if frame >= 9000]
    streams = {
        0x47C6: early,
        0x482E: [(frame, addresses[0]) for frame, addresses in late][
            :BOSS_TERRAIN_PATHS[0x482E]],
        0x4754: [(frame, addresses[1]) for frame, addresses in late
                 if len(addresses) >= 3],
        0x46CC: [(frame, addresses[-1]) for frame, addresses in late],
    }
    path_report = {}
    for path, expected_count in BOSS_TERRAIN_PATHS.items():
        stream = streams[path]
        if len(stream) != expected_count:
            errors.append(
                f"boss terrain path `${path:04X}`: trace writes "
                f"{len(stream)} вместо {expected_count}")
            continue
        if any(right[0] - left[0] != 2
               for left, right in zip(stream, stream[1:])):
            errors.append(f"boss terrain path `${path:04X}`: VBlank step не 2")
        for index, ((_frame, address), (_next_frame, next_address)) in enumerate(
                zip(stream, stream[1:])):
            offset = 0x10000 + path + index * 2
            delta = int.from_bytes(main[offset:offset + 2], "little")
            if _bytewise_add_word(address, delta) != next_address:
                errors.append(
                    f"boss terrain path `${path:04X}`: mismatch step {index}")
                break
        sentinel_offset = 0x10000 + path + (expected_count - 1) * 2
        sentinel = int.from_bytes(main[sentinel_offset:sentinel_offset + 2],
                                  "little")
        if sentinel != 0x8000:
            errors.append(f"boss terrain path `${path:04X}`: нет sentinel `$8000`")
        path_report[f"{path:04X}"] = {
            "write_count": len(stream),
            "first_frame": stream[0][0],
            "last_frame": stream[-1][0],
            "first_vram_offset": stream[0][1],
            "last_vram_offset": stream[-1][1],
            "sentinel": sentinel,
        }
    return ({
        "trace_present": True,
        "trace": str(BOSS_TERRAIN_TRACE.relative_to(ROOT)),
        "pc": 0xA010,
        "validated_writes": len(rows),
        "paths": path_report,
    }, errors)


def sound_disassembly(image: bytes) -> tuple[str, int]:
    """Получить линейный Z80 listing официальным MAME unidasm.

    Listing намеренно называется линейным: в областях таблиц байты могут
    выглядеть как инструкции. Граница `$5780` — последний не-`$FF` byte
    загружаемого sound image, а не заявление, что всё до неё является кодом.
    """
    if not UNIDASM.is_file():
        raise FileNotFoundError(f"MAME unidasm отсутствует: {UNIDASM}")
    last = max((index for index, value in enumerate(image) if value != 0xFF),
               default=-1)
    SOUND_PATH.parent.mkdir(parents=True, exist_ok=True)
    SOUND_PATH.write_bytes(image)
    process = subprocess.run(
        [str(UNIDASM), str(SOUND_PATH), "-arch", "z80",
         "-count", str(last + 1), "-upper"],
        cwd=ROOT, check=False, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    if process.returncode:
        raise RuntimeError(f"unidasm завершился с кодом {process.returncode}: "
                           f"{process.stderr.strip()}")
    return process.stdout.rstrip(), last


def dynamic_pc_seeds() -> tuple[set[int], list[dict[str, object]]]:
    """Прочитать runtime IP из сохранённых MAME traces.

    MAME CSV исторически сохраняет только `IP`, без `CS`. До Stage 1 одинаковый
    offset относится к reset `CS=$3F00` и не может быть seed основного runtime.
    Поэтому используются только кадры Stage 1 (`>=898`) и исключается Lua
    invincibility-write `$42FC6`: его `pc` — место остановки CPU, не writer.
    """
    result: set[int] = set()
    sources = []
    for path in TRACE_FILES:
        if not path.is_file():
            sources.append({"path": str(path), "present": False, "pcs": 0})
            continue
        before = len(result)
        with path.open("r", encoding="ascii", errors="strict") as source:
            header = source.readline().rstrip("\r\n").split(",")
            if "pc" not in header:
                raise ValueError(f"trace без PC column: {path}")
            column = header.index("pc")
            frame_column = header.index("frame")
            address_column = header.index("address") if "address" in header else None
            for line in source:
                fields = line.rstrip("\r\n").split(",")
                if len(fields) <= column:
                    continue
                if int(fields[frame_column]) < 898:
                    continue
                if (address_column is not None and
                        int(fields[address_column], 16) == 0x42FC6):
                    continue
                result.add(int(fields[column], 16) & 0xFFFF)
        sources.append({"path": str(path.relative_to(ROOT)), "present": True,
                        "size": path.stat().st_size,
                        "new_pcs": len(result) - before,
                        "total_pcs": len(result)})
    return result, sources


def normalize_dynamic_pc_boundaries(image: bytes, pcs: set[int]) -> set[int]:
    """Удалить trace IP, попавшие внутрь инструкции с меньшим IP.

    MAME write taps у V30 string/bit операций могут вернуть несколько
    соседних IP. Сортированный однопроходный decode сохраняет настоящие
    последовательные boundaries, но отбрасывает bytes внутри уже принятой
    инструкции.
    """
    decoder = RecursiveV30(image, 0x400, 0x10000, set())
    covered: set[int] = set()
    result = set()
    for pc in sorted(pcs):
        if pc in covered:
            continue
        physical = 0x400 + pc
        if image[physical:physical + 2] == b"\x0f\x20":
            size = 2
        else:
            insn = decoder._one(pc)
            if insn is None:
                continue
            size = insn.size
        result.add(pc)
        covered.update(range(pc + 1, pc + size))
    return result


def main_ranges() -> list[Range]:
    return [
        Range(0x00000, 0x003FF, "main-low",
              "низ ROM перед runtime CS:$0040; vectors/служебные bytes",
              "физическое размещение ROM + сегментация V30"),
        Range(0x00400, 0x103FF, "main-cs",
              "runtime V30 CS=$0040, logical $0000..$FFFF",
              "far jump bootstrap `$0040:$0000` и прямые runtime traces"),
        Range(0x10000, 0x1FFFF, "world-es",
              "World/data segment ES=$1000, logical $0000..$FFFF",
              "segment overrides `26` и ROM table references"),
        Range(0x20000, 0x2AFFF, "sound-upload-source",
              "duplicated-byte source sound image `$0000..$57FF`; V30 copies every even byte into shared sound RAM",
              "literal startup loop `$0040:$0015..$0030` + equality of every byte pair"),
        Range(0x2B000, 0x2FFFF, "erased-ff",
              "sound image `$5800..$7FFF` после deinterleave: erased `$FF`",
              "побайтовая проверка + startup copy stride 2"),
        Range(0x30000, 0x38FFF, "world-metatiles",
              "256 metatile records ×144 bytes; 48 cells `(tile code word, attribute byte)`",
              "`$EA95/$EB02->$EB20/$EB4B/$EB86/$EBBB`, точная формула `physical=$30000+index*144`"),
        Range(0x39000, 0x3963C, "service-diagnostic-code",
              "service-mode V30: RAM/VRAM/palette/sprite/input/sound diagnostics, CS=$3900",
              "reset far jump + direct and table-resolved control-flow"),
        Range(0x3963D, 0x3F7FF, "rom-selftest-padding",
              "неисполняемое checksum/padding наполнение второго bank",
              "границы достигнутого service code + reset checksum"),
        Range(0x3F800, 0x3FC39, "reset-post-code",
              "reset/POST V30, entry CS=$3F00:$0800",
              "reset vector + recursive disassembly"),
        Range(0x3FC3A, 0x3FFEF, "reset-post-data-padding",
              "локальные POST bytes/padding вне достигнутых инструкций",
              "code ownership + checksum path"),
        Range(0x3FFF0, 0x3FFFD, "reset-vector-window",
              "16-byte reset window; far vector находится по `$3FFF0`",
              "MAME reset fetch + ROM_RELOAD"),
        Range(0x3FFFE, 0x3FFFF, "rom-checksum-word",
              "корректирующее word полного 256 KiB checksum",
              "`$3F00:$087B..$088F` исключает эти bytes из суммы и добавляет word"),
    ]


def classify_unique_main(image: bytes, main_code: RecursiveV30,
                         boot39: RecursiveV30, boot3f: RecursiveV30) -> list[str]:
    labels = ["unclassified"] * 0x40000
    for item in main_ranges():
        for address in range(item.start, item.end + 1):
            if labels[address] == "unclassified":
                labels[address] = item.kind
            elif item.kind == "world-es":
                labels[address] += "+world-es"
    for logical, insn in main_code.instructions.items():
        for address in range(0x400 + logical,
                             min(0x40000, 0x400 + logical + insn.size)):
            labels[address] = "v30-code-main"
    for analysis, base, name in ((boot39, 0x39000, "v30-code-bootstrap3900"),
                                 (boot3f, 0x3F000, "v30-code-reset3f00")):
        for logical, insn in analysis.instructions.items():
            for address in range(base + logical,
                                 min(0x40000, base + logical + insn.size)):
                labels[address] = name
    return labels


def verify_coverage(labels: list[str], regions: dict[str, bytes]) -> list[str]:
    errors = []
    if len(labels) != 0x40000 or any(value == "unclassified" for value in labels):
        errors.append("unique maincpu `$00000..$3FFFF` покрыт не полностью")
    if regions["maincpu"][0x20000:0x40000] != regions["maincpu"][0xE0000:0x100000]:
        errors.append("reset ROM_RELOAD `$E0000..$FFFFF` не совпадает с bank 1")
    if any(value != 0xFF for value in regions["maincpu"][0x2B000:0x30000]):
        errors.append("ожидаемый erased range `$2B000..$2FFFF` не равен `$FF`")
    sound_source = regions["maincpu"][0x20000:0x30000]
    if any(sound_source[index] != sound_source[index + 1]
           for index in range(0, len(sound_source), 2)):
        errors.append("sound source `$20000..$2FFFF` не состоит из равных byte pairs")
    sound = sound_upload_image(regions["maincpu"])
    if any(value != 0xFF for value in sound[0x5781:]):
        errors.append("sound image после `$5780` не является erased `$FF`")
    if (sum(regions["maincpu"][:0x3FFFE]) +
            int.from_bytes(regions["maincpu"][0x3FFFE:0x40000], "little")) & 0xFFFF:
        errors.append("полный ROM checksum reset POST не равен нулю")
    if len(regions["tiles0"]) != 0x20000 or len(regions["tiles1"]) != 0x20000:
        errors.append("неверный размер tile region")
    if len(regions["sprites"]) != 0x80000:
        errors.append("неверный размер sprite region")
    for start in (0x10000, 0x30000, 0x50000, 0x70000):
        if regions["sprites"][start:start + 0x8000] != regions["sprites"][start + 0x8000:start + 0x10000]:
            errors.append(f"sprite ROM_RELOAD `{start:05X}` не совпадает")
    return errors


def build_report() -> dict[str, object]:
    require_verified()
    regions = assemble_regions()
    main = regions["maincpu"]
    documented = extract_documented_addresses()
    documented_contexts = extract_documented_contexts()
    # `RTYPE_WORLD_ALL_STAGE_EVENTS.md` также является generated semantic MD:
    # его 48 именованных handlers не должны считаться безымянными лишь потому,
    # что литерал находится в отдельном полном all-stage документе.
    for address, meaning in HANDLER_NAMES.items():
        contexts = documented_contexts.setdefault(address, [])
        context = f"all-stage event handler: {meaning}"
        if context not in contexts:
            contexts.append(context)
            contexts.sort()
    semantic_queue = extract_semantic_queue()
    dynamic_pcs, trace_sources = dynamic_pc_seeds()
    dynamic_pcs = normalize_dynamic_pc_boundaries(main, dynamic_pcs)
    sound = sound_upload_image(main)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    MAIN_PATH.write_bytes(main[:0x40000])
    sound_listing, sound_last = sound_disassembly(sound)
    sound_runtime = RecursiveZ80(sound + bytes(0x8000),
                                 {0x0000, 0x0008, 0x0010, 0x0018,
                                  0x0020, 0x0028, 0x0030, 0x0038} |
                                 SOUND_INDIRECT_ENTRIES)
    sound_runtime.run()
    sound_labels = []
    for address in range(0x8000):
        if address in sound_runtime.owners:
            sound_labels.append("z80-code")
        elif address <= 0x0E0E:
            sound_labels.append("z80-inline-data")
        elif 0x1000 <= address <= sound_last:
            sound_labels.append("ym2151-music-sfx-data")
        else:
            sound_labels.append("erased-ff")
    stage_events_markdown, stage_event_count = build_stage_events_markdown(main)
    boss_terrain, boss_terrain_errors = verify_boss_terrain_paths(main)
    indirect_targets, indirect_edges = discover_v30_indirect_edges(main)
    irq_entries, irq_errors = irq_vector_entries(main)

    # Main runtime: proven far target `$0040:$0000`. Existing semantic map
    # provides additional proven entries (handlers/tables are filtered later
    # by successful decode); this expands indirect-dispatch coverage without
    # guessing from every word-shaped value in data.
    function_seeds = {address for address in KNOWN_CODE_ENTRIES
                      if address in documented and
                      main[0x400 + address] not in (0x00, 0xFF)}
    function_seeds |= indirect_targets
    # Входы IRQ из таблицы векторов ROM (включая заглушки неиспользуемых линий).
    function_seeds |= set(irq_entries.values())
    # Сначала строится граф от смысловых entry. Write-tap MAME может сработать
    # внутри одной V30 string/bit instruction и сообщить текущий IP уже после
    # первого opcode byte. Такой IP является runtime evidence выполнения, но
    # не новым instruction boundary. Отбрасываем лишь доказанные interior PC.
    base_runtime, _base_state_edges, function_seeds = expand_v30_state_graph(
        main, 0x400, 0x10000, function_seeds)
    boundary_pcs = {pc for pc in dynamic_pcs
                    if pc not in base_runtime.owners or
                    base_runtime.owners[pc] == pc}
    while True:
        traversal_seeds = function_seeds | boundary_pcs
        runtime, state_handler_edges, expanded_function_seeds = (
            expand_v30_state_graph(main, 0x400, 0x10000, traversal_seeds))
        # Реальные trace IP нужны как границы инструкций, но не являются сами
        # по себе function entry. Из расширенного набора оставляем только
        # обнаруженные state targets и исходные смысловые seeds.
        state_targets = {target for _source, target, _owner
                         in state_handler_edges}
        runtime.function_entries = function_seeds | state_targets | {
            target for _source, target in runtime.calls
        }
        interior_dynamic = set()
        for _byte, previous, current in runtime.conflicts:
            candidates = sorted({previous, current} & boundary_pcs)
            if len(candidates) > 1:
                interior_dynamic.update(candidates[1:])
            elif candidates:
                interior_dynamic.add(candidates[0])
        if not interior_dynamic:
            break
        boundary_pcs -= interior_dynamic
    # Object state writes раскрываются fixed-point обходом позднее исходных
    # ROM tables; добавляем их в точный union трёх `[BP]` dispatchers.
    generic_existing = {(item["source"], item["target"])
                        for item in indirect_edges
                        if item["kind"] == "ram-object-handler-call"}
    for source in (0x0244, 0x0259, 0x0267):
        for target in sorted(state_targets):
            if (source, target) not in generic_existing:
                indirect_edges.append({
                    "source": source, "target": target,
                    "kind": "ram-object-handler-call",
                    "table": "object+$00 state-write union",
                })
    indirect_edges.sort(key=lambda item: (item["source"], item["target"],
                                           item["kind"]))
    boot39, boot39_state_edges, boot39_state_entries = (
        expand_boot39_state_graph(main))
    # `$0040:$00B6/$00BB` делают far calls в аппаратные helpers `$0B6A`
    # и `$0C15`; reset-vector path сам по себе до них не доходит.
    boot3f = RecursiveV30(main, 0x3F000, 0x1000,
                          {0x800, 0x0B6A, 0x0C15})
    boot3f.run()
    labels = classify_unique_main(main, runtime, boot39, boot3f)
    errors = verify_coverage(labels, regions)
    errors.extend(boss_terrain_errors)
    errors.extend(irq_errors)
    task_producers, task_unresolved = task_queue_producers(runtime)
    if task_unresolved:
        errors.append("вызовы task allocator `$0384` с нерешённым CX: " +
                      ",".join(f"${site:04X}" for site in task_unresolved))
    derived_task_targets = {value for values in task_producers.values() for value in values}
    if derived_task_targets != TASK_QUEUE_TARGETS:
        errors.append("выведенные из кода task-ring handlers не совпадают с TASK_QUEUE_TARGETS: " +
                      ",".join(f"${value:04X}" for value in sorted(derived_task_targets ^ TASK_QUEUE_TARGETS)))
    sound_audit = sound_trace_audit(sound_runtime, errors)
    sound_formats = sound_data_format_map(sound, errors)
    tile_consumers = tile_graphics_consumer_map(main, errors)
    sprite_consumers = sprite_direct_descriptor_map(main, runtime, errors)
    service_data = service_world_rom_data_map(main, boot39, errors)
    reset_data = reset_world_rom_data_map(main, boot3f, runtime, errors)
    world_es_coverage = world_es_semantic_coverage(
        main, sprite_consumers, service_data, reset_data, errors)
    if any(pc not in runtime.owners for pc in dynamic_pcs):
        errors.append("не все реально исполненные runtime PC принадлежат инструкции")
    indirect_instruction_sites = {
        item.address for item in runtime.instructions.values()
        if item.mnemonic in ("call", "jmp") and
        not item.operands.startswith("0x")
    }
    if indirect_instruction_sites != {
            0x00D3, 0x00F6, 0x0244, 0x0259, 0x0267,
            0x1BC6, 0x257F, 0x2612, 0x3957, 0xC0DC, 0xFB06}:
        errors.append("набор indirect runtime V30 instructions изменился")
    allocator_sites = {source for source, target in runtime.calls
                       if target == 0x03A6}
    if allocator_sites != (set(ALLOCATOR_IMMEDIATE_TARGET_BY_SITE) |
                           {0x794E, 0x91E5, 0x95BB, 0x9D5F, 0xBAEE,
                            0xC637, 0xDA10}):
        errors.append("набор allocator `$03A6` producer sites изменился")
    unresolved_indirect_targets = {
        item["target"] for item in indirect_edges
        if item["target"] not in runtime.instructions
    }
    if unresolved_indirect_targets:
        errors.append("не все indirect V30 targets декодированы как code entries")
    if max(boot39.owners, default=-1) != 0x063C:
        errors.append("service diagnostic code boundary не равна `$3963C`")
    if max(boot3f.owners, default=-1) != 0x0C39:
        errors.append("reset/helper code boundary не равна `$3FC39`")
    if stage_event_count != 788 or len(STAGE_RANGES) != 8:
        errors.append("all-stage event map имеет неверные границы/число записей")
    if len(HANDLER_NAMES) != 48:
        errors.append("не все уникальные stage-event handlers имеют смысловое имя")
    if sound_runtime.conflicts:
        errors.append("Z80 sound recursive map имеет instruction conflicts")
    if sound_runtime.invalid:
        errors.append("Z80 sound recursive map имеет invalid direct targets")
    if sound_runtime.indirect != {0x035D, 0x03AB}:
        errors.append("набор Z80 indirect jumps не совпадает с двумя доказанными tables")
    command_table = tuple(int.from_bytes(sound[0x035E + index * 2:
                                               0x0360 + index * 2], "little")
                          for index in range(32))
    type_table = tuple(int.from_bytes(sound[0x03AC + index * 2:
                                            0x03AE + index * 2], "little")
                       for index in range(3))
    if command_table != SOUND_COMMAND_TABLE or type_table != SOUND_TYPE_TABLE:
        errors.append("Z80 indirect dispatch tables изменились или декодированы неверно")
    for name, analysis in (("runtime", runtime), ("service", boot39),
                           ("reset", boot3f)):
        if analysis.conflicts:
            errors.append(f"{name}: instruction ownership conflicts: "
                          f"{len(analysis.conflicts)}")
        unhandled_nec = [item.address for item in analysis.instructions.values()
                         if item.raw.startswith("0f ") and
                         item.mnemonic != "add4s"]
        if unhandled_nec:
            errors.append(f"{name}: необработанные NEC V30 opcodes `$0F`: "
                          f"{len(unhandled_nec)}")

    pages = []
    for start in range(0, 0x40000, 0x1000):
        page = main[start:start + 0x1000]
        kinds = collections.Counter(labels[start:start + 0x1000])
        pages.append({
            "start": start,
            "end": start + 0xFFF,
            "sha256": sha256(page),
            "entropy": round(entropy(page), 4),
            "zero_bytes": page.count(0),
            "ff_bytes": page.count(0xFF),
            "kinds": dict(sorted(kinds.items())),
        })

    raw = [{
        "name": spec.local_name,
        "size": spec.size,
        "region": spec.region,
        "sha1": spec.sha1,
        "sha256": spec.sha256,
    } for spec in ROMS]
    runtime_entries_without_context = sorted(
        entry for entry in runtime.function_entries
        if entry not in documented_contexts)
    direct_refs_without_context = sorted({
        (space, address) for _source, space, address in runtime.data_refs
        if address not in documented_contexts
    })
    # The first built-in semantic requirement is discharged only by a
    # machine-checkable contract: every explicit ES data range has an exact
    # format and a consumer list (an empty list means a proved orphan/erased
    # range), all 64 KiB are classified, and the independent sprite consumer
    # graph is complete.
    es_contract_ranges = (
        list(reset_data["ranges"]) + list(service_data["ranges"]) +
        list(sprite_consumers["producer_ranges"]) +
        list(world_es_coverage["proven_runtime_ranges"]) +
        list(world_es_coverage["interpreter_ranges"])
    )
    es_contract_metadata_complete = all(
        isinstance(item.get("format"), str) and bool(item["format"].strip()) and
        isinstance(item.get("consumers"), list)
        for item in es_contract_ranges)
    es_data_contract_complete = (
        world_es_coverage["complete"] and
        es_contract_metadata_complete and
        sprite_consumers["complete"]
    )
    builtin_gaps = list(BUILTIN_SEMANTIC_GAPS)
    if es_data_contract_complete:
        builtin_gaps.remove(
            "каждый ES data range: формат записи и полный список consumers")
    if sprite_consumers["complete"]:
        builtin_gaps.remove(
            "sprite graphics ROM: каждый code связан с descriptor/resource consumers")
    semantic_unresolved_count = (
        len(semantic_queue) + len(builtin_gaps) +
        len(runtime_entries_without_context) + len(direct_refs_without_context)
    )
    instruction_order = sorted(runtime.instructions)
    instruction_position = {address: index for index, address
                            in enumerate(instruction_order)}
    function_entry_order = sorted(runtime.function_entries)
    rng_call_sites = []
    for source, target in sorted(runtime.calls):
        if target != 0xEDE9:
            continue
        position = instruction_position[source]
        owner = max(entry for entry in function_entry_order if entry <= source)
        context_addresses = instruction_order[max(0, position - 4):
                                              position + 5]
        rng_call_sites.append({
            "source": source,
            "owner_entry": owner,
            "context": [asdict(runtime.instructions[address])
                        for address in context_addresses],
        })
    if len(rng_call_sites) != 79:
        errors.append("набор из 79 runtime callers RNG `$EDE9` изменился")
    es_access_sites = es_access_site_registry(runtime, documented_contexts)
    if len(es_access_sites) != 733:
        errors.append("набор из 733 syntactic `ES:[...]` sites изменился")
    if any(not site["owner_entries"] for site in es_access_sites):
        errors.append("не каждое ES-access site принадлежит CFG procedure")
    world_es_catalog = world_es_access_catalog(es_access_sites, errors)
    if (world_es_catalog["world_site_count"] != 620 or
            not world_es_catalog["all_sites_catalogued"]):
        errors.append("World ES catalog не покрывает точные 620 consumers")
    report = {
        "schema": 1,
        "set": "rtype / World",
        "mame_region_sha256": {name: sha256(data)
                               for name, data in regions.items()},
        "raw_roms": raw,
        "main_physical_ranges": [asdict(item) for item in main_ranges()],
        "main_class_runs": [{"start": start, "end": end, "kind": kind}
                            for start, end, kind in contiguous_runs(labels)],
        "main_pages": pages,
        "runtime_v30": {
            "segment": "CS=$0040",
            "physical_base": 0x400,
            "instruction_count": len(runtime.instructions),
            "code_bytes": len(runtime.owners),
            "function_entries": runtime.functions(),
            "direct_calls": sorted(runtime.calls),
            "direct_jumps": sorted(runtime.jumps),
            "data_refs": sorted(runtime.data_refs),
            "far_calls": sorted(runtime.far_calls),
            "far_jumps": sorted(runtime.far_jumps),
            "object_handler_edges": sorted(state_handler_edges),
            "indirect_control_flow": indirect_edges,
            "irq_vector_entries": {str(irq): ip for irq, ip in sorted(irq_entries.items())},
            "task_queue_producers": {f"{site:04X}": values for site, values in sorted(task_producers.items())},
            "rng_call_sites": rng_call_sites,
            "es_access_sites": es_access_sites,
            "world_es_access_catalog": world_es_catalog,
            "invalid_seeds": sorted(runtime.invalid),
            "ownership_conflicts": sorted(runtime.conflicts),
            "dynamic_pc_count": len(dynamic_pcs),
            "dynamic_boundary_pc_count": len(boundary_pcs),
            "trace_sources": trace_sources,
            "instructions": runtime.listing(),
        },
        "bootstrap_3900": {
            "instruction_count": len(boot39.instructions),
            "code_bytes": len(boot39.owners),
            "functions": boot39.functions(),
            "state_dispatch_entries": sorted(boot39_state_entries),
            "state_dispatch_edges": sorted(boot39_state_edges),
            "world_rom_data": service_data,
            "data_refs": sorted(boot39.data_refs),
            "instructions": boot39.listing(),
            "ownership_conflicts": sorted(boot39.conflicts),
        },
        "bootstrap_3f00": {
            "instruction_count": len(boot3f.instructions),
            "code_bytes": len(boot3f.owners),
            "functions": boot3f.functions(),
            "world_rom_data": reset_data,
            "data_refs": sorted(boot3f.data_refs),
            "instructions": boot3f.listing(),
            "ownership_conflicts": sorted(boot3f.conflicts),
        },
        "documented_logical_addresses": documented,
        "documented_contexts": {f"{address:04X}": values
                                for address, values in documented_contexts.items()},
        "world_es_semantic_coverage": world_es_coverage,
        "semantic_completion": {
            "complete": semantic_unresolved_count == 0,
            "es_data_contract_complete": es_data_contract_complete,
            "es_data_contract_range_count": len(es_contract_ranges),
            "manual_queue": semantic_queue,
            "builtin_gaps": builtin_gaps,
            "runtime_entries_without_context": runtime_entries_without_context,
            "direct_refs_without_context": direct_refs_without_context,
            "unresolved_count": semantic_unresolved_count,
        },
        "sound_z80": {
            "image_size": len(sound),
            "last_non_ff": sound_last,
            "sha256": sha256(sound),
            "linear_listing_sha256": sha256(sound_listing.encode("utf-8")),
            "linear_listing": sound_listing,
            "recursive": {
                "instruction_count": len(sound_runtime.instructions),
                "code_bytes_loaded_image": sum(
                    1 for address in sound_runtime.owners if address <= sound_last),
                "non_code_bytes_loaded_image": (sound_last + 1) - sum(
                    1 for address in sound_runtime.owners if address <= sound_last),
                "direct_calls": sorted(sound_runtime.calls),
                "direct_jumps": sorted(sound_runtime.jumps),
                "indirect_jumps": sorted(sound_runtime.indirect),
                "invalid_targets": sorted(sound_runtime.invalid),
                "ownership_conflicts": sorted(sound_runtime.conflicts),
                "instructions": sound_runtime.listing(),
                "class_runs": [
                    {"start": start, "end": end, "kind": kind}
                    for start, end, kind in contiguous_runs(sound_labels)
                ],
                "classified_bytes": len(sound_labels),
                "unclassified_bytes": sound_labels.count("unclassified"),
                "command_dispatch_table_035e": list(command_table),
                "type_dispatch_table_03ac": list(type_table),
            },
            "mame_bus_trace": sound_audit,
            "data_formats": sound_formats,
        },
        "all_stage_events": {
            "stage_count": len(STAGE_RANGES),
            "event_count": stage_event_count,
            "handler_meanings": {f"{address:04X}": meaning
                                 for address, meaning in sorted(HANDLER_NAMES.items())},
            "markdown_sha256": sha256(stage_events_markdown.encode("utf-8")),
            "markdown": stage_events_markdown,
        },
        "boss_terrain_paths": boss_terrain,
        "graphics": {
            "tiles0": {"raw_size": len(regions["tiles0"]),
                       "decoded_codes": 4096, "cell": "8x8x4bpp",
                       "consumer_map": tile_consumers["tiles0_codes"]},
            "tiles1": {"raw_size": len(regions["tiles1"]),
                       "decoded_codes": 4096, "cell": "8x8x4bpp",
                       "consumer_map": tile_consumers["tiles1_codes"]},
            "sprites": {"raw_size": len(regions["sprites"]),
                        "decoded_codes": 4096, "cell": "16x16x4bpp",
                        "consumer_map": sprite_consumers["codes"]},
            "sprite_consumers": {
                key: value for key, value in sprite_consumers.items()
                if key != "codes"
            },
            "tile_consumers": {
                key: value for key, value in tile_consumers.items()
                if key not in ("tiles0_codes", "tiles1_codes")
            },
        },
        "coverage": {
            "unique_main_bytes": len(labels),
            "unclassified_bytes": labels.count("unclassified"),
            "errors": errors,
        },
    }
    return report


def h(value: int, width: int = 5) -> str:
    return f"`${value:0{width}X}`"


def render_markdown(report: dict[str, object]) -> str:
    raw = report["raw_roms"]
    pages = report["main_pages"]
    runtime = report["runtime_v30"]
    functions = runtime["function_entries"]
    data_refs = runtime["data_refs"]
    contexts = report["documented_contexts"]
    errors = report["coverage"]["errors"]
    semantic = report["semantic_completion"]
    lines = [
        "# R-Type World: полная проверяемая карта ROM",
        "",
        "> Этот файл генерируется `Source/Tools/m72_rom_complete_map.py`.",
        "> Ручные догадки сюда не подмешиваются. Подробная доказанная семантика",
        "> процедур хранится в `RTYPE_WORLD_ROM_MAP.md`; этот документ является",
        "> полным адресным индексом и контролем отсутствия скрытых дыр.",
        "",
        "## Статус полноты",
        "",
        f"- Набор: `{report['set']}`.",
        f"- Проверено исходных ROM: **{len(raw)}/20**.",
        f"- Покрыто уникальных maincpu bytes: **{report['coverage']['unique_main_bytes']}/262144**.",
        f"- Не включено ни в один физический диапазон: **{report['coverage']['unclassified_bytes']} bytes**.",
        f"- Рекурсивно подтверждено runtime V30 instructions: **{runtime['instruction_count']}**, code bytes: **{runtime['code_bytes']}**.",
        f"- Найдено function entries: **{len(functions)}**, прямых data references: **{len(data_refs)}**.",
        f"- Реально исполненных PC из сохранённых MAME traces: **{runtime['dynamic_pc_count']}**.",
        f"- Индексировано адресов из подробной semantic map: **{len(contexts)}**.",
        f"- Автопроверка: **{'FAIL — ' + '; '.join(errors) if errors else 'OK'}**.",
        "",
        "Важно: «адрес покрыт» не означает «семантика доказана». Все интервалы",
        "общих data/padding classes ниже являются",
        "явным реестром оставшейся расшифровки, а не заявлением о завершении.",
        "",
        "## 20 физических ROM-файлов",
        "",
        "| Файл | Region | Размер | SHA-256 |",
        "|---|---:|---:|---|",
    ]
    for item in raw:
        lines.append(f"| `{item['name']}` | `{item['region']}` | {item['size']} | `{item['sha256']}` |")
    lines += [
        "",
        "Отсутствующие в переданном комплекте PROM/PLD (`m72_a-8l`,",
        "`m72_a-9l`, `m72_a-3d`, `m72_a-4d`, `m72_r-3a`) не объявляются",
        "исследованными. Они относятся к аппаратной логике платы, а не к этим",
        "20 файлам; их ожидаемые MAME SHA приведены в `m72_arcade.py`.",
        "",
        "## V30: physical program address space (20 bit)",
        "",
        "| Physical | Назначение | Источник/доказательство |",
        "|---:|---|---|",
        "| `$00000..$3FFFF` | 256 KiB уникального program ROM | четыре interleaved ROM |",
        "| `$40000..$43FFF` | work RAM, не ROM | `rtype_map` MAME |",
        "| `$C0000..$C03FF` | sprite RAM | `m72_cpu1_common_map` |",
        "| `$C8000..$C8BFF` | palette RAM layer/group 0 | `m72_cpu1_common_map` |",
        "| `$CC000..$CCBFF` | palette RAM layer/group 1 | `m72_cpu1_common_map` |",
        "| `$D0000..$D3FFF` | VRAM foreground | `m72_cpu1_common_map` |",
        "| `$D8000..$DBFFF` | VRAM background | `m72_cpu1_common_map` |",
        "| `$E0000..$EFFFF` | shared sound RAM | `m72_cpu1_common_map` |",
        "| `$FFFF0..$FFFFF` | reset-vector mirror of bank 1 | `ROM_RELOAD` + map |",
        "",
        "Незаданные MAME map интервалы читаются как open/unmapped bus и не",
        "являются скрытым ROM. Reset mirror `$E0000..$FFFFF` в собранном region",
        "равен `$20000..$3FFFF` побайтно, хотя CPU map отдельно гарантирует ROM",
        "только для reset vector `$FFFF0..$FFFFF`; `$E0000..$EFFFF` поверх него",
        "отображён как sound RAM.",
        "",
        "## Сегментные координаты V30",
        "",
        "| Координата | Physical formula | Смысл |",
        "|---|---|---|",
        "| runtime `CS=$0040:$oooo` | `$00400 + oooo` | основной код `$0000..$FFFF` |",
        "| World `ES=$1000:$oooo` | `$10000 + oooo` | таблицы, descriptors, scripts |",
        "| runtime `DS=$4000:$oooo` | `$40000 + oooo` | work RAM `$0000..$3FFF` |",
        "| POST `CS=$3900:$oooo` | `$39000 + oooo` | диагностика/поддержка bootstrap |",
        "| reset `CS=$3F00:$oooo` | `$3F000 + oooo` | reset/POST, entry `$0800` |",
        "",
        "Из-за сегментации physical `$10000..$103FF` одновременно достижим как",
        "хвост runtime CS и начало ES. Это реальное перекрытие представлений,",
        "а не ошибка карты.",
        "",
        "## Уникальный maincpu ROM: непрерывные физические классы",
        "",
        "| Physical | Класс | Текущее доказанное значение |",
        "|---:|---|---|",
    ]
    for item in report["main_physical_ranges"]:
        lines.append(f"| `{item['start']:05X}..{item['end']:05X}` | `{item['kind']}` | {item['meaning']} ({item['evidence']}) |")
    lines += [
        "",
        "## Поблочная матрица maincpu (каждый байт учтён)",
        "",
        "| Physical page | Entropy | `$00` | `$FF` | SHA-256 | Классы после code analysis |",
        "|---:|---:|---:|---:|---|---|",
    ]
    for page in pages:
        kinds = ", ".join(f"`{name}`:{count}" for name, count in page["kinds"].items())
        lines.append(f"| `{page['start']:05X}..{page['end']:05X}` | {page['entropy']:.4f} | {page['zero_bytes']} | {page['ff_bytes']} | `{page['sha256']}` | {kinds} |")
    lines += [
        "",
        "## Доказательная база runtime PC",
        "",
        "| Trace | Размер | Новых PC | Накопительно PC |",
        "|---|---:|---:|---:|",
    ]
    for source in runtime["trace_sources"]:
        if source["present"]:
            lines.append(f"| `{source['path']}` | {source['size']} | {source['new_pcs']} | {source['total_pcs']} |")
        else:
            lines.append(f"| `{source['path']}` | отсутствует | — | — |")
    lines += [
        "",
        "## Runtime V30 procedure index",
        "",
        "Это автоматический conservative index. Адрес считается entry, если он",
        "достигнут доказанным прямым `CALL/JMP`, main entry или уже описан в",
        "семантической карте и успешно декодируется. Девять форм indirect",
        "dispatch ниже разрешены только через их точные ROM tables/producers;",
        "случайные word values не объявляются кодом.",
        "",
        "| CS offset | Physical | Последний достигнутый byte до следующего entry | Instructions | Direct callees | Контекст semantic map |",
        "|---:|---:|---:|---:|---|---|",
    ]
    for function in functions:
        callees = ", ".join(f"`${value:04X}`" for value in function["direct_calls"])
        labels = "; ".join(contexts.get(f"{function['entry']:04X}", []))
        lines.append(f"| `${function['entry']:04X}` | `{function['physical']:05X}` | `${function['end']:04X}` | {function['instruction_count']} | {callees or '—'} | {labels or '—'} |")
    lines += [
        "",
        "## Runtime V30 indirect control-flow cross-reference",
        "",
        "Каждая строка — разрешённое ребро одного из девяти достигнутых",
        "косвенных `CALL/JMP`. Табличные границы и количество уникальных",
        "handlers проверяются генератором; каждый target обязан быть instruction",
        "boundary полного recursive traversal.",
        "",
        "| Instruction | Target | Вид | ROM/RAM producer |",
        "|---:|---:|---|---|",
    ]
    for edge in runtime["indirect_control_flow"]:
        lines.append(
            f"| `${edge['source']:04X}` | `${edge['target']:04X}` | "
            f"`{edge['kind']}` | {edge['table']} |")
    lines += [
        "",
        "## Все runtime вызовы RNG `$EDE9`",
        "",
        f"Достигнуто ровно **{len(runtime['rng_call_sites'])}** call sites. Для",
        "каждого приведён owner entry и точное окно исполнения: четыре",
        "инструкции до `CALL` фиксируют timer/VBlank guard и подготовку, четыре",
        "после — маску, диапазон и destination случайного значения.",
        "",
        "| Call site | Owner | Точный instruction context |",
        "|---:|---:|---|",
    ]
    for site in runtime["rng_call_sites"]:
        context = " ; ".join(
            f"`${item['address']:04X}` {item['mnemonic']} {item['operands']}".rstrip()
            for item in site["context"])
        lines.append(
            f"| `${site['source']:04X}` | `${site['owner_entry']:04X}` | "
            f"{context} |")
    lines += [
        "",
        "## Runtime direct CALL cross-reference",
        "",
        "| Callee | Все достигнутые callers | Semantic contexts callee |",
        "|---:|---|---|",
    ]
    callers: dict[int, list[int]] = collections.defaultdict(list)
    for source, target in runtime["direct_calls"]:
        callers[target].append(source)
    for target in sorted(callers):
        source_text = ", ".join(f"`${value:04X}`" for value in callers[target])
        labels = "; ".join(contexts.get(f"{target:04X}", []))
        lines.append(f"| `${target:04X}` | {source_text} | {labels or '—'} |")
    lines += [
        "",
        "## Прямые absolute data references",
        "",
        "| Instruction | Segment | Offset | Предварительное пространство |",
        "|---:|---:|---:|---|",
    ]
    for source, segment, target in data_refs:
        meaning = ("World ROM data" if segment == "ES" else
                   "literal DS offset; effective segment changes are documented separately")
        lines.append(f"| `${source:04X}` | `{segment}` | `${target:04X}` | {meaning} |")
    lines += [
        "",
        "## Полный syntactic registry обращений через `ES`",
        "",
        f"Рекурсивно достижимый runtime содержит ровно **{len(runtime['es_access_sites'])}** ",
        "инструкций с явным `ES:[...]`. Таблица намеренно отделяет syntactic",
        "адресацию от семантики: `ES` бывает World ROM, video/palette RAM или",
        "временным рабочим сегментом. Окончательная классификация должна",
        "следовать из segment-state перед инструкцией; один literal сам по себе",
        "не считается доказательством типа данных.",
        "",
        "| Instruction | Owner | ES segment / пространство | Access | Выражение | Команда | Semantic context |",
        "|---:|---:|---|---|---|---|---|",
    ]
    for site in runtime["es_access_sites"]:
        expressions = ", ".join(f"`{value}`" for value in site["expressions"])
        segment_text = "; ".join(
            ("`DS:$3088` dynamic" if value is None else f"`${value:04X}`") +
            f" {meaning}" for value, meaning in
            zip(site["segments"], site["segment_meanings"]))
        context = "; ".join(site["context"]) or "—"
        operation = f"{site['mnemonic']} {site['operands']}".rstrip()
        owner_text = ", ".join(f"`${value:04X}`"
                               for value in site["owner_entries"])
        lines.append(
            f"| `${site['source']:04X}` | {owner_text} | "
            f"{segment_text} | `{site['access']}` | {expressions} | "
            f"`{operation}` | {context} |")
    world_catalog = runtime["world_es_access_catalog"]
    lines += [
        "",
        "## Индекс прямых баз World ES и pointer-relative consumers",
        "",
        f"Из {len(runtime['es_access_sites'])} syntactic ES-sites ровно **{world_catalog['world_site_count']}** ",
        "принадлежат неизменному World ROM segment `$1000`. Все они включены",
        "в индекс: большой signed displacement нормализован как ROM-база,",
        "малый `+field` без доказанного producer остаётся pointer-relative.",
        f"Получено **{world_catalog['direct_base_count']}** прямых баз и ",
        f"**{world_catalog['pointer_relative_site_count']}** pointer-relative sites.",
        "",
        "| Base | Width/access | Consumer instructions | Owner entries | Context |",
        "|---:|---|---|---|---|",
    ]
    for group in world_catalog["direct_bases"]:
        consumers = group["consumers"]
        signatures = ", ".join(sorted({
            f"{item['access']}:{item['width']}" for item in consumers}))
        sources = ", ".join(f"`${item['source']:04X}`" for item in consumers)
        owners = ", ".join(f"`${value:04X}`" for value in sorted({
            owner for item in consumers for owner in item["owner_entries"]}))
        context = "; ".join(sorted({
            label for item in consumers for label in item["context"]})) or "—"
        lines.append(f"| `${group['base']:04X}` | `{signatures}` | "
                     f"{sources} | {owners} | {context} |")
    pointer_sources = ", ".join(
        f"`${item['source']:04X}`"
        for item in world_catalog["pointer_relative_consumers"])
    lines += [
        "",
        "Pointer-relative consumer sites (полные команды, owners и context",
        "находятся в предыдущей таблице и в JSON):",
        "",
        pointer_sources,
    ]
    for title, data in (
            ("Reset/DSW World-ROM formats", report["bootstrap_3f00"]["world_rom_data"]),
            ("Service-mode World-ROM formats", report["bootstrap_3900"]["world_rom_data"])):
        lines += ["", f"### {title}", "",
                  "| ES range | Segment | Exact format | Consumer sites |",
                  "|---:|---:|---|---|"]
        for item in data["ranges"]:
            consumers = ", ".join(f"`${value:04X}`"
                                  for value in item["consumers"]) or "—"
            lines.append(
                f"| `${item['start']:04X}..${item['end']:04X}` | "
                f"`{item.get('segment', 'ES')}:$1000` | {item['format']} | "
                f"{consumers} |")
    lines += ["", "### Sprite descriptor producer formats", "",
              "| ES range | Exact format | Renderer/data consumers |",
              "|---:|---|---|"]
    for item in report["graphics"]["sprite_consumers"]["producer_ranges"]:
        consumers = ", ".join(f"`${value:04X}`"
                              for value in item["consumers"]) or "—"
        lines.append(
            f"| `${item['start']:04X}..${item['end']:04X}` | "
            f"{item['format']} | {consumers} |")
    es_coverage = report["world_es_semantic_coverage"]
    lines += ["", "### Runtime/interpreter World-ROM formats", "",
              "| ES range | Exact format | Consumer sites |",
              "|---:|---|---|"]
    for item in (es_coverage["proven_runtime_ranges"] +
                 es_coverage["interpreter_ranges"]):
        consumers = ", ".join(f"`${value:04X}`"
                              for value in item["consumers"]) or "— (proved unreferenced)"
        lines.append(
            f"| `${item['start']:04X}..${item['end']:04X}` | "
            f"{item['format']} | {consumers} |")
    lines += [
        "",
        "## Побайтовое покрытие форматов World ES",
        "",
        f"Без догадок классифицировано **{es_coverage['known_byte_count']}** из",
        f"**65536** bytes; осталось **{es_coverage['unresolved_byte_count']}**.",
        "Один byte считается закрытым только внутри доказанного code alias,",
        "sprite descriptor, stage interpreter table/record, metatile descriptor",
        "или проверенного `$FF` tail. Пересечения сохраняют оба формата.",
        "",
        "| ES range | Classification |",
        "|---:|---|",
    ]
    for item in es_coverage["classified_runs"]:
        lines.append(f"| `${item['start']:04X}..${item['end']:04X}` | "
                     f"`{item['classification']}` |")
    lines += [
        "",
        "## Все осмысленные адреса из подробной semantic map",
        "",
        "Таблица ниже строится из каждого литерала `$XXXX` в",
        "`RTYPE_WORLD_ROM_MAP.md`. Контекст — заголовок раздела, где адрес",
        "был получен из disassembly, HEX или runtime evidence. Поэтому ни один",
        "ранее осмысленный адрес не может молча исчезнуть из полного индекса.",
        "",
        "| Logical/address | Исследованные контексты |",
        "|---:|---|",
    ]
    for address, headings in contexts.items():
        lines.append(f"| `${address}` | {'; '.join(headings)} |")
    lines += [
        "",
        "## Точные непрерывные runs автоматической byte-классификации",
        "",
        "Это более точный уровень, чем 4 KiB matrix: границы идут по каждому",
        "переходу code/data class. Полный raw byte остаётся в проверяемом region",
        "и однозначно восстанавливается по SHA исходных ROM.",
        "",
        "| Physical | Class |",
        "|---:|---|",
    ]
    for run in report["main_class_runs"]:
        lines.append(f"| `{run['start']:05X}..{run['end']:05X}` | `{run['kind']}` |")
    lines += [
        "",
        "## Полные event streams всех восьми stages",
        "",
        f"Проверено **{report['all_stage_events']['event_count']}** записей и",
        f"**{len(report['all_stage_events']['handler_meanings'])}** именованных",
        "entry semantics dispatch table `ES:$B92D`. Вложенный generated index:",
        "",
        report["all_stage_events"]["markdown"],
        "",
        "## Графические ROM address spaces",
        "",
        "### `tiles0` и `tiles1`",
        "",
        "Каждый region `$00000..$1FFFF` состоит из четырёх plane quarters по",
        "`$8000`. MAME `tilelayout`: 8×8, 4 bpp, 4096 code `$000..$FFF`,",
        "64 bits одного plane на code. Plane order — region quarters 3,2,1,0.",
        "Все 4096 code каждого слоя адресуемы; атрибут tile выбирает palette и",
        "flip независимо от raw ROM address.",
        "",
        "Связь с main ROM теперь проверяется полностью. Physical",
        "`$30000..$38FFF` — не POST pattern, а ровно 256 metatile records по",
        "144 bytes. Каждый record содержит 48 cells по три bytes:",
        "`tile code word + attribute byte`. Foreground descriptor array",
        "`ES:$C627..$D68E` содержит 2100 words, background",
        "`ES:$D68F..$EB06` — 2620; low 14 bits каждого word проверены как",
        "metatile index `$00..$FF`, bits 14/15 — flip X/Y.",
        "",
        f"`tiles0` имеет **{report['graphics']['tile_consumers']['tiles0_used_codes']}** codes с foreground consumers; ",
        f"`tiles1` — **{report['graphics']['tile_consumers']['tiles1_used_codes']}** с background consumers. ",
        "Для каждого из всех 4096 codes JSON хранит точный список metatile",
        "indices и число layer descriptors; отсутствующий список означает",
        "доказанно неиспользуемый code, а не неразобранный адрес.",
        "",
        "### `sprites`",
        "",
        "Region `$00000..$7FFFF`, четыре plane quarters по `$20000`, layout",
        "16×16×4 bpp, 4096 code `$000..$FFF`. Внутри каждого quarter ROM `$01`,",
        "`$11`, `$21`, `$31` занимают только первые `$8000` и аппаратно/MAME",
        "перезагружены во вторые `$8000`: `$10000→$18000`, `$30000→$38000`,",
        "`$50000→$58000`, `$70000→$78000`. Автопроверка сравнивает эти четыре пары.",
        "",
        "Строгая нижняя граница строится только от достигнутых calls",
        "`$1BCC/$1BE9/$1C1B/$1CA6`: literal `BX` доказывает адрес descriptor,",
        "а composite emitters доказывают также запись `BX+6`. Сейчас",
        f"разрешено **{report['graphics']['sprite_consumers']['literal_bx_calls']}** из ",
        f"**{report['graphics']['sprite_consumers']['renderer_calls_total']}** renderer calls и ",
        f"**{report['graphics']['sprite_consumers']['directly_proven_code_count']}** уникальных sprite codes. ",
        "Все renderer calls разрешены через literal, object-field и ROM-table",
        "producer chains; похожие шестибайтные последовательности без consumer",
        "edge дескрипторами не объявляются. Code без consumer list доказанно",
        "не используется достигнутым игровым графом.",
        "",
        "## I/O address space",
        "",
        "| Ports | Read | Write |",
        "|---:|---|---|",
        "| `$00..$01` | IN0 | sound latch `$00`; `$01` без отдельной write-семантики |",
        "| `$02..$03` | IN1 | `$02` coin counters / sound CPU reset |",
        "| `$04..$05` | DSW | `$04` sprite DMA trigger |",
        "| `$06..$07` | — | raster IRQ line |",
        "| `$40..$43` | PIC 8259 | PIC 8259 |",
        "| `$80..$81` | — | layer 0 scroll Y |",
        "| `$82..$83` | — | layer 0 scroll X |",
        "| `$84..$85` | — | layer 1 scroll Y |",
        "| `$86..$87` | — | layer 1 scroll X |",
        "",
        "### Биты входных words (active-low)",
        "",
        "| Word/bit | Назначение |",
        "|---:|---|",
        "| `IN0 $0001/$0002/$0004/$0008` | P1 right/left/down/up |",
        "| `IN0 $0010/$0020/$0040/$0080` | P1 buttons 4/3/2/1 |",
        "| `IN0 $0100..$8000` | те же направления/кнопки cocktail P2 |",
        "| `IN1 $0001/$0002` | Start 1 / Start 2 |",
        "| `IN1 $0004/$0008` | Coin 1 / Coin 2 (аппаратная arcade-семантика; в ZX-порту не требуется монетник) |",
        "| `IN1 $0010/$0020` | Service 1 / service test mode |",
        "| `IN1 $0080` | sprite DMA complete |",
        "",
        "### R-Type DSW word",
        "",
        "| Mask | Значение |",
        "|---:|---|",
        "| `$0003` | lives: 2/3/4/5 |",
        "| `$0004` | demo sounds |",
        "| `$0008` | bonus-life schedule |",
        "| `$00F0` | coinage mode 1 / часть mode 2 |",
        "| `$0100` | flip screen |",
        "| `$0200` | upright/cocktail |",
        "| `$0400` | coin mode 1/2 |",
        "| `$0800` | normal/hard |",
        "| `$1000` | allow continue |",
        "| `$2000` | stop mode |",
        "| `$4000` | invulnerability diagnostic DIP |",
        "| `$8000` | service mode |",
        "",
        "### Z80 sound address/port spaces",
        "",
        "| Space | Range | Назначение |",
        "|---|---:|---|",
        "| program | `$0000..$FFFF` | shared sound RAM; V30 загружает `$0000..$7FFF`, Z80 использует верх как state/stack |",
        "| I/O | `$00..$01` | YM2151 status/register-data read/write |",
        "| I/O | `$02` read | V30 sound latch command |",
        "| I/O | `$06` write | acknowledge sound latch |",
        "| I/O | прочее | unmapped для конфигурации `rtype_sound_portmap` |",
        "",
        "Sound CPU имеет собственное 64 KiB address space в shared sound RAM;",
        "для R-Type отдельного sound program ROM в комплекте нет. Точный цикл",
        "`$0040:$0015..$0030` ставит `DS=$2000`, `ES=$E000`, 32768 раз делает",
        "`MOVSB; INC SI`: берёт один byte и пропускает его равную копию.",
        "Следовательно physical `$20000 + 2*n` и `$20001 + 2*n` соответствуют",
        "одному sound address `$n`. Все 32768 пары проверяются автоматически.",
        f"Sound image SHA-256: `{report['sound_z80']['sha256']}`; последний",
        f"не-`$FF` byte: `${report['sound_z80']['last_non_ff']:04X}`; `$5781..$7FFF` erased.",
        "",
        "### Recursive Z80 control-flow map",
        "",
        f"Достигнуто инструкций: **{report['sound_z80']['recursive']['instruction_count']}**; ",
        f"code bytes в `$0000..$5780`: **{report['sound_z80']['recursive']['code_bytes_loaded_image']}**; ",
        f"не принадлежат достигнутым инструкциям: **{report['sound_z80']['recursive']['non_code_bytes_loaded_image']}**; ",
        f"indirect `JP (HL/IX/IY)`: **{len(report['sound_z80']['recursive']['indirect_jumps'])}**.",
        "",
        "Этот split использует точные длины Z80, прямые JP/JR/CALL/RST и",
        "interrupt vectors `$0008…$0038`. Непокрытые bytes ещё нельзя все",
        "назвать исполняемыми: два `JP (HL)` полностью разрешены через",
        "ROM-таблицы `$035E` (32 entries) и `$03AC` (3 entries).",
        "",
        "### Независимая MAME bus trace sound Z80",
        "",
        f"Проверено: **{report['sound_z80']['mame_bus_trace']['verified']}**; ",
        f"подано commands: **{report['sound_z80']['mame_bus_trace']['commands_sent']}**; ",
        f"наблюдалось PC values: **{report['sound_z80']['mame_bus_trace']['observed_pc_values']}**; ",
        f"границ статических инструкций: **{report['sound_z80']['mame_bus_trace']['observed_instruction_starts']}**.",
        "",
        "MAME получил все command bytes `$00..$FF`. Program read/write и I/O",
        "taps агрегированы по паре `PC,address`. Все program writes лежат только",
        "в `$F800..$FFFF`; read ports строго `$01/$02`, write ports строго",
        "`$00/$01/$06`. Каждый наблюдавшийся PC принадлежит byte достигнутой",
        "статической инструкции, кроме `$0610`: это уже выставленный PC после",
        "`RET $060F` во время чтения return address из `$FD7A/$FD7B`, а не",
        "исполнение byte `$0610`. Generator проверяет это исключение явно.",
        "",
        "### Полный формат sound data `$1000..$5781`",
        "",
        f"Command records: **{report['sound_z80']['data_formats']['unique_command_records']}**; ",
        f"stream pointer references: **{report['sound_z80']['data_formats']['stream_pointer_references']}**; ",
        f"уникальных stream roots: **{report['sound_z80']['data_formats']['unique_stream_roots']}**; ",
        f"не классифицировано bytes: **{report['sound_z80']['data_formats']['unclassified_bytes_1000_5781']}**.",
        "",
        "| Range | Точный формат |",
        "|---:|---|",
    ]
    for layout in report["sound_z80"]["data_formats"]["layouts"]:
        lines.append(
            f"| `${layout['start']:04X}..${layout['end']:04X}` | "
            f"{layout['format']} |")
    lines += [
        "",
        "#### 32 класса stream bytecode",
        "",
        "| Opcode | Handler | Bytes | Flow | Семантика |",
        "|---:|---:|---:|---|---|",
    ]
    for opcode in report["sound_z80"]["data_formats"]["opcode_classes"]:
        lines.append(
            f"| `${opcode['start']:02X}..${opcode['end']:02X}` | "
            f"`${opcode['handler']:04X}` | {opcode['bytes']} | "
            f"`{opcode['flow']}` | {opcode['meaning']} |")
    lines += [
        "",
        "#### Все command bytes и их records",
        "",
        "Bit 7 команды отбрасывается инструкцией `$00F8 SLA E`, после которой",
        "`D=0`: поэтому `$80..$FF` являются точными aliases `$00..$7F`.",
        "`start` использует сам command как owner; `replace-owner` читает owner",
        "следующим byte; `fade-owner` содержит `(owner,target attenuation,",
        "duration divisor)`; type `>=30` немедленно отклоняется как no-op.",
        "",
        "| Commands | Record/type | Kind/owner | Stream pointers или fade |",
        "|---:|---:|---|---|",
    ]
    for command in report["sound_z80"]["data_formats"]["commands"]:
        pointers = ", ".join(
            f"`${value:04X}`" for value in command["stream_pointers"])
        if command["kind"] == "fade-owner":
            payload = (f"target=`${command['target_attenuation']:02X}`, "
                       f"divisor=`${command['duration_divisor']:02X}`")
        else:
            payload = pointers or "—"
        lines.append(
            f"| `${command['aliases'][0]:02X}`/`${command['aliases'][1]:02X}` | "
            f"`${command['record']:04X}`/`${command['type']:02X}` | "
            f"`{command['kind']}`, owner `${command['owner_command']:02X}` | "
            f"{payload} |")
    lines += [
        "",
        "#### Orphan stream blocks",
        "",
        "Эти bytes декодируются тем же bytecode grammar, но не имеют inbound",
        "edge ни от 128 command records, ни от всех наблюдавшихся `$0349`",
        "stream fetches. Это точная категория неиспользуемого остаточного",
        "bytecode, а не неизвестные данные.",
        "",
        "| Range | Raw bytes |",
        "|---:|---|",
    ]
    for block in report["sound_z80"]["data_formats"]["orphan_bytecode_blocks"]:
        lines.append(
            f"| `${block['start']:04X}..${block['end']:04X}` | "
            f"`{block['raw']}` |")
    lines += [
        "",
        "| Z80 range | Класс |",
        "|---:|---|",
    ]
    for run in report["sound_z80"]["recursive"]["class_runs"]:
        lines.append(
            f"| `${run['start']:04X}..${run['end']:04X}` | `{run['kind']}` |")
    lines += [
        "",
        "### Полный линейный Z80 listing sound image `$0000..$5780`",
        "",
        "Этот listing создан `MAME 0.288 unidasm -arch z80`. Он гарантирует",
        "адрес/HEX/декодирование каждого загруженного не-erased byte, но не",
        "выдаёт data tables за доказанные процедуры: линейный дизассемблер",
        "по определению декодирует и данные. Code/data split выше объединяет",
        "recursive traversal с независимой sound-PC/read/write bus trace.",
        "",
        "```asm",
        report["sound_z80"]["linear_listing"],
        "```",
        "",
        "## Автопроверка",
        "",
        "```powershell",
        "$env:PYTHONPATH='Build\\PythonDeps;Source\\Tools'",
        "python Source/Tools/m72_rom_complete_map.py --check",
        "```",
        "",
        "Проверяются SHA всех исходников, размеры assembled regions, полное",
        "покрытие `$00000..$3FFFF`, reset mirror, erased `$2B000..$2FFFF`,",
        "четыре sprite reload и воспроизводимость JSON/Markdown.",
        "",
        "## Строгий статус семантической расшифровки",
        "",
        f"Незакрытых пунктов: **{semantic['unresolved_count']}**.",
        "",
        "`--check` обязан завершаться ошибкой, пока это число не равно нулю.",
        "",
    ]

    for item in semantic["manual_queue"] + semantic["builtin_gaps"]:
        lines.append(f"- {item}")
    if semantic["runtime_entries_without_context"]:
        values = ", ".join(
            f"`${value:04X}`" for value in
            semantic["runtime_entries_without_context"])
        lines.append(f"- V30 entries без semantic-map context: {values}")
    if semantic["direct_refs_without_context"]:
        values = ", ".join(
            f"`{space}:${address:04X}`" for space, address in
            semantic["direct_refs_without_context"])
        lines.append(f"- Прямые data references без semantic-map context: {values}")
    lines.append("")

    lines += [
        "## Far control-flow edges V30",
        "",
        "| Source CS offset | Тип | Target segment:offset |",
        "|---:|---|---:|",
    ]
    for source, segment, offset in runtime["far_calls"]:
        lines.append(f"| `${source:04X}` | `CALL FAR` | `${segment:04X}:${offset:04X}` |")
    for source, segment, offset in runtime["far_jumps"]:
        lines.append(f"| `${source:04X}` | `JMP FAR` | `${segment:04X}:${offset:04X}` |")

    for title, key, segment, physical in (
            ("Service diagnostic procedure index", "bootstrap_3900", 0x3900, 0x39000),
            ("Reset/POST/helper procedure index", "bootstrap_3f00", 0x3F00, 0x3F000)):
        lines += [
            "",
            f"## {title}",
            "",
            "| Segment:offset | Physical | End offset | Instructions | Direct callees |",
            "|---:|---:|---:|---:|---|",
        ]
        for function in report[key]["functions"]:
            callees = ", ".join(f"`${value:04X}`"
                                for value in function["direct_calls"])
            lines.append(
                f"| `${segment:04X}:${function['entry']:04X}` | "
                f"`{function['physical']:05X}` | `${function['end']:04X}` | "
                f"{function['instruction_count']} | {callees or '—'} |")

    def append_listing(title: str, instructions: list[dict[str, object]],
                       segment: int) -> None:
        lines.extend(["", f"## {title}", "", "```asm"])
        for item in instructions:
            lines.append(
                f"{segment:04X}:{item['address']:04X}  "
                f"{item['raw']:<29} {item['mnemonic']:<8} {item['operands']}".rstrip())
        lines.extend(["```", ""])

    append_listing("Полный достигнутый runtime V30 listing",
                   runtime["instructions"], 0x0040)
    append_listing("Полный service diagnostic V30 listing",
                   report["bootstrap_3900"]["instructions"], 0x3900)
    append_listing("Полный reset/POST/helper V30 listing",
                   report["bootstrap_3f00"]["instructions"], 0x3F00)
    return "\n".join(lines)


def serialized_outputs(report: dict[str, object]) -> tuple[str, str]:
    return (json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            render_markdown(report))


def write_outputs(report: dict[str, object]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    json_text, markdown = serialized_outputs(report)
    JSON_PATH.write_text(json_text, encoding="utf-8")
    MD_PATH.write_text(markdown, encoding="utf-8")
    ALL_STAGE_PATH.write_text(report["all_stage_events"]["markdown"],
                              encoding="utf-8")


def verify_outputs(report: dict[str, object]) -> list[str]:
    """Проверить, что committed/generated документы не устарели."""
    expected_json, expected_markdown = serialized_outputs(report)
    errors = []
    for path, expected in ((JSON_PATH, expected_json),
                           (MD_PATH, expected_markdown),
                           (ALL_STAGE_PATH,
                            report["all_stage_events"]["markdown"])):
        if not path.is_file():
            errors.append(f"отсутствует generated output `{path.relative_to(ROOT)}`")
        elif path.read_text(encoding="utf-8") != expected:
            errors.append(f"generated output устарел: `{path.relative_to(ROOT)}`")
    if not SOUND_PATH.is_file() or SOUND_PATH.read_bytes() != sound_upload_image(
            assemble_regions()["maincpu"]):
        errors.append("generated sound upload image отсутствует или устарел")
    main = assemble_regions()["maincpu"][:0x40000]
    if not MAIN_PATH.is_file() or MAIN_PATH.read_bytes() != main:
        errors.append("generated unique main ROM image отсутствует или устарел")
    return errors


def cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="проверить и пересобрать карту; fail при invariant error")
    args = parser.parse_args()
    report = build_report()
    errors = list(report["coverage"]["errors"])
    if args.check:
        errors.extend(verify_outputs(report))
    else:
        write_outputs(report)
    print(f"ROM files: {len(report['raw_roms'])}/20")
    print(f"runtime instructions: {report['runtime_v30']['instruction_count']}")
    print(f"runtime function entries: {len(report['runtime_v30']['function_entries'])}")
    print(f"unclassified main bytes: {report['coverage']['unclassified_bytes']}")
    print(f"semantic unresolved items: "
          f"{report['semantic_completion']['unresolved_count']}")
    print(f"JSON: {JSON_PATH}")
    print(f"Markdown: {MD_PATH}")
    if report["semantic_completion"]["unresolved_count"]:
        errors.append("семантическая карта содержит незакрытые пункты")
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    if args.check:
        print("AUTOCHECK OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
