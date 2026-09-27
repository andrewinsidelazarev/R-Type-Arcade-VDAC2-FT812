#!/usr/bin/env python3
"""Нарезка RAM_G-ассетов на 16К-страницы для spgbld.

M72 ARGB4444 blob грузится в RAM_G целиком при старте: SPG кладёт куски в
страницы, а ASM отправляет их в FT812 через TS DMA.
Генерирует также generated_spritepages.inc с таблицами для загрузчиков.

От принятого интерфейса v002 сохраняется только нижняя 30-строчная HUD-панель.
Игровое поле строится живыми all-stage terrain textures и не хранит лишний
614400-байтный кадр Stage 1.

Оригинальный MAME fire transient хранится отдельно в SPG-страницах как готовый
unsigned 8-bit mono PCM 11025 Hz. Эти страницы потоково загружаются в General
Sound при старте и не занимают RAM_G FT812.
"""
from __future__ import annotations

import hashlib
import json
import zlib
from pathlib import Path

from pyz80_compiler import (CompileError, PhysicalAllocation,
                            load_memory_layout,
                            validate_physical_allocations)

ROOT = Path(__file__).resolve().parents[2]
SPR_SRC = (
    ROOT
    / "Assets"
    / "Converted"
    / "Arcade"
    / "Sprites"
    / "RTYPE_M72_FRAME900_ARGB4444.bin"
)
GS_WAVE_SRC = (
    ROOT
    / "Audio"
    / "Converted"
    / "RTYPE_WAVE_SHOT_U8_11025.raw"
)
# Видеотракт M72: атлас глифов и спрайтовых ячеек (из ROM, апскейл офлайн),
# тайловая память и sprite RAM титульного экрана. Порт держит структуры
# оригинала как есть — рендерер читает из них код и атрибут, как это делал V30.
M72_TILE_ATLAS_SRC = ROOT / "Assets" / "Converted" / "Arcade" / "Atlas" / "TILE_ATLAS_ARGB4444.bin"
M72_TITLE_VRAM_SRC = ROOT / "Assets" / "Converted" / "Arcade" / "Atlas" / "TITLE_VRAM0.bin"
M72_SPR_ATLAS_SRC = ROOT / "Assets" / "Converted" / "Arcade" / "Atlas" / "TITLE_FONT_ARGB4444.bin"
M72_SPRITERAM_SRC = ROOT / "Assets" / "Converted" / "Arcade" / "Atlas" / "TITLE_SPRITERAM.bin"
M72_TITLE_EVENTS_SRC = ROOT / "Assets" / "Converted" / "Arcade" / "Atlas" / "TITLE_EVENTS.bin"
M72_STAGE_DIR = ROOT / "Assets" / "Converted" / "Arcade" / "Stage1" / "Tiles"
M72_STAGE_BG_ATLAS_SRC = M72_STAGE_DIR / "STAGE1_BG_BACK_ATLAS_ARGB4444.bin"
M72_STAGE_FG_ATLAS_SRC = M72_STAGE_DIR / "STAGE1_FG_FRONT_ATLAS_ARGB4444.bin"
M72_STAGE_BG_MAP_SRC = M72_STAGE_DIR / "STAGE1_BG_BACK_MAP.bin"
M72_STAGE_FG_MAP_SRC = M72_STAGE_DIR / "STAGE1_FG_FRONT_MAP.bin"
M72_STAGE_EVENTS_SRC = M72_STAGE_DIR / "STAGE1_VRAM_EVENTS.bin"
ARCADE_BG_SRC = (
    ROOT / "Assets" / "Converted" / "Arcade" / "Stage1"
    / "STAGE1_FRAME0900_TILES_640x480_RGB565.bin"
)
# В SPG остаётся только компактный Stage 1: игра гарантированно стартует даже
# без карты, а Stage 2…8 загружаются FAT32-драйвером. Монолит всех уровней
# больше не съедает 154 страницы и оставляет RAM для таблиц automata.
TARGET_PACK_SRC = ROOT / "Build" / "SD" / "RType" / "RTYPE01.PAK"
# Полный M72 sprite ROM в index4. Для игрового hot path он заранее
# разворачивается в index8 и занимает страницы #70..#AF: на промахе кэша
# TS DMA копирует 8-КБ chunk прямо в RAM_G, не гоняя Inflate через Z80/SPI.
M72_SPRITE_INDEX4_SRC = (
    ROOT / "Assets" / "Converted" / "Arcade" / "RTYPE_SPRITES_INDEX4.bin"
)
# Музыка Stage 1, перенесённая с YM2151 на TurboSound FM (ym2151_to_tsfm.py).
TSFM_MUSIC_SRC = (
    ROOT / "Assets" / "Converted" / "Arcade" / "Music" / "STAGE1_TSFM.bin"
)
OUT_DIR = ROOT / "Build"
OUT_INC = ROOT / "Source" / "ASM" / "generated_spritepages.inc"
OUT_INI = ROOT / "spgbld_rtype.ini"
PYTHON_TRANSLATION_SRC = ROOT / "Build" / "python_translation_tables.bin"
PYTHON_COMPILED_SRC = ROOT / "Build" / "python_compiled_p00.bin"
PYTHON_COMPILER_REPORT = ROOT / "Build" / "rtype_python_compiler.json"
PYTHON_ASSET_MANIFEST = ROOT / "Build" / "rtype_python_assets.json"
PYTHON_HQ_LOOKUP_PAGE = 0xEC
PYTHON_HQ_LOOKUP_OFFSET = 0x2000
PYTHON_HQ_TEMPLATE_OFFSET = 0x2700
PYTHON_BEAM_SRC = ROOT / "Build" / "rtype_python_beam_commands.bin"
PYTHON_CHARGE_SRC = (
    ROOT / "Assets" / "Converted" / "Arcade" / "Player"
    / "R9_CHARGE_ARGB4444.bin"
)
PYTHON_PLAYER_MANIFEST = PYTHON_CHARGE_SRC.with_name("r9_pitch.json")
MEMORY_LAYOUT_MANIFEST = ROOT / "Source" / "Tools" / "rtype_memory_layout.json"

