#!/usr/bin/env python3
"""Прогон сборки в Z80+FT812-симуляторе: докуда доходит старт и что уходит в FT812.

Симулятор берётся из соседнего проекта HMM2 (project-agnostic модель TS-Config +
FT812). Это НЕ источник истины по картинке — им остаётся bt8xxemu в Unreal, — но
он отвечает на главные вопросы отладки старта: выполняется ли код, встал ли
видеорежим, дошло ли дело до сборки кадра.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HMM2_TOOLS = (ROOT.parent / "HMM2" / "Pre-releases" /
              "v020-2026-07-16-adventure-ui-battle-ai-reference" /
              "Source" / "Tools")
sys.path.insert(0, str(HMM2_TOOLS))

from tsconf_ft812_sim import TSConfFT812Machine, parse_sym  # noqa: E402

REG_HSIZE = 0x302034
REG_VSIZE = 0x302048
REG_DLSWAP = 0x302054
REG_PCLK = 0x302070


def main() -> int:
    sym = parse_sym(ROOT / "Build" / "rtype.sym")
    machine = TSConfFT812Machine(
        ROOT,
        spgbld_path=ROOT / "spgbld_rtype.ini",
        sym_path=ROOT / "Build" / "rtype.sym",
        load_spg=True,
    )
    if machine.errors:
        print("ошибки загрузки SPG:", machine.errors)

    print(f"старт: PC=${machine.reg.PC:04X} SP=${machine.reg.SP:04X}")

    # Контрольные точки старта в порядке их прохождения.
    checkpoints = [
        ("Platform_Init", sym.get("Platform_Init")),
        ("Init_Video", sym.get("Init_Video")),
        ("M72Sprites_Upload", sym.get("M72Sprites_Upload")),
        ("ArcadeGame_Init", sym.get("ArcadeGame_Init")),
        ("MainLoop", sym.get("MainLoop")),
        ("Render_Frame", sym.get("Render_Frame")),
    ]
    for name, addr in checkpoints:
        if addr is None:
            print(f"{name:16s} — нет в .sym")
            continue
        try:
            steps = machine.run_until_pc(addr, max_steps=40_000_000)
        except Exception as exc:  # noqa: BLE001
            print(f"{name:16s} НЕ ДОСТИГНУТ: {exc}")
            print(f"                 PC=${machine.reg.PC:04X}")
            return 1
        print(f"{name:16s} достигнут за {steps} шагов")

    # Досчитать кадр до ожидания свапа — к этому моменту буфер команд уже отправлен.
    wait_pc = sym.get("Render_Frame.waitDLSwap")
    if wait_pc is not None:
        machine.run_until_pc(wait_pc, max_steps=20_000_000)

    ft = machine.ft
    sprite_src = (
        ROOT
        / "Assets"
        / "Converted"
        / "Arcade"
        / "Sprites"
        / "RTYPE_M72_FRAME900_ARGB4444.bin"
    ).read_bytes()
    sprite_base = sym["M72_SPR_BLOB_BASE"]
    title_tiles_src = (
        ROOT / "Assets" / "Converted" / "Arcade" / "Atlas"
        / "TILE_ATLAS_ARGB4444.bin"
    ).read_bytes()
    title_sprites_src = (
        ROOT / "Assets" / "Converted" / "Arcade" / "Atlas"
        / "TITLE_FONT_ARGB4444.bin"
    ).read_bytes()
    title_tiles_base = sym["M72_ATLAS_RAMG"]
    title_sprites_base = sym["M72_SPRATLAS_RAMG"]
    sprite_ramg = bytes(ft.ram_g[sprite_base:sprite_base + len(sprite_src)])
    title_tiles_ramg = bytes(
        ft.ram_g[title_tiles_base:title_tiles_base + len(title_tiles_src)])
    title_sprites_ramg = bytes(
        ft.ram_g[title_sprites_base:title_sprites_base + len(title_sprites_src)])
    sprite_ok = sprite_ramg == sprite_src
    title_tiles_ok = title_tiles_ramg == title_tiles_src
    title_sprites_ok = title_sprites_ramg == title_sprites_src
    game_mode_ok = machine.get_byte(sym["GameMode"]) == 0

    # Проверить сам Z80-загрузчик интерфейса v002 отдельно от ожидания START.
    # Это та же подпрограмма, которую Title_Update вызывает при смене сцены.
    machine.call(sym["ArcadeBackground_Upload"], max_steps=50_000_000)
    arcade_bg_full = (
        ROOT / "Assets" / "Converted" / "Arcade" / "Stage1"
        / "STAGE1_FRAME0900_TILES_640x480_RGB565.bin"
    ).read_bytes()
    arcade_bg_src = arcade_bg_full[-sym["ARCADE_BG_SIZE"]:]
    arcade_bg_base = sym["ARCADE_BG_RAMG"]
    arcade_bg_ramg = bytes(
        ft.ram_g[arcade_bg_base:arcade_bg_base + len(arcade_bg_src)])
    arcade_bg_ok = arcade_bg_ramg == arcade_bg_src
    print(f"\nRAM_G M72 sprites byte-exact: {sprite_ok}, "
          f"sha256={hashlib.sha256(sprite_ramg).hexdigest()}")
    print(f"RAM_G title tiles byte-exact: {title_tiles_ok}, "
          f"sha256={hashlib.sha256(title_tiles_ramg).hexdigest()}")
    print(f"RAM_G title sprites byte-exact: {title_sprites_ok}, "
          f"sha256={hashlib.sha256(title_sprites_ramg).hexdigest()}")
    print(f"RAM_G v002 HUD 640x30 byte-exact: {arcade_bg_ok}, "
          f"sha256={hashlib.sha256(arcade_bg_ramg).hexdigest()}")
    # На старте загружен только титул. RGB565-кадр v002 загружается позднее,
    # непосредственно при переходе GameMode 0 -> 1.
    print(f"GameMode остаётся титулом: {game_mode_ok}")
    print(f"cmd_write_ptr = {ft.cmd_write_ptr}, dlswap = {ft.dlswap}")

    print("\nкоманды, отправленные копроцессору:")
    data = bytes(ft.ram_cmd[: max(ft.cmd_write_ptr, 4)])
    for i in range(0, min(len(data), 4 * 40), 4):
        word = int.from_bytes(data[i:i + 4], "little")
        print(f"  [{i // 4:3d}] ${word:08X}  {decode_cmd(word)}")
    return 0 if (sprite_ok and title_tiles_ok and title_sprites_ok
                 and arcade_bg_ok and game_mode_ok) else 1


def decode_cmd(word: int) -> str:
    """Короткая расшифровка команды DL/копроцессора — чтобы глазами видеть кадр."""
    if word & 0xFFFFFF00 == 0xFFFFFF00:
        return {0x00: "CMD_DLSTART", 0x01: "CMD_SWAP"}.get(word & 0xFF, "CMD_?")
    op = word >> 24
    names = {
        0x00: "DISPLAY", 0x01: "BITMAP_SOURCE", 0x02: "CLEAR_COLOR_RGB",
        0x04: "COLOR_RGB", 0x05: "BITMAP_HANDLE", 0x07: "BITMAP_LAYOUT",
        0x08: "BITMAP_SIZE", 0x0D: "POINT_SIZE", 0x15: "TRANSFORM_A",
        0x18: "TRANSFORM_D", 0x19: "TRANSFORM_E", 0x1F: "BEGIN",
        0x21: "END", 0x26: "CLEAR", 0x27: "VERTEX_FORMAT",
        0x28: "BITMAP_LAYOUT_H", 0x29: "BITMAP_SIZE_H",
    }
    if op & 0xC0 == 0x40:
        x = (word >> 15) & 0x7FFF
        y = word & 0x7FFF
        if x & 0x4000:
            x -= 0x8000
        if y & 0x4000:
            y -= 0x8000
        return f"VERTEX2F x={x} y={y}"
    return names.get(op, f"op {op:02X}")


if __name__ == "__main__":
    raise SystemExit(main())
