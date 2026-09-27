#!/usr/bin/env python3
"""Byte-exact проверки объектной страницы и ROM-descriptor renderer Z80."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Source" / "Python"))
sys.path.insert(0, str(ROOT / "Source" / "Tools"))
sys.path.insert(0, str(
    ROOT.parent / "HMM2" / "Pre-releases" /
    "v020-2026-07-16-adventure-ui-battle-ai-reference" /
    "Source" / "Tools"))

from rtype_port.enemies import (  # noqa: E402
    M72Rom, _direction_offset, read_descriptor,
)
from rtype_port.stage import _collision_address  # noqa: E402
from sim_world_runtime_check import install_texture_coprocessor  # noqa: E402
from tsconf_ft812_sim import TSConfFT812Machine, parse_sym  # noqa: E402


OBJECT_PAGE = 0x09
OBJECT_PHYSICAL = OBJECT_PAGE * 0x4000
OBJECT_RECORD_SIZE = 0x40
CACHE_META_PAGE = 0x0F
CELL_MAP_PHYSICAL = CACHE_META_PAGE * 0x4000
SPRITE_CELL_BYTES = 16 * 16
SPRITE_RAMG = 0x0C0000


def _bc(machine: TSConfFT812Machine) -> int:
    return (machine.reg.B << 8) | machine.reg.C


def _signed16(value: int) -> int:
    return value - 0x10000 if value & 0x8000 else value


def _call_hl(machine: TSConfFT812Machine, address: int, value: int,
             **registers: int) -> int:
    max_steps = registers.pop("max_steps", 2_000_000)
    return machine.call(
        address, h=(value >> 8) & 0xFF, l=value & 0xFF,
        max_steps=max_steps, **registers)


def _words(machine: TSConfFT812Machine, first: int, last: int) -> list[int]:
    data = bytes(machine.mem.read(address) for address in range(first, last))
    return [int.from_bytes(data[offset:offset + 4], "little")
            for offset in range(0, len(data), 4)]


def main() -> int:
    symbols = parse_sym(ROOT / "Build" / "rtype.sym")
    machine = TSConfFT812Machine(
        ROOT,
        spgbld_path=ROOT / "spgbld_rtype.ini",
        sym_path=ROOT / "Build" / "rtype.sym",
        load_spg=True,
    )
    machine.run_until_pc(symbols["MainLoop"], max_steps=40_000_000)
    rom = M72Rom()

    # Четыре 16-КБ окна ES должны читаться буквально, включая слово,
    # пересекающее pack boundary `$3FFF/$4000`.
    for address in (0x0000, 0x0001, 0x3FFE, 0x3FFF, 0x4000,
                    0x7FFF, 0x8000, 0xBFFF, 0xC000, 0xFFFE):
        _call_hl(machine, symbols["RTypeWorldRom_ReadByte"], address)
        assert machine.reg.A == rom.byte(address), hex(address)
    for address in (0x0000, 0x3FFE, 0x3FFF, 0x4000,
                    0x7FFE, 0x7FFF, 0xBFFF, 0xFFFE):
        _call_hl(machine, symbols["RTypeWorldRom_ReadWord"], address)
        actual = (machine.reg.D << 8) | machine.reg.E
        assert actual == rom.word(address), (hex(address), hex(actual))

    # Literal FIFO: при reset доступны индексы 2…95; после возврата в том же
    # порядке allocator обязан выдать ту же последовательность повторно.
    machine.call(symbols["RTypeObjects_Reset"], max_steps=1_000_000)
    assert machine.get_byte(symbols["RTYPE_OBJECT_FREE_COUNT"]) == 94
    first_pass: list[int] = []
    for expected in range(2, 96):
        machine.call(symbols["RTypeObjects_Take"], max_steps=100_000)
        assert not machine.reg.F & 1
        index = machine.reg.A
        assert index == expected
        first_pass.append(index)
        record = OBJECT_PHYSICAL + index * OBJECT_RECORD_SIZE
        assert bytes(machine.mem.physical[record:record + OBJECT_RECORD_SIZE]) == bytes(64)
        machine.mem.physical[record] = 1
        machine.mem.physical[record + 0x10] = index ^ 0x55
        machine.mem.physical[record + 0x11] = index ^ 0xAA
    machine.call(symbols["RTypeObjects_Take"], max_steps=100_000)
    assert machine.reg.F & 1
    for index in first_pass:
        machine.call(symbols["RTypeObjects_Release"], a=index,
                     max_steps=100_000)
    second_pass = []
    for expected in first_pass:
        machine.call(symbols["RTypeObjects_Take"], max_steps=100_000)
        second_pass.append(machine.reg.A)
        assert machine.get_byte(symbols["RTypeObjects_TakenXFraction"]) == (
            expected ^ 0x55)
        assert machine.get_byte(symbols["RTypeObjects_TakenYFraction"]) == (
            expected ^ 0xAA)
    assert second_pass == first_pass

    # Resource manager удерживает один type в одном palette slot и освобождает
    # его лишь после последнего reference.
    machine.call(symbols["RTypeObjects_Reset"], max_steps=1_000_000)
    for resource, expected_slot in ((0x57, 0), (0x59, 1), (0x5A, 2),
                                    (0x5C, 3), (0x0D, 4)):
        machine.call(symbols["RTypeResources_Acquire"], a=resource)
        assert machine.reg.A == expected_slot and not machine.reg.F & 1
    machine.call(symbols["RTypeResources_Acquire"], a=0x0D)
    assert machine.reg.A == 4
    machine.call(symbols["RTypeResources_Release"], a=4)
    machine.call(symbols["RTypeResources_Acquire"], a=0x0D)
    assert machine.reg.A == 4

    # Signed координаты проверяются по всей видимой области и за обоими
    # краями; Y — точное умножение на 24 без таблицы.
    for native_x in (-400, -321, -17, -1, 0, 1, 17, 319, 384, 767):
        _call_hl(machine, symbols["RTypeSprite_NativeXToVertex"],
                 native_x & 0xFFFF)
        expected = round(native_x * 64 / 3)
        assert _signed16(_bc(machine)) == expected, native_x
    for native_y in (-64, -1, 0, 1, 239, 384):
        _call_hl(machine, symbols["RTypeSprite_NativeYToVertex"],
                 native_y & 0xFFFF)
        assert _signed16(_bc(machine)) == native_y * 24, native_y

    for source_x, source_y in ((0x0140, 0x0080), (0x0200, 0x0100),
                               (0x02C0, 0x0180)):
        for target_x, target_y in ((0x0130, 0x0070), (0x0148, 0x0100),
                                   (0x0200, 0x0188), (0x02C8, 0x0078),
                                   (source_x, source_y)):
            machine.set_word(symbols["RTypeObjects_ProjectileSourceX"], source_x)
            machine.set_word(symbols["RTypeObjects_ProjectileSourceY"], source_y)
            machine.set_word(symbols["RTypePlayerNativeX"], target_x)
            machine.set_word(symbols["RTypePlayerNativeY"], target_y)
            machine.call(symbols["RTypeDirection_Offset"], max_steps=200_000)
            assert machine.reg.A == _direction_offset(
                source_x, source_y, target_x, target_y), (
                source_x, source_y, target_x, target_y, machine.reg.A)

    # `$1E6C` должен адресовать живую 16-КБ ring-карту, включая unsigned
    # horizontal wrap, vertical clamp и ненулевой foreground Y scroll.
    foreground = machine.mem.physical
    for scroll_x, scroll_y in ((0, 0), (1, 7), (63, 8), (64, 127),
                               (255, 511), (511, 3)):
        machine.set_word(symbols["RTypeWorldFgScrollQ8"] + 1, scroll_x)
        machine.set_word(symbols["RTypeWorldFgYScrollQ8"] + 1, scroll_y)
        for object_x, object_y in ((0x012C, 0x007C), (0x0140, 0x017F),
                                   (0x02C8, 0x0110), (0xFFFF, 0x0200)):
            machine.call(
                symbols["RTypeTerrain_ForegroundCode"],
                b=object_x >> 8, c=object_x & 0xFF,
                d=object_y >> 8, e=object_y & 0xFF,
                max_steps=200_000)
            address = _collision_address(
                object_x, object_y, scroll_x, scroll_y)
            offset = 0x07 * 0x4000 + address
            expected = (foreground[offset] |
                        (foreground[offset + 1] << 8)) & 0x0FFF
            actual = (machine.reg.H << 8) | machine.reg.L
            assert actual == expected, (
                scroll_x, scroll_y, object_x, object_y,
                hex(address), hex(actual), hex(expected))

    # `$1EB5` адресует независимую background ring-карту тем же алгоритмом,
    # но с собственными X/Y scroll и страницей #08.
    for scroll_x, scroll_y in ((0, 0), (7, 1), (64, 8), (255, 511)):
        machine.set_word(symbols["RTypeWorldBgScrollQ8"] + 1, scroll_x)
        machine.set_word(symbols["RTypeWorldBgYScrollQ8"] + 1, scroll_y)
        for object_x, object_y in ((0x012C, 0x007C), (0x0200, 0x0110),
                                   (0x02D3, 0x0193), (0xFFFF, 0x0200)):
            machine.call(
                symbols["RTypeTerrain_BackgroundCode"],
                b=object_x >> 8, c=object_x & 0xFF,
                d=object_y >> 8, e=object_y & 0xFF,
                max_steps=200_000)
            address = _collision_address(
                object_x, object_y, scroll_x, scroll_y)
            offset = 0x08 * 0x4000 + address
            expected = (foreground[offset] |
                        (foreground[offset + 1] << 8)) & 0x0FFF
            actual = (machine.reg.H << 8) | machine.reg.L
            assert actual == expected, (
                scroll_x, scroll_y, object_x, object_y,
                hex(address), hex(actual), hex(expected))

    install_texture_coprocessor(machine)
    # Cache metadata must never share the object page: the old #D800 map
    # overwrote #D900 FIFO/scheduler state and silently suppressed enemies.
    object_runtime_before_cache = bytes(machine.mem.physical[
        OBJECT_PHYSICAL + 0x1900:OBJECT_PHYSICAL + 0x1C00])
    machine.call(symbols["RTypeSpriteCache_Reset"], max_steps=500_000)
    assert bytes(machine.mem.physical[
        OBJECT_PHYSICAL + 0x1900:OBJECT_PHYSICAL + 0x1C00]) == \
        object_runtime_before_cache
    machine.call(symbols["RTypeSpriteCache_BeginFrame"], max_steps=500_000)
    machine.call(symbols["RTypeWorldTexture_Enable"], max_steps=500_000)
    atlas = bytearray()
    packed = (ROOT / "Assets" / "Converted" / "Arcade" /
              "RTYPE_SPRITES_INDEX4.bin").read_bytes()
    for value in packed:
        atlas.extend((value >> 4, value & 0x0F))

    # Descriptor `$28E2` — 2x2 Red Flyer. Проверяем разобранные поля, cells,
    # четыре dynamic BITMAP_SOURCE и точные VERTEX2F coordinates.
    descriptor_address = 0x28E2
    descriptor = read_descriptor(rom, descriptor_address)
    anchor_x, anchor_y, palette = 500, 200, 4
    machine.set_word(symbols["RTypeSprite_AnchorX"], anchor_x)
    machine.set_word(symbols["RTypeSprite_AnchorY"], anchor_y)
    _call_hl(machine, symbols["RTypeSprite_ReadDescriptor"],
             descriptor_address)
    assert machine.get_word(symbols["RTypeSprite_Code"]) == descriptor.code
    assert machine.get_word(symbols["RTypeSprite_Attr"]) == descriptor.attr
    assert machine.get_byte(symbols["RTypeSprite_Width"]) == descriptor.width
    assert machine.get_byte(symbols["RTypeSprite_Height"]) == descriptor.height
    assert _signed16(machine.get_word(symbols["RTypeSprite_BaseX"])) == (
        anchor_x + descriptor.dx - 320)
    assert _signed16(machine.get_word(symbols["RTypeSprite_BaseY"])) == (
        384 - (anchor_y + descriptor.dy) - descriptor.height * 16)

    _call_hl(machine, symbols["RTypeSprite_PrepareDescriptor"],
             descriptor_address, max_steps=5_000_000)
    codes = [descriptor.code + 8 * x + y
             for x in range(descriptor.width)
             for y in range(descriptor.height)]
    for code in codes:
        map_at = CELL_MAP_PHYSICAL + code * 2
        slot = (machine.mem.physical[map_at] |
                (machine.mem.physical[map_at + 1] << 8))
        assert slot != 0xFFFF
        actual = bytes(machine.ft.ram_g[
            SPRITE_RAMG + slot * SPRITE_CELL_BYTES:
            SPRITE_RAMG + (slot + 1) * SPRITE_CELL_BYTES])
        expected = bytes(atlas[
            code * SPRITE_CELL_BYTES:(code + 1) * SPRITE_CELL_BYTES])
        assert actual == expected, code

    command_buffer = symbols["RTypeFTCommandBufferStart"]
    machine.set_word(symbols["FT.Coprocessor.BufferPtr"], command_buffer)
    _call_hl(
        machine, symbols["RTypeSprite_DrawDescriptor"], descriptor_address,
        a=palette, b=(anchor_x >> 8), c=anchor_x & 0xFF,
        d=(anchor_y >> 8), e=anchor_y & 0xFF, max_steps=5_000_000)
    command_end = machine.get_word(symbols["FT.Coprocessor.BufferPtr"])
    words = _words(machine, command_buffer, command_end)
    sources = [word & 0x3FFFFF for word in words if word >> 24 == 0x01]
    vertices = [word for word in words if word >> 30 == 1]
    assert len(sources) == len(codes) == len(vertices) == 4
    assert sources == [
        SPRITE_RAMG + (
            machine.mem.physical[CELL_MAP_PHYSICAL + code * 2] |
            (machine.mem.physical[CELL_MAP_PHYSICAL + code * 2 + 1] << 8)
        ) * SPRITE_CELL_BYTES
        for code in codes
    ]
    assert any(word == 0x2A000000 | (0x01C400 + palette * 32)
               for word in words)
    expected_vertices = []
    base_x = anchor_x + descriptor.dx - 320
    base_y = 384 - (anchor_y + descriptor.dy) - descriptor.height * 16
    for cell_x in range(descriptor.width):
        for cell_y in range(descriptor.height):
            x = round((base_x + cell_x * 16) * 64 / 3) & 0x7FFF
            y = ((base_y + cell_y * 16) * 24) & 0x7FFF
            expected_vertices.append(0x40000000 | (x << 15) | y)
    assert vertices == expected_vertices

    # На collision-кадре `$E601` проверяет обе карты. Фон отдельно делаем
    # solid при пустом foreground, затем проверяем полный десятикадровый
    # `$E686` descriptor trace и освобождение resource только в конце.
    machine.call(symbols["RTypeWorld_ClearMaps"], max_steps=2_000_000)
    machine.call(symbols["RTypeObjects_ClearScratch"], max_steps=100_000)
    projectile_x, projectile_y = 0x0200, 0x0110
    machine.set_word(symbols["RTypeWorldFgScrollQ8"] + 1, 0)
    machine.set_word(symbols["RTypeWorldFgYScrollQ8"] + 1, 0)
    machine.set_word(symbols["RTypeWorldBgScrollQ8"] + 1, 0)
    machine.set_word(symbols["RTypeWorldBgYScrollQ8"] + 1, 0)
    foreground_address = _collision_address(projectile_x, projectile_y, 0, 0)
    background_address = _collision_address(projectile_x, projectile_y, 0, 0)
    foreground[0x07 * 0x4000 + foreground_address] = 0xFF
    foreground[0x07 * 0x4000 + foreground_address + 1] = 0x0F
    foreground[0x08 * 0x4000 + background_address] = 0x01
    foreground[0x08 * 0x4000 + background_address + 1] = 0x00
    scratch = symbols["RTYPE_OBJECT_SCRATCH"]
    machine.set_byte(scratch + symbols["RTYPE_OBJ_TYPE"],
                     symbols["RTYPE_OBJ_ENEMY_PROJECTILE"])
    machine.set_word(scratch + symbols["RTYPE_OBJ_X"], projectile_x)
    machine.set_word(scratch + symbols["RTYPE_OBJ_Y"], projectile_y)
    machine.set_word(scratch + symbols["RTYPE_OBJ_DESCRIPTOR"], 0x84AE)
    machine.call(symbols["RTypeResources_Acquire"], a=0x56)
    projectile_slot = machine.reg.A
    machine.set_byte(scratch + symbols["RTYPE_OBJ_PALETTE"], projectile_slot)
    machine.set_byte(scratch + symbols["RTYPE_OBJ_RESOURCE"], 0x56)
    machine.set_word(symbols["FrameCounter"], 1)
    machine.call(symbols["RTypeObjects_UpdateEnemyProjectileCore"],
                 max_steps=5_000_000)
    assert machine.get_word(
        scratch + symbols["RTYPE_OBJ_PROJECTILE_BURST"]) == 10
    expected_burst_descriptors = []
    for timer in range(10, 0, -1):
        machine.call(symbols["RTypeObjects_UpdateEnemyProjectile"],
                     max_steps=5_000_000)
        expected_descriptor = 0x8490 + (timer & 0x0E) * 3
        expected_burst_descriptors.append(expected_descriptor)
        assert machine.get_word(
            scratch + symbols["RTYPE_OBJ_DESCRIPTOR"]) == expected_descriptor
        assert machine.get_word(
            scratch + symbols["RTYPE_OBJ_PROJECTILE_BURST"]) == timer - 1
    assert machine.get_byte(scratch + symbols["RTYPE_OBJ_TYPE"]) == 0
    refs_physical = 0x09 * 0x4000 + (symbols["RTYPE_RESOURCE_REFS"] & 0x3FFF)
    assert foreground[refs_physical + projectile_slot] == 0

    print("World ROM: 4 pack pages + boundary words byte-exact")
    print("M72 object pool: FIFO 94/94 и Q8 slot residue exact")
    print("Resource manager: acquire/retain/release exact")
    print("Native coordinate conversion: signed X/Y exact")
    print("Aiming `$1D89`: 15 source/target pairs exact")
    print("Terrain collision `$1E6C/$1EB5`: FG/BG X/Y ring address exact")
    print("Descriptor $28E2: geometry, frame-safe cache cells и FT812 DL exact")
    print("Projectile `$E601/$E686`: BG collision и 10-frame burst exact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