# Шапка конфигурации spgbld. Имя выходного SPG задаётся в build.cmd и всегда
# rtype_vdac2.spg — переименование запрещено (CLAUDE.md).
INI_HEAD = """Desc = R-Type VDAC2
Start = 0x5000
Stack = 0x4EFF
Resident = 0x4F00
Page3 = 0
Clock = 2
INT = 0
Pager = 0x0

Compression = 0

; Ядро: код и резидентные данные, страница #05 (слот 1).
Block = #5000, #05, Build/Core.bin

; Предсохранённые таблицы приложения: постоянно отображённая page #00.
Block = #1000, #00, Build/coordinate_tables.bin
Block = #2000, #00, Build/resident_tables.bin

; Банк сложных object handlers. Во время вызова он временно отображается в
; slot2 `$8000..$BFFF`; page #06 восстанавливается до возврата в главный цикл.
Block = #0000, #0A, Build/object_bank1.bin
Block = #0000, #0B, Build/object_bank2.bin
Block = #0000, #0C, Build/object_bank3.bin
Block = #0000, #0D, Build/object_bank4.bin
Block = #0000, #0E, Build/rtype_loader.bin
Block = #0000, #E5, Build/collision_bank.bin
Block = #0000, #E6, Build/fixed_player_bank.bin

; Настоящие спрайтовые объекты M72 (ARGB4444), предварительные xBRZ6 + Lanczos.
"""

PAGE_SIZE = 0x4000
FIRST_PAGE = 0x10          # страницы #10.. свободны (Core занимает #05/#06)
TARGET_PACK_BASE_PAGE = 0x49
PYTHON_CHARGE_PAGES = (0xE8, 0xE9, 0xEA)
PYTHON_BEAM_PAGE = 0xEB
SPRITE_RAW_PAGE_COUNT = 0x40
# Active stage может занимать #49..#76, staging — #B0..#DD. Поэтому мегабайт
# sprite ROM разбит на два физических диапазона, а точные страницы хранит
# таблица: #77..#AF (57) и #DE..#E4 (7).
SPRITE_RAW_PAGES = tuple(range(0x77, 0xB0)) + tuple(range(0xDE, 0xE5))
RAM_G_SIZE = 0x100000
M72_SPR_SHA256 = "463683d30f58a585c5b7eb2365cbe8c83c522d264b23fed4aecab7ec1b8e1ecb"
GS_WAVE_SHA256 = "5b5e8043d927c89b9376eb4ef995c3f62868b07456cdbecc8857a9c74092e29a"
# Изолированно снятые эффекты (mame_sound_command.lua): $30 — обычный выстрел,
# $31 — Wave Cannon. Сняты в тишине, без вычитания дорожек.
#
# Выстрел собирается отдельным скриптом m72_shot_sfx.py на 22050 Гц: 43 % его
# энергии лежит выше предела Найквиста для 11025 Гц, и на общей частоте он терял
# характер. Играется нотой на октаву выше (GS_SHOT_NOTE в general_sound.asm).
GS_SHOT_SRC = ROOT / "Audio" / "Converted" / "RTYPE_SFX_SHOT_U8_22050.raw"
GS_SHOT_SHA256 = "024854e39929fe671cef1e2e6ae61dfdc4eae0e0ee67c09b4f27ddf4368096ba"
ARCADE_BG_SHA256 = "5b92f8f61f8bab08a08b8c66cf94700556f54513861131a573160b291d598078"


