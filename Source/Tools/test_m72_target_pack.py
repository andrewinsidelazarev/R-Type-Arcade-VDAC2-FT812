"""Проверки полного целевого пакета всех восьми stages."""
from __future__ import annotations

import struct
import unittest

import m72_target_pack as target


class TargetPackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.pack, cls.manifest = target.build_target_pack()

    def test_header_and_directory_cover_the_complete_world(self) -> None:
        magic, version, stages, record_size, events, checkpoints, size, directory = (
            struct.unpack_from("<4sHBBHHII", self.pack, 0))
        self.assertEqual(target.MAGIC, magic)
        self.assertEqual(target.VERSION, version)
        self.assertEqual(8, stages)
        self.assertEqual(target.STAGE_RECORD_SIZE, record_size)
        self.assertEqual(788, events)
        self.assertEqual(16, checkpoints)
        self.assertEqual(len(self.pack), size)
        self.assertEqual(target.DIRECTORY_OFFSET, directory)
        self.assertEqual(0, len(self.pack) % target.PAGE_SIZE)

    def test_global_rom_and_sprite_graphics_are_byte_exact(self) -> None:
        world = self.manifest["globals"]["world_rom"]
        first = int(world["offset"])
        source = target.MAINCPU.read_bytes()[0x10000:0x20000]
        self.assertEqual(source, self.pack[first:first + int(world["size"])])
        self.assertEqual(0, first % target.PAGE_SIZE)

        sprites = self.manifest["globals"]["sprites"]
        first = int(sprites["offset"])
        magic, count, record_size, raw_size, _ = struct.unpack_from(
            "<4sHHII", self.pack, first)
        self.assertEqual(target.SPRITE_TEXTURE_MAGIC, magic)
        self.assertEqual(target.SPRITE_TEXTURE_RECORD_SIZE, record_size)
        expected = target._unpack_index4(target.SPRITES.read_bytes())
        self.assertEqual(len(expected), raw_size)
        rebuilt = bytearray()
        for index in range(count):
            relative, size = struct.unpack_from(
                "<IH", self.pack,
                first + target.SPRITE_TEXTURE_HEADER_SIZE +
                index * target.SPRITE_TEXTURE_RECORD_SIZE)
            self.assertLessEqual(relative % target.PAGE_SIZE + size,
                                 target.PAGE_SIZE)
            rebuilt += target.zlib.decompress(
                self.pack[first + relative:first + relative + size])
        self.assertEqual(expected, bytes(rebuilt))

    def test_stage_palettes_follow_rom_5541_lists(self) -> None:
        maincpu = target.MAINCPU.read_bytes()
        for stage in self.manifest["stages"]:
            section = stage["tile_palette"]
            expected = target._tile_palette_tables(
                maincpu, int(section["config_index"]))
            first = int(section["offset"])
            self.assertEqual(expected,
                             self.pack[first:first + int(section["size"])])

    def test_tile_palette_uses_the_second_rgb_rom_bank(self) -> None:
        maincpu = target.MAINCPU.read_bytes()
        table = target._tile_palette_tables(maincpu, 1)
        red, green, blue = maincpu[
            0x3B000 + 0x2400 + 0x11 * 48 + 3:
            0x3B000 + 0x2400 + 0x11 * 48 + 6]
        expected = (0xF000 | (((red * 15 + 15) // 31) << 8) |
                    (((green * 15 + 15) // 31) << 4) |
                    ((blue * 15 + 15) // 31))
        self.assertEqual(expected, struct.unpack_from("<H", table, 34)[0])

    def test_sprite_palette_uses_the_first_rgb_rom_bank(self) -> None:
        maincpu = target.MAINCPU.read_bytes()
        table = target._tile_palette_tables(maincpu, 1)
        red, green, blue = maincpu[
            0x3B000 + 0x11 * 48 + 3:
            0x3B000 + 0x11 * 48 + 6]
        expected = (0xF000 | (((red * 15 + 15) // 31) << 8) |
                    (((green * 15 + 15) // 31) << 4) |
                    ((blue * 15 + 15) // 31))
        self.assertEqual(
            expected, struct.unpack_from("<H", table, 1024 + 34)[0])
        self.assertEqual(0, struct.unpack_from("<H", table, 1024)[0] >> 12)

    def test_stage_texture_streams_restore_every_expanded_strip(self) -> None:
        source_manifest = target.json.loads(
            target.TERRAIN_MANIFEST.read_text(encoding="utf-8"))
        for packed_stage, source_stage in zip(
                self.manifest["stages"], source_manifest["stages"]):
            for bank, layer_name in enumerate(("foreground", "background")):
                section = packed_stage[layer_name + "_texture"]
                first = int(section["offset"])
                magic, count, record_size, _, _ = struct.unpack_from(
                    "<4sHHII", self.pack, first)
                self.assertEqual(target.TEXTURE_MAGIC, magic)
                self.assertEqual(target.TEXTURE_RECORD_SIZE, record_size)
                terrain = (target.ROOT /
                           source_stage["layers"][layer_name]["stream"]).read_bytes()
                graphics = (target.TILES0, target.TILES1)[bank].read_bytes()
                self.assertEqual(len(terrain) // target.STRIP_BYTES, count)
                for index in range(count):
                    relative, size = struct.unpack_from(
                        "<IH", self.pack,
                        first + target.TEXTURE_HEADER_SIZE +
                        index * target.TEXTURE_RECORD_SIZE)
                    self.assertLessEqual(relative % target.PAGE_SIZE + size,
                                         target.PAGE_SIZE)
                    actual = target.zlib.decompress(
                        self.pack[first + relative:first + relative + size])
                    raw = terrain[index * target.STRIP_BYTES:
                                  (index + 1) * target.STRIP_BYTES]
                    self.assertEqual(target._texture_strip(
                        raw, target._unpack_index4(graphics)), actual)

    def test_every_terrain_strip_is_page_safe_and_reversible(self) -> None:
        source_manifest = target.json.loads(
            target.TERRAIN_MANIFEST.read_text(encoding="utf-8"))
        for packed_stage, source_stage in zip(
                self.manifest["stages"], source_manifest["stages"]):
            for layer_name in ("foreground", "background"):
                section = packed_stage[layer_name]
                source = (target.ROOT /
                          source_stage["layers"][layer_name]["stream"]).read_bytes()
                rebuilt = bytearray()
                first = int(section["offset"])
                count = int(section["strip_count"])
                for index in range(count):
                    page = index // target.STRIPS_PER_PAGE
                    slot = index % target.STRIPS_PER_PAGE
                    offset = first + page * target.PAGE_SIZE + slot * target.STRIP_BYTES
                    self.assertLessEqual(
                        offset % target.PAGE_SIZE + target.STRIP_BYTES,
                        target.PAGE_SIZE)
                    rebuilt += self.pack[offset:offset + target.STRIP_BYTES]
                self.assertEqual(source, bytes(rebuilt))

    def test_stage_control_records_preserve_manifest_values(self) -> None:
        source_manifest = target.json.loads(
            target.TERRAIN_MANIFEST.read_text(encoding="utf-8"))
        for packed_stage, source_stage in zip(
                self.manifest["stages"], source_manifest["stages"]):
            event_offset = int(packed_stage["event_offset"])
            events = source_stage["events"]
            self.assertEqual(len(events), int(packed_stage["event_count"]))
            for index, event in enumerate(events):
                actual = struct.unpack_from(
                    "<3H", self.pack,
                    event_offset + index * target.EVENT_RECORD_SIZE)
                self.assertEqual(
                    (int(event["threshold"]), int(event["command"]),
                     int(event["handler"])), actual)

    def test_global_checkpoint_table_is_indexed_zero_through_fifteen(self) -> None:
        section = self.manifest["global_checkpoints"]
        offset = int(section["offset"])
        self.assertEqual(0, offset % target.PAGE_SIZE)
        for index in range(16):
            actual = struct.unpack_from(
                "<7H", self.pack,
                offset + index * target.CHECKPOINT_RECORD_SIZE)
            self.assertEqual(index, actual[0])


if __name__ == "__main__":
    unittest.main()