def pad_gs_fx(pcm: bytes) -> bytes:
    """Добить FX тишиной: GS доигрывает внутренний буфер до его границы."""
    if not pcm:
        return pcm
    target = ((len(pcm) + 64 + 511) // 512) * 512
    return pcm + bytes([0x80]) * (target - len(pcm))


def unpack_index4(blob: bytes) -> bytes:
    """Развернуть left/high, right/low nibbles M72 в байты index8."""
    result = bytearray(len(blob) * 2)
    result[0::2] = bytes(value >> 4 for value in blob)
    result[1::2] = bytes(value & 0x0F for value in blob)
    return bytes(result)


def split_blob(blob: bytes, *, first_page: int, stem: str) -> list[tuple[int, int, Path]]:
    pages = []
    for offset in range(0, len(blob), PAGE_SIZE):
        chunk = blob[offset:offset + PAGE_SIZE]
        page = first_page + len(pages)
        if page > 0xFF:
            raise SystemExit(f"номер страницы ${page:X} не помещается в DEFB")
        out = OUT_DIR / f"{stem}_p{len(pages):02d}.bin"
        out.write_bytes(chunk)
        pages.append((page, len(chunk), out))
    return pages


def split_blob_page_list(
        blob: bytes, *, page_numbers: tuple[int, ...], stem: str
) -> list[tuple[int, int, Path]]:
    """Нарезать blob по явно заданной непересекающейся карте TS RAM."""
    if len(blob) > len(page_numbers) * PAGE_SIZE:
        raise SystemExit(f"{stem}: для {len(blob)} Б не хватает заданных pages")
    pages = []
    for index, offset in enumerate(range(0, len(blob), PAGE_SIZE)):
        chunk = blob[offset:offset + PAGE_SIZE]
        page = page_numbers[index]
        out = OUT_DIR / f"{stem}_p{index:02d}.bin"
        out.write_bytes(chunk)
        pages.append((page, len(chunk), out))
    return pages


def validate_spg_page_layout(
        named_groups: list[tuple[str, str, tuple[int, ...]]],
        ) -> int:
    """Сверить реальные страницы упаковщика с общей картой памяти цели."""
    try:
        layout, layout_report = load_memory_layout(MEMORY_LAYOUT_MANIFEST)
        allocations = [
            PhysicalAllocation(name, owner, pages)
            for name, owner, pages in named_groups if pages
        ]
        allocation_report = validate_physical_allocations(layout, allocations)
    except CompileError as error:
        raise SystemExit(f"memory layout: {error}") from error
    if (layout_report.owners_of_page(0xED) != ("ft812-render-queues",) or
            layout_report.owners_of_page(0xEE) != ("ft812-render-queues",) or
            layout_report.owners_of_page(0xEF) !=
            ("ft812-command-templates",)):
        raise SystemExit("memory layout: потерян резерв FT812 #ED..#EF")
    return len(allocation_report.allocated_pages)


def split_records(blob: bytes, *, record_size: int, records_per_page: int,
                  first_page: int, stem: str) -> list[tuple[int, int, Path]]:
    """Split fixed records without ever cutting one at a TS-Conf page edge."""
    if not blob or len(blob) % record_size:
        raise SystemExit(
            f"{stem}: размер {len(blob)} не кратен записи {record_size}")
    chunk_size = record_size * records_per_page
    if chunk_size > PAGE_SIZE:
        raise SystemExit(f"{stem}: {chunk_size} байт не помещаются в страницу")
    pages = []
    for offset in range(0, len(blob), chunk_size):
        chunk = blob[offset:offset + chunk_size]
        page = first_page + len(pages)
        if page > 0xFF:
            raise SystemExit(f"номер страницы ${page:X} не помещается в DEFB")
        out = OUT_DIR / f"{stem}_p{len(pages):02d}.bin"
        out.write_bytes(chunk)
        pages.append((page, len(chunk), out))
    if b"".join(path.read_bytes() for _, _, path in pages) != blob:
        raise SystemExit(f"{stem}: страницы не собираются обратно в исходный поток")
    return pages


def main() -> int:
    if not SPR_SRC.exists():
        raise SystemExit("нет M72 sprite blob — сначала m72_sprite_assets.py")
    if not GS_WAVE_SRC.exists():
        raise SystemExit(f"нет готового General Sound PCM: {GS_WAVE_SRC}")

    sprite_blob = SPR_SRC.read_bytes()
    gs_wave = GS_WAVE_SRC.read_bytes()
    gs_shot = GS_SHOT_SRC.read_bytes() if GS_SHOT_SRC.exists() else b""
    if gs_shot and hashlib.sha256(gs_shot).hexdigest() != GS_SHOT_SHA256:
        raise SystemExit("PCM обычного выстрела не совпал с зафиксированным")
    sprite_sha256 = hashlib.sha256(sprite_blob).hexdigest()
    if sprite_sha256 != M72_SPR_SHA256:
        raise SystemExit(
            "M72 sprite blob не совпал с зафиксированным build-time asset: "
            f"{sprite_sha256}"
        )
    if len(sprite_blob) & 3:
        raise SystemExit("спрайтовый блоб должен заканчиваться на 4-байтной границе")
    gs_wave_sha256 = hashlib.sha256(gs_wave).hexdigest()
    if gs_wave_sha256 != GS_WAVE_SHA256:
        raise SystemExit(
            "General Sound PCM не совпал с зафиксированным MAME-derived asset: "
            f"{gs_wave_sha256}"
        )
    if not gs_wave:
        raise SystemExit("General Sound PCM должен быть непустым")

    # `#38 Load FX` округляет внутренний sample buffer и при SeekLast=#FF
    # доигрывает весь округлённый хвост. Без собственной unsigned-тишины там
    # слышен мусор GS RAM — именно тот «битый» треск после эффектов на железе.
    # Дополнительные 64 байта гарантируют, что даже уже кратный сектору PCM
    # заканчивается нашей тишиной, а не следующим выделенным FX-буфером.
    gs_wave = pad_gs_fx(gs_wave)
    gs_shot = pad_gs_fx(gs_shot)

    sprite_pages = split_blob(sprite_blob, first_page=FIRST_PAGE, stem="m72_sprites")
    gs_wave_pages = split_blob(
        gs_wave,
        first_page=FIRST_PAGE + len(sprite_pages),
        stem="gs_wave_shot",
    )
    shot_pages = split_blob(
        gs_shot,
        first_page=FIRST_PAGE + len(sprite_pages) + len(gs_wave_pages),
        stem="gs_shot",
    ) if gs_shot else []
    tsfm_music = TSFM_MUSIC_SRC.read_bytes() if TSFM_MUSIC_SRC.exists() else b""
    music_pages = split_blob(
        tsfm_music,
        first_page=(FIRST_PAGE + len(sprite_pages) + len(gs_wave_pages)
                    + len(shot_pages)),
        stem="tsfm_music",
    ) if tsfm_music else []

    def after(*groups):
        return FIRST_PAGE + sum(len(g) for g in groups)

    base = (sprite_pages, gs_wave_pages, shot_pages, music_pages)
    tile_atlas = M72_TILE_ATLAS_SRC.read_bytes() if M72_TILE_ATLAS_SRC.exists() else b""
    atlas_pages = split_blob(tile_atlas, first_page=after(*base),
                             stem="m72_atlas") if tile_atlas else []
    title_vram = M72_TITLE_VRAM_SRC.read_bytes() if M72_TITLE_VRAM_SRC.exists() else b""
    vram_pages = split_blob(title_vram, first_page=after(*base, atlas_pages),
                            stem="m72_title_vram") if title_vram else []
    spr_atlas = M72_SPR_ATLAS_SRC.read_bytes() if M72_SPR_ATLAS_SRC.exists() else b""
    spr_atlas_pages = split_blob(spr_atlas, first_page=after(*base, atlas_pages, vram_pages),
                                 stem="m72_spratlas") if spr_atlas else []
    spriteram = M72_SPRITERAM_SRC.read_bytes() if M72_SPRITERAM_SRC.exists() else b""
    spriteram_pages = split_blob(
        spriteram, first_page=after(*base, atlas_pages, vram_pages, spr_atlas_pages),
        stem="m72_spriteram") if spriteram else []
    title_events = M72_TITLE_EVENTS_SRC.read_bytes()
    title_event_pages = split_records(
        title_events, record_size=423, records_per_page=38,
        first_page=after(*base, atlas_pages, vram_pages, spr_atlas_pages,
                          spriteram_pages), stem="m72_title_events")
    stage_bg_atlas = M72_STAGE_BG_ATLAS_SRC.read_bytes()
    stage_fg_atlas = M72_STAGE_FG_ATLAS_SRC.read_bytes()
    stage_bg_map = M72_STAGE_BG_MAP_SRC.read_bytes()
    stage_fg_map = M72_STAGE_FG_MAP_SRC.read_bytes()
    stage_events = M72_STAGE_EVENTS_SRC.read_bytes()
    arcade_bg_full = ARCADE_BG_SRC.read_bytes()
    if hashlib.sha256(arcade_bg_full).hexdigest() != ARCADE_BG_SHA256:
        raise SystemExit("HQ-фон игрового интерфейса v002 не совпал с зафиксированным")
    arcade_bg = arcade_bg_full[-640 * 30 * 2:]
    stage_bg_atlas_pages = split_blob(
        stage_bg_atlas,
        first_page=after(*base, atlas_pages, vram_pages, spr_atlas_pages,
                         spriteram_pages, title_event_pages),
        stem="m72_stage_bg_atlas")
    stage_fg_atlas_pages = split_blob(
        stage_fg_atlas,
        first_page=after(*base, atlas_pages, vram_pages, spr_atlas_pages,
                         spriteram_pages, title_event_pages,
                         stage_bg_atlas_pages),
        stem="m72_stage_fg_atlas")
    stage_bg_map_pages = split_blob(
        stage_bg_map,
        first_page=after(*base, atlas_pages, vram_pages, spr_atlas_pages,
                         spriteram_pages, title_event_pages,
                         stage_bg_atlas_pages, stage_fg_atlas_pages),
        stem="m72_stage_bg_map")
    stage_fg_map_pages = split_blob(
        stage_fg_map,
        first_page=after(*base, atlas_pages, vram_pages, spr_atlas_pages,
                         spriteram_pages, title_event_pages,
                         stage_bg_atlas_pages, stage_fg_atlas_pages,
                         stage_bg_map_pages),
        stem="m72_stage_fg_map")
    stage_event_pages = split_blob(
        stage_events,
        first_page=after(*base, atlas_pages, vram_pages, spr_atlas_pages,
                         spriteram_pages, title_event_pages,
                         stage_bg_atlas_pages, stage_fg_atlas_pages,
                         stage_bg_map_pages,
                         stage_fg_map_pages), stem="m72_stage_events")
    arcade_bg_pages = split_blob(
        arcade_bg,
        first_page=after(*base, atlas_pages, vram_pages, spr_atlas_pages,
                         spriteram_pages, title_event_pages,
                         stage_bg_atlas_pages, stage_fg_atlas_pages,
                         stage_bg_map_pages,
                         stage_fg_map_pages, stage_event_pages),
        stem="arcade_bg")
    target_pack = TARGET_PACK_SRC.read_bytes()
    if (not target_pack.startswith(b"RTZ2") or
            not target_pack or len(target_pack) % PAGE_SIZE):
        raise SystemExit("bootstrap Stage 1 pack отсутствует или повреждён")
    target_pack_prefix_end = after(
        *base, atlas_pages, vram_pages, spr_atlas_pages, spriteram_pages,
        title_event_pages, stage_bg_atlas_pages,
        stage_fg_atlas_pages, stage_bg_map_pages, stage_fg_map_pages,
        stage_event_pages, arcade_bg_pages)
    if target_pack_prefix_end > TARGET_PACK_BASE_PAGE:
        raise SystemExit(
            "ассеты перед active stage window дошли до страницы "
            f"${target_pack_prefix_end:02X}, предел ${TARGET_PACK_BASE_PAGE:02X}")
    # Окно RTZ2 намеренно начинается с фиксированной #49. Размер title может
    # меняться, но FAT32/DMA-loader и восемь отдельных PAK всегда коммитят в
    # один адрес. Свободные #46…#48 — безопасный резерв, а не потерянный RAM_G.
    target_pack_pages = split_blob(
        target_pack, first_page=TARGET_PACK_BASE_PAGE,
        stem="rtype_target_pack")
    if target_pack_pages[-1][0] > 0x76:
        raise SystemExit(
            "bootstrap stage вышел за active-stage window: "
            f"${target_pack_pages[-1][0]:02X} > $76")
    if not PYTHON_ASSET_MANIFEST.exists():
        raise SystemExit(
            "нет HQ asset manifest — сначала rtype_python_translator.py")
    hq_manifest = json.loads(PYTHON_ASSET_MANIFEST.read_text(encoding="utf-8"))
    hq_sprite = next((
        artifact for artifact in hq_manifest.get("artifacts", ())
        if artifact.get("kind") == "sprite-bootstrap-working-set"
    ), None)
    if hq_sprite is None:
        raise SystemExit("HQ asset manifest не содержит sprite bootstrap")
    hq_raw_path = ROOT / str(hq_sprite["path"])
    hq_compressed_info = hq_sprite.get("compressed", {})
    hq_lookup_info = hq_sprite.get("lookup", {})
    hq_template_info = hq_sprite.get("templates", {})
    hq_append_info = hq_template_info.get("append", {})
    hq_compressed_path = ROOT / str(hq_compressed_info.get("path", ""))
    hq_lookup_path = ROOT / str(hq_lookup_info.get("path", ""))
    hq_template_path = ROOT / str(hq_template_info.get("path", ""))
    hq_append_path = ROOT / str(hq_append_info.get("path", ""))
    try:
        hq_raw = hq_raw_path.read_bytes()
        hq_compressed = hq_compressed_path.read_bytes()
        hq_lookup = hq_lookup_path.read_bytes()
        hq_templates = hq_template_path.read_bytes()
        hq_append = hq_append_path.read_bytes()
    except OSError as exc:
        raise SystemExit(f"не читается Python HQ sprite set: {exc}") from exc
    if (len(hq_raw) != int(hq_sprite["size"]) or
            hashlib.sha256(hq_raw).hexdigest() != hq_sprite["sha256"]):
        raise SystemExit("Python HQ sprite bytes не совпали с asset manifest")
    if (len(hq_compressed) != int(hq_compressed_info["size"]) or
            len(hq_compressed) & 3 or
            hashlib.sha256(hq_compressed).hexdigest() !=
            hq_compressed_info["sha256"]):
        raise SystemExit("Python HQ zlib stream не совпал с asset manifest")
    zlib_size = int(hq_compressed_info.get("zlib_size", len(hq_compressed)))
    append_ram_g = int(hq_append_info.get("ram_g_base", -1))
    expected_append_ram_g = (
        int(hq_sprite["ram_g_base"]) + len(hq_raw) + 3) & ~3
    if (len(hq_append) != int(hq_append_info.get("size", -1)) or
            hashlib.sha256(hq_append).hexdigest() !=
            hq_append_info.get("sha256") or
            append_ram_g != expected_append_ram_g):
        raise SystemExit("Python HQ CMD_APPEND pack не совпал с asset manifest")
    append_padding = append_ram_g - (
        int(hq_sprite["ram_g_base"]) + len(hq_raw))
    hq_inflate = hq_raw + bytes(append_padding) + hq_append
    if zlib.decompress(hq_compressed[:zlib_size]) != hq_inflate:
        raise SystemExit(
            "Python HQ zlib не восстанавливает pixels+CMD_APPEND pack")
    if (len(hq_lookup) != int(hq_lookup_info["size"]) or
            hashlib.sha256(hq_lookup).hexdigest() != hq_lookup_info["sha256"]):
        raise SystemExit("Python HQ lookup не совпал с asset manifest")
    if (len(hq_templates) != int(hq_template_info["size"]) or
            hashlib.sha256(hq_templates).hexdigest() !=
            hq_template_info["sha256"]):
        raise SystemExit("Python HQ templates не совпали с asset manifest")
    hq_sprite_pages = split_blob(
        hq_compressed,
        first_page=target_pack_pages[-1][0] + 1,
        stem="rtype_python_hq_sprites",
    )
    if hq_sprite_pages[-1][0] > 0x76:
        raise SystemExit(
            "HQ sprite bootstrap вышел за active-stage window: "
            f"${hq_sprite_pages[-1][0]:02X} > $76")
    if PYTHON_HQ_LOOKUP_OFFSET + len(hq_lookup) > PYTHON_HQ_TEMPLATE_OFFSET:
        raise SystemExit("Python HQ lookup пересёк начало template table")
    if PYTHON_HQ_TEMPLATE_OFFSET + len(hq_templates) > PAGE_SIZE:
        raise SystemExit("Python HQ templates не помещаются в metadata page #EC")
    hq_lookup_page_data = bytearray(PAGE_SIZE)
    hq_lookup_page_data[
        PYTHON_HQ_LOOKUP_OFFSET:PYTHON_HQ_LOOKUP_OFFSET + len(hq_lookup)
    ] = hq_lookup
    hq_lookup_page_data[
        PYTHON_HQ_TEMPLATE_OFFSET:PYTHON_HQ_TEMPLATE_OFFSET + len(hq_templates)
    ] = hq_templates
    hq_lookup_page_path = OUT_DIR / "rtype_python_hq_lookup_page.bin"
    hq_lookup_page_path.write_bytes(hq_lookup_page_data)
    hq_lookup_pages = [(
        PYTHON_HQ_LOOKUP_PAGE, PAGE_SIZE, hq_lookup_page_path)]
    if not PYTHON_CHARGE_SRC.exists() or not PYTHON_PLAYER_MANIFEST.exists():
        raise SystemExit(
            "нет переведённой Python-анимации Beam — сначала m72_player_assets.py")
    charge_blob = PYTHON_CHARGE_SRC.read_bytes()
    player_manifest = json.loads(PYTHON_PLAYER_MANIFEST.read_text(encoding="utf-8"))
    charge_manifest = player_manifest.get("charge_binary", {})
    if (charge_manifest.get("size") != len(charge_blob) or
            charge_manifest.get("sha256") != hashlib.sha256(charge_blob).hexdigest()):
        raise SystemExit("R9_CHARGE_ARGB4444.bin не совпал с r9_pitch.json")
    charge_pages = split_blob_page_list(
        charge_blob, page_numbers=PYTHON_CHARGE_PAGES,
        stem="rtype_python_charge")
    if not PYTHON_BEAM_SRC.exists():
        raise SystemExit(
            "нет команд Beam — сначала rtype_python_translator.py")
    beam_blob = PYTHON_BEAM_SRC.read_bytes()
    if not beam_blob or len(beam_blob) > PAGE_SIZE:
        raise SystemExit(
            f"Beam command blob имеет неверный размер {len(beam_blob)}")
    beam_pages = [(PYTHON_BEAM_PAGE, len(beam_blob), PYTHON_BEAM_SRC)]
    packed_sprite_rom = M72_SPRITE_INDEX4_SRC.read_bytes()
    sprite_raw = unpack_index4(packed_sprite_rom)
    if len(sprite_raw) != SPRITE_RAW_PAGE_COUNT * PAGE_SIZE:
        raise SystemExit(
            "распакованный sprite ROM должен занимать ровно 1 МБ, получено "
            f"{len(sprite_raw)} Б")
    if len(SPRITE_RAW_PAGES) != SPRITE_RAW_PAGE_COUNT:
        raise SystemExit("карта sprite ROM должна содержать ровно 64 pages")
    sprite_raw_pages = split_blob_page_list(
        sprite_raw, page_numbers=SPRITE_RAW_PAGES, stem="rtype_sprite_raw")
    if not PYTHON_TRANSLATION_SRC.exists():
        raise SystemExit("нет LUT активного Python — сначала rtype_python_translator.py")
    python_translation_pages = split_blob(
        PYTHON_TRANSLATION_SRC.read_bytes(), first_page=0xE7,
        stem="python_translation")
    if not PYTHON_COMPILED_SRC.exists() or not PYTHON_COMPILER_REPORT.exists():
        raise SystemExit(
            "нет скомпилированного Python Z80 bank — сначала "
            "rtype_python_translator.py")
    compiler_report = json.loads(
        PYTHON_COMPILER_REPORT.read_text(encoding="utf-8"))
    compiled_blob = PYTHON_COMPILED_SRC.read_bytes()
    compiled_page = int(compiler_report["target"]["code_page"])
    if len(compiled_blob) != PAGE_SIZE:
        raise SystemExit(
            f"Python Z80 bank имеет размер {len(compiled_blob)}, ожидалось {PAGE_SIZE}")
    if hashlib.sha256(compiled_blob).hexdigest() != compiler_report["binary_sha256"]:
        raise SystemExit("Python Z80 bank не совпал с compiler report")
    python_compiled_pages = [(compiled_page, len(compiled_blob),
                              PYTHON_COMPILED_SRC)]

    def page_numbers(group: list[tuple[int, int, Path]]) -> tuple[int, ...]:
        return tuple(page for page, _, _ in group)

    concrete_page_count = validate_spg_page_layout([
        ("fixed-tables", "fixed-tables", (0x00,)),
        ("core-slot1", "core-slot1", (0x05,)),
        ("core-slot2", "core-slot2", (0x06,)),
        ("object-code", "object-code", (0x0A, 0x0B, 0x0C, 0x0D)),
        ("loader-code", "loader-code", (0x0E,)),
        ("startup-sprites", "bootstrap-assets", page_numbers(sprite_pages)),
        ("gs-wave", "bootstrap-assets", page_numbers(gs_wave_pages)),
        ("gs-shot", "bootstrap-assets", page_numbers(shot_pages)),
        ("tsfm-music", "bootstrap-assets", page_numbers(music_pages)),
        ("title-tile-atlas", "bootstrap-assets", page_numbers(atlas_pages)),
        ("title-vram", "bootstrap-assets", page_numbers(vram_pages)),
        ("title-sprite-atlas", "bootstrap-assets", page_numbers(spr_atlas_pages)),
        ("title-sprite-ram", "bootstrap-assets", page_numbers(spriteram_pages)),
        ("title-events", "bootstrap-assets", page_numbers(title_event_pages)),
        ("stage-bg-atlas", "bootstrap-assets", page_numbers(stage_bg_atlas_pages)),
        ("stage-fg-atlas", "bootstrap-assets", page_numbers(stage_fg_atlas_pages)),
        ("stage-bg-map", "bootstrap-assets", page_numbers(stage_bg_map_pages)),
        ("stage-fg-map", "bootstrap-assets", page_numbers(stage_fg_map_pages)),
        ("stage-events", "bootstrap-assets", page_numbers(stage_event_pages)),
        ("hud", "bootstrap-assets", page_numbers(arcade_bg_pages)),
        ("active-stage", "active-stage", page_numbers(target_pack_pages)),
        ("python-hq-sprites", "active-stage", page_numbers(hq_sprite_pages)),
        ("python-hq-lookup", "sprite-metadata", page_numbers(hq_lookup_pages)),
        ("sprite-rom", "sprite-rom", page_numbers(sprite_raw_pages)),
        ("collision-code", "collision-code", (0xE5,)),
        ("fixed-player-code", "fixed-player-code", (0xE6,)),
        ("python-lut", "python-lut", page_numbers(python_translation_pages)),
        ("python-charge", "charge-beam-assets", page_numbers(charge_pages)),
        ("python-beam", "charge-beam-assets", page_numbers(beam_pages)),
        ("compiler-code", "compiler-code", page_numbers(python_compiled_pages)),
    ])
    # Спрайты R-9 теперь включают полный Python-набор pitch/launch и занимают
    # больше прежнего frame-900 blob. Оставляем им отдельное окно до #018000,
    # а неизменяемый тайловый атлас начинаем с фиксированного #020000. Так его
    # адрес не плавает при добавлении объектов и World scratch #018000/#01C000
    # не повреждает title tiles. Большой title-font ниже всё равно пересекается
    # с игровыми texture windows и штатно восстанавливается при выходе в title.
    if len(sprite_blob) > 0x018000:
        raise SystemExit(
            f"M72 sprite blob {len(sprite_blob)} Б вышел за окно #000000…#017FFF")
    atlas_ramg = 0x020000
    spr_atlas_ramg = atlas_ramg + len(tile_atlas)
    stage_bg_atlas_ramg = spr_atlas_ramg + len(spr_atlas)
    stage_fg_atlas_ramg = stage_bg_atlas_ramg + len(stage_bg_atlas)
    if stage_fg_atlas_ramg + len(stage_fg_atlas) > RAM_G_SIZE:
        raise SystemExit(
            f"RAM_G overflow: атласы занимают {stage_fg_atlas_ramg + len(stage_fg_atlas)} "
            f"> {RAM_G_SIZE}")
    # После смены сцены title-font освобождён. HUD занимает зазор перед двумя
    # 512x512 index8 terrain textures, не пересекая текущий stage atlas.
    arcade_bg_ramg = 0x036000
    if arcade_bg_ramg + len(arcade_bg) > 0x040000:
        raise SystemExit("HUD-панель пересекает background terrain texture")

    lines = [
        "; ═══ СГЕНЕРИРОВАНО split_sprites.py — не редактировать вручную ═══",
        "; Блок спрайтов M72: страница и длина; загрузка начинается с RAM_G 0.",
        "",
        f"M72_SPR_PAGE_COUNT  EQU {len(sprite_pages)}",
        "M72SpritePageTable:",
    ]
    for page, size, _ in sprite_pages:
        lines.append(f"                DEFB ${page:02X}")
        lines.append(f"                DEFW {size}")
    lines.extend(
        [
            "",
            "; Полученное из MAME беззнаковое 8-битное моно PCM 11025 Гц для General Sound.",
            f"GS_WAVE_RAW_SIZE    EQU {len(gs_wave)}",
            f"GS_WAVE_PAGE_COUNT  EQU {len(gs_wave_pages)}",
            "GSWavePageTable:",
        ]
    )
    for page, size, _ in gs_wave_pages:
        lines.append(f"                DEFB ${page:02X}")
        lines.append(f"                DEFW {size}")
    if shot_pages:
        lines.extend([
            "",
            "; Обычный выстрел R-9 (звуковая команда игры $30), снят изолированно.",
            f"GS_SHOT_RAW_SIZE    EQU {len(gs_shot)}",
            f"GS_SHOT_PAGE_COUNT  EQU {len(shot_pages)}",
            "GSShotPageTable:",
        ])
        for page, size, _ in shot_pages:
            lines.append(f"                DEFB ${page:02X}")
            lines.append(f"                DEFW {size}")
    if music_pages:
        lines.extend(
            [
                "",
                "; Музыка Stage 1 для TurboSound FM (2×YM2203): поток"
                " «пауза/счётчик/чип,регистр,значение».",
                f"TSFM_MUSIC_SIZE       EQU {len(tsfm_music)}",
                f"TSFM_MUSIC_PAGE_COUNT EQU {len(music_pages)}",
                "TsfmMusicPageTable:",
            ]
        )
        for page, size, _ in music_pages:
            lines.append(f"                DEFB ${page:02X}")
            lines.append(f"                DEFW {size}")
    # Таблицы страниц для загрузчиков видеотракта. Каждая группа обязана иметь
    # и таблицу здесь, и блок в spgbld.ini — иначе Z80 замапит несуществующую
    # страницу и прочитает мусор.
    def emit_group(title, prefix, table, blob, pages, ramg=None):
        if not pages:
            return
        lines.append("")
        lines.append("; " + title)
        if ramg is not None:
            lines.append(f"{prefix}_RAMG       EQU ${ramg:06X}")
        lines.append(f"{prefix}_SIZE       EQU {len(blob)}")
        lines.append(f"{prefix}_PAGE_COUNT EQU {len(pages)}")
        lines.append(table + ":")
        for page, size, _ in pages:
            lines.append(f"                DEFB ${page:02X}")
            lines.append(f"                DEFW {size}")

    emit_group("Атлас глифов M72: тайлы 8x8 из ROM, увеличенные офлайн.",
               "M72_ATLAS", "M72AtlasPageTable", tile_atlas, atlas_pages, atlas_ramg)
    emit_group("Тайловая память титула: карта 64x64, на тайл два слова.",
               "M72_TVRAM", "M72TitleVramPageTable", title_vram, vram_pages)
    emit_group("Спрайтовые ячейки M72: логотип титульного экрана.",
               "M72_SPRATLAS", "M72SprAtlasPageTable", spr_atlas, spr_atlas_pages,
               spr_atlas_ramg)
    emit_group("Sprite RAM титульного экрана — структура оригинала.",
               "M72_SPRRAM", "M72SpriteRamPageTable", spriteram, spriteram_pages)
    emit_group("Покадровые состояния самостоятельного Python-title.",
               "M72_TITLE_EVENTS", "M72TitleEventPageTable",
               title_events, title_event_pages)
    lines.extend([
        "M72_TITLE_PACKET_SIZE EQU 423",
        "M72_TITLE_PACKETS_PER_PAGE EQU 38",
        f"M72_TITLE_FRAME_COUNT EQU {len(title_events) // 423}",
        "M72_TITLE_GLYPH_STATE_SIZE EQU 35",
    ])
    emit_group("Stage 1: задний tile-проход после полного HQ-апскейла слоя.",
               "M72_STAGE_BG_ATLAS", "M72StageBgAtlasPageTable",
               stage_bg_atlas, stage_bg_atlas_pages, stage_bg_atlas_ramg)
    emit_group("Stage 1: передний tile-проход после полного HQ-апскейла слоя.",
               "M72_STAGE_FG_ATLAS", "M72StageFgAtlasPageTable",
               stage_fg_atlas, stage_fg_atlas_pages, stage_fg_atlas_ramg)
    emit_group("Stage 1: 64x32 word-map слотов заднего прохода.",
               "M72_STAGE_BG_MAP", "M72StageBgMapPageTable",
               stage_bg_map, stage_bg_map_pages)
    emit_group("Stage 1: 64x32 word-map слотов переднего прохода.",
               "M72_STAGE_FG_MAP", "M72StageFgMapPageTable",
               stage_fg_map, stage_fg_map_pages)
    emit_group("Stage 1: точные пакеты MAME VRAM-delta для runtime replay.",
               "M72_STAGE_EVENTS", "M72StageEventPageTable",
               stage_events, stage_event_pages)
    emit_group("Игровой интерфейс v002: нижняя RGB565 HUD-панель 640x30.",
               "ARCADE_BG", "ArcadeBgPageTable",
               arcade_bg, arcade_bg_pages, arcade_bg_ramg)
    emit_group("Bootstrap Z80 pack: общие таблицы и Stage 1; Stage 2…8 идут с SD.",
               "RTYPE_TARGET_PACK", "RTypeTargetPackPageTable",
               target_pack, target_pack_pages)
    lines.extend([
        "",
        "; Точные Python HQ sprite cells лежат подряд: таблица страниц не нужна.",
        f"RTYPE_PY_HQ_SPRITE_RAMG_BASE EQU ${int(hq_sprite['ram_g_base']):06X}",
        "; Совместимое имя старого uploader-а; это адрес распакованных pixels.",
        "RTYPE_PY_HQ_SPRITE_ZLIB_RAMG EQU RTYPE_PY_HQ_SPRITE_RAMG_BASE",
        f"RTYPE_PY_HQ_SPRITE_ZLIB_SIZE EQU {len(hq_compressed)}",
        f"RTYPE_PY_HQ_SPRITE_ZLIB_PAGE_COUNT EQU {len(hq_sprite_pages)}",
        f"RTYPE_PY_HQ_SPRITE_ZLIB_FIRST_PAGE EQU #{hq_sprite_pages[0][0]:02X}",
        f"RTYPE_PY_HQ_SPRITE_RAW_SIZE EQU {len(hq_raw)}",
        f"RTYPE_PY_HQ_INFLATE_RAW_SIZE EQU {len(hq_inflate)}",
        f"RTYPE_PY_HQ_APPEND_RAMG EQU ${append_ram_g:06X}",
        f"RTYPE_PY_HQ_APPEND_SIZE EQU {len(hq_append)}",
        f"RTYPE_PY_HQ_APPEND_BLOB_COUNT EQU {int(hq_append_info['blob_count'])}",
        f"RTYPE_PY_HQ_LOOKUP_PAGE EQU #{PYTHON_HQ_LOOKUP_PAGE:02X}",
        f"RTYPE_PY_HQ_LOOKUP_PTR EQU #{0xC000 + PYTHON_HQ_LOOKUP_OFFSET:04X}",
        f"RTYPE_PY_HQ_LOOKUP_SIZE EQU {len(hq_lookup)}",
        f"RTYPE_PY_HQ_LOOKUP_COUNT EQU {int(hq_lookup_info['record_count'])}",
        f"RTYPE_PY_HQ_LOOKUP_REC_SIZE EQU {int(hq_lookup_info['record_size'])}",
        f"RTYPE_PY_HQ_TEMPLATE_PTR EQU #{0xC000 + PYTHON_HQ_TEMPLATE_OFFSET:04X}",
        f"RTYPE_PY_HQ_TEMPLATE_SIZE EQU {len(hq_templates)}",
        f"RTYPE_PY_HQ_TEMPLATE_COUNT EQU {int(hq_template_info['record_count'])}",
        f"RTYPE_PY_HQ_TEMPLATE_REC_SIZE EQU {int(hq_template_info['record_size'])}",
        f"RTYPE_PY_HQ_TEMPLATE_CELL_COUNT EQU {int(hq_template_info['cell_count'])}",
        f"RTYPE_PY_HQ_TEMPLATE_CELL_SIZE EQU {int(hq_template_info['cell_record_size'])}",
    ])
    emit_group("Анимация накопления Beam из активной Python-версии.",
               "RTYPE_PY_CHARGE", "RTypePyChargePageTable",
               charge_blob, charge_pages, 0x02C000)
    lines.extend([
        "ARCADE_BG_WIDTH  EQU 640",
        "ARCADE_BG_HEIGHT EQU 30",
        "ARCADE_BG_STRIDE EQU 1280",
        f"RTYPE_TARGET_PACK_BASE_PAGE EQU ${target_pack_pages[0][0]:02X}",
        "",
        "; Полный распакованный M72 sprite ROM: 128 chunks по 8 КБ.",
        f"RTYPE_SPRITE_RAW_PAGE_COUNT EQU {len(sprite_raw_pages)}",
        "RTypeSpriteRawPageTable:",
    ])
    lines.extend(
        f"                DEFB ${page:02X}" for page, _, _ in sprite_raw_pages)
    OUT_INC.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Конфигурация spgbld генерируется здесь же: число страниц зависит от размера блока,
    # и вручную поддерживать список Block-строк — гарантированный рассинхрон.
    ini = [INI_HEAD]
    ini.append("\n; Код, скомпилированный из Python AST через typed IR и SDCC.\n")
    for page, _, out in python_compiled_pages:
        ini.append(f"Block = #0000, #{page:02X}, Build/{out.name}\n")
    for page, _, out in python_translation_pages:
        ini.append(f"Block = #0000, #{page:02X}, Build/{out.name}\n")
    for page, _, out in sprite_pages:
        ini.append(f"Block = #0000, #{page:02X}, Build/{out.name}\n")
    ini.append("\n; Полученный из MAME звук: беззнаковое 8-битное моно 11025 Гц для General Sound.\n")
    for page, _, out in gs_wave_pages:
        ini.append(f"Block = #0000, #{page:02X}, Build/{out.name}\n")
    if music_pages:
        ini.append("\n; Музыка Stage 1 для TurboSound FM (2×YM2203).\n")
        for page, _, out in music_pages:
            ini.append(f"Block = #0000, #{page:02X}, Build/{out.name}\n")
    # Каждая нарезанная группа обязана попасть в SPG: таблица в .inc без блока
    # здесь означает, что Z80 замапит несуществующую страницу и прочитает мусор.
    for title, pages in (
        ("Обычный выстрел R-9 для General Sound (22050 Гц).", shot_pages),
        ("Атлас глифов M72 (тайлы из ROM).", atlas_pages),
        ("Тайловая память титульного экрана.", vram_pages),
        ("Спрайтовые ячейки M72 (логотип титула).", spr_atlas_pages),
        ("Sprite RAM титульного экрана.", spriteram_pages),
        ("Покадровые состояния самостоятельного Python-title.", title_event_pages),
        ("Stage 1: HQ-атлас заднего tile-прохода.", stage_bg_atlas_pages),
        ("Stage 1: HQ-атлас переднего tile-прохода.", stage_fg_atlas_pages),
        ("Stage 1: карта заднего tile-прохода.", stage_bg_map_pages),
        ("Stage 1: карта переднего tile-прохода.", stage_fg_map_pages),
        ("Stage 1: поток MAME VRAM-delta.", stage_event_pages),
        ("Игровой интерфейс v002: RGB565 HUD-панель 640x30.", arcade_bg_pages),
        ("Bootstrap World-данные Stage 1; остальные levels загружаются с SD.",
         target_pack_pages),
        ("Точные Python HQ sprite cells, zlib для FT812 CMD_INFLATE.",
         hq_sprite_pages),
        ("Lookup точных Python HQ sprite cells в metadata page #EC.",
         hq_lookup_pages),
        ("Анимация накопления Beam активной Python-версии.", charge_pages),
        ("FT812 command strips для Python Beam.", beam_pages),
        ("Полный M72 sprite ROM index8 для прямого TS DMA в RAM_G.",
         sprite_raw_pages),
    ):
        if not pages:
            continue
        ini.append("\n; " + title + "\n")
        for page, _, out in pages:
            ini.append(f"Block = #0000, #{page:02X}, Build/{out.name}\n")
    OUT_INI.write_text("".join(ini), encoding="utf-8")

    for page, size, out in sprite_pages:
        print(f"страница ${page:02X}: {size:6d} Б  ->  {out.name}")
    for page, size, out in gs_wave_pages:
        print(f"страница ${page:02X}: {size:6d} Б  ->  {out.name}")
    print(f"ini: {OUT_INI}")
    print(
        f"RAM_G: m72_sprites={len(sprite_blob)} Б, "
        f"все активные атласы={stage_fg_atlas_ramg + len(stage_fg_atlas)} Б"
    )
    print(f"RAM_G: arcade_bg=${arcade_bg_ramg:06X}, {len(arcade_bg)} Б")
    print(
        f"bootstrap Stage 1 pack: {len(target_pack)} Б, страницы "
        f"${target_pack_pages[0][0]:02X}…${target_pack_pages[-1][0]:02X}"
    )
    print(
        f"Python HQ sprites: {len(hq_raw)} Б -> {len(hq_compressed)} Б, страницы "
        f"${hq_sprite_pages[0][0]:02X}…${hq_sprite_pages[-1][0]:02X}; "
        f"CMD_APPEND {len(hq_append)} Б; "
        f"lookup/templates page ${PYTHON_HQ_LOOKUP_PAGE:02X}"
    )
    print(
        f"sprite ROM index8: {len(sprite_raw)} Б, страницы "
        f"${sprite_raw_pages[0][0]:02X}…${sprite_raw_pages[-1][0]:02X}"
    )
    print(f"m72_sprites sha256: {sprite_sha256}")
    print(f"gs_wave sha256:     {gs_wave_sha256}")
    print(
        f"memory layout: {concrete_page_count} concrete pages checked; "
        "FT812 queue/template #ED..#EF reserved"
    )
    print(f"inc: {OUT_INC}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
