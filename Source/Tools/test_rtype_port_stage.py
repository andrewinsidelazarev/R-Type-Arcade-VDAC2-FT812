"""Сверка Python-переноса M72-скроллера с полным эталоном Stage 1."""
from __future__ import annotations

import json
import struct
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PYTHON = ROOT / "Source" / "Python"
if str(PYTHON) not in sys.path:
    sys.path.insert(0, str(PYTHON))

from rtype_port.stage import M72Scroll, M72TerrainModifier, M72Tilemaps, Stage


class M72ScrollTest(unittest.TestCase):
    def test_first_visible_frame_has_both_layer_scrolls(self) -> None:
        scroll = M72Scroll()
        scroll.advance()
        self.assertEqual(0x0040, scroll.foreground_x)
        self.assertEqual(0x0081, scroll.background_x)

    def test_dispatch_uses_later_same_vblank_progression(self) -> None:
        scroll = M72Scroll()
        while scroll.vblank < 2511:
            scroll.advance()
        # Snapshot state is `$097D80`; `$0467` then integrates `$0080`
        # before `$1BA7`, crossing the mini-boss threshold `$097E`.
        self.assertEqual(0x097D, scroll.progression)
        self.assertEqual(0x097E, scroll.dispatch_progression)

    def test_objects_use_later_same_vblank_scroll_delta(self) -> None:
        scroll = M72Scroll()
        while scroll.vblank < 1471:
            scroll.advance()
        # Callback snapshot at frame 1471 contains the `$FFFF` written on the
        # preceding pass.  The current `$0467` writes zero before object
        # handler `$5Axx` runs; frame 1472 is the inverse.  These are direct
        # `object_writes.csv` checkpoints at PC `$0493`.
        self.assertEqual(0xFFFF, scroll.foreground_delta)
        self.assertEqual(0x0000, scroll.dispatch_foreground_delta)
        scroll.advance()
        self.assertEqual(0x0000, scroll.foreground_delta)
        self.assertEqual(0xFFFF, scroll.dispatch_foreground_delta)

    def test_complete_stage1_register_stream(self) -> None:
        reference = list(struct.iter_unpack(
            "<HH",
            (ROOT / "Assets" / "Converted" / "Arcade" / "Stage1"
             / "STAGE1_SCROLL_X.bin").read_bytes(),
        ))
        scroll = M72Scroll()
        while scroll.vblank < 898:
            scroll.advance()
        actual = [(scroll.foreground_x, scroll.background_x)]
        for _ in range(1, len(reference)):
            scroll.advance()
            actual.append((scroll.foreground_x, scroll.background_x))
        self.assertEqual(reference, actual)

    def test_object_scroll_state_matches_mame_snapshots(self) -> None:
        """RAM $2EC0/$2ED0/$2F4A, sampled before same-frame CPU writes."""
        checkpoints = {
            898: (0x005780, 0x065700, 0x0000),
            1000: (0x008A80, 0x068A00, 0x0000),
            1200: (0x00EE80, 0x06EE00, 0x0000),
            1400: (0x015280, 0x075200, 0x0000),
            1471: (0x017600, 0x077580, 0xFFFF),
            1472: (0x017680, 0x077600, 0x0000),
            1473: (0x017700, 0x077680, 0xFFFF),
            1474: (0x017780, 0x077700, 0x0000),
            1475: (0x017800, 0x077780, 0xFFFF),
        }
        scroll = M72Scroll()
        while scroll.vblank < max(checkpoints):
            scroll.advance()
            expected = checkpoints.get(scroll.vblank)
            if expected is not None:
                self.assertEqual(
                    expected,
                    (scroll.foreground_accumulator,
                     scroll.progression_accumulator,
                     scroll.foreground_delta),
                    f"MAME frame {scroll.vblank}",
                )

    def test_scroll_wrap_delta_is_signed_one_pixel_step(self) -> None:
        scroll = M72Scroll(
            foreground_accumulator=0x01FF80,
            progression_accumulator=0x01FF80,
        )
        scroll.advance()
        self.assertEqual(0x0000, scroll.foreground_x)
        self.assertEqual(0xFFFF, scroll.foreground_delta)

    def test_missing_integrator_preserves_ram_delta(self) -> None:
        scroll = M72Scroll()
        while scroll.vblank < 4397:
            scroll.advance()
        self.assertEqual(0xFFFF, scroll.foreground_delta)
        scroll.advance()  # 4398: stall caused by missing `$0467` on 4397.
        self.assertEqual(0x0D2C80, scroll.progression_accumulator)
        self.assertEqual(0xFFFF, scroll.foreground_delta)

    def test_no_fire_f42e_commits_after_final_9235_integration(self) -> None:
        scroll = M72Scroll(stage1_no_fire_reference=True)
        while scroll.vblank < 9235:
            scroll.advance()
        final_dispatch_x = scroll.dispatch_foreground_x
        self.assertEqual(0x0080, scroll.foreground_velocity)

        scroll.advance()

        self.assertEqual(final_dispatch_x, scroll.foreground_x)
        self.assertEqual(final_dispatch_x, scroll.dispatch_foreground_x)
        self.assertEqual(0, scroll.foreground_velocity)
        self.assertEqual(0, scroll.background_velocity)

    def test_no_fire_boss_does_not_take_playable_post_boss_timeline(self) -> None:
        scroll = M72Scroll(stage1_no_fire_reference=True)
        while scroll.vblank < 9236:
            scroll.advance()
        stopped = (scroll.foreground_accumulator,
                   scroll.background_accumulator,
                   scroll.progression_accumulator)
        while scroll.vblank < 10500:
            scroll.advance()
        self.assertEqual(stopped, (
            scroll.foreground_accumulator,
            scroll.background_accumulator,
            scroll.progression_accumulator,
        ))
        self.assertEqual(0, scroll.foreground_velocity)
        self.assertEqual(0, scroll.background_velocity)

        playable = M72Scroll(vblank=9769)
        playable.advance()
        self.assertEqual(0x0080, playable.foreground_velocity)
        self.assertEqual(0x0080, playable.background_velocity)

    def test_object_velocity_write_commits_after_next_snapshot_integration(
            self) -> None:
        scroll = M72Scroll(
            vblank=100,
            foreground_accumulator=0,
            foreground_velocity=0,
            background_accumulator=0,
            background_velocity=0,
            progression_accumulator=0,
        )
        scroll.queue_object_velocity_write(None, 0x0040)

        scroll.advance()

        # The frame-101 callback is still the result of velocity zero.  Its
        # later `$0467` dispatch already sees the post-handler `$0040` write.
        self.assertEqual(0, scroll.background_accumulator)
        self.assertEqual(0x0040, scroll.background_velocity)
        self.assertEqual(0, scroll.dispatch_background_delta)

        scroll.advance()
        self.assertEqual(0x0040, scroll.background_accumulator)
        scroll.advance()
        self.assertEqual(0x0080, scroll.background_accumulator)
        scroll.advance()
        self.assertEqual(0x00C0, scroll.background_accumulator)
        self.assertEqual(0xFFFF, scroll.dispatch_background_delta)

    def test_f130_reset_is_visible_at_following_callback(self) -> None:
        scroll = M72Scroll(
            vblank=100,
            foreground_accumulator=0x012340,
            foreground_velocity=0x0080,
            background_accumulator=0x010080,
            background_velocity=0x0080,
            progression_accumulator=0x14FE00,
        )
        scroll.queue_stage_transition_reset()
        scroll.queue_object_velocity_write(0, 0)

        scroll.advance()

        self.assertEqual(0, scroll.foreground_accumulator)
        self.assertEqual(0, scroll.background_accumulator)
        self.assertEqual(0, scroll.foreground_velocity)
        self.assertEqual(0, scroll.background_velocity)
        # `$F130` never writes `$2F4A`; progression stops at its prior value.
        self.assertEqual(0x14FE80, scroll.progression_accumulator)

    def test_f01b_stage_init_replaces_progression_and_velocities(self) -> None:
        scroll = M72Scroll(
            vblank=100,
            foreground_accumulator=0x012340,
            foreground_velocity=0,
            background_accumulator=0x010080,
            background_velocity=0,
            progression_accumulator=0x14FF80,
        )
        scroll.queue_stage_init(0x1500, 0x0080, 0x0040)

        scroll.advance()

        self.assertEqual(0, scroll.foreground_accumulator)
        self.assertEqual(0, scroll.background_accumulator)
        self.assertEqual(0x150000, scroll.progression_accumulator)
        self.assertEqual(0x0080, scroll.foreground_velocity)
        self.assertEqual(0x0040, scroll.background_velocity)


class M72TilemapTest(unittest.TestCase):
    def test_boss_normal_and_hit_flash_are_offline_palette_variants(self) -> None:
        directory = (ROOT / "Assets" / "Converted" / "Arcade" / "Stage1" /
                     "Sections")
        for section in (2, 3):
            with self.subTest(section=section):
                manifest = json.loads((
                    directory / f"STAGE1_S{section}_BOSS_PALETTE_manifest.json"
                ).read_text(encoding="utf-8"))
                normal = manifest["variants"]["normal9501"]
                flash = manifest["variants"]["flash9500"]
                self.assertEqual(9501, normal["palette_frame"])
                self.assertEqual(9500, flash["palette_frame"])
                self.assertEqual(normal["layers"]["fg"]["atlas_sha256"],
                                 flash["layers"]["fg"]["atlas_sha256"])
                self.assertNotEqual(normal["layers"]["bg"]["atlas_sha256"],
                                    flash["layers"]["bg"]["atlas_sha256"])

    def test_rom_tilemap_matches_mame_frames_898_and_1000(self) -> None:
        scroll = M72Scroll()
        tilemaps = M72Tilemaps()
        checkpoints = (
            (898, ROOT / "Build" / "Arcade" / "MAME" / "scroll_state_probe"),
            (1000, ROOT / "Build" / "Arcade" / "MAME" / "stage1_vram_pc"),
        )
        for frame, directory in checkpoints:
            while scroll.vblank < frame:
                scroll.advance()
                tilemaps.advance(scroll)
            for layer in range(2):
                reference = (
                    directory / f"frame_{frame:06d}_vram{layer}.bin"
                ).read_bytes()
                first = 16 * 64 * 4
                last = 48 * 64 * 4
                self.assertEqual(reference[first:last],
                                 tilemaps.vram[layer][first:last])

    def test_rom_1e6c_ground_walker_probe_matches_mame_frame_1473(self) -> None:
        scroll = M72Scroll()
        tilemaps = M72Tilemaps()
        while scroll.vblank < 1473:
            scroll.advance()
            tilemaps.advance(scroll)

        # Ground walker `$5BA4` has X=$02C7,Y=$00B5 after its first step;
        # it probes X-8,Y-16.  The MAME snapshot contains code $0FA0 at
        # foreground VRAM byte offset $2B98.
        object_x, object_y = 0x02BF, 0x00A5
        stage = Stage.__new__(Stage)
        stage.m72_scroll = scroll
        stage.tilemaps = tilemaps
        address = stage.terrain_address(object_x, object_y)
        self.assertEqual(0x2B98, address)
        self.assertEqual(0x0FA0,
                         struct.unpack_from("<H", tilemaps.vram[0], address)[0]
                         & 0x0FFF)

    def test_rom_1e6c_uses_later_same_vblank_scroll_x(self) -> None:
        """`$780E` slot `$1280` hits code `$0116` on MAME VBlank 3502."""
        scroll = M72Scroll()
        tilemaps = M72Tilemaps()
        while scroll.vblank < 3502:
            scroll.advance()
            tilemaps.advance(scroll)

        self.assertEqual(0x016D, scroll.foreground_x)
        self.assertEqual(0x016E, scroll.dispatch_foreground_x)
        stage = Stage.__new__(Stage)
        stage.m72_scroll = scroll
        stage.tilemaps = tilemaps
        address = stage.terrain_address(0x01EA, 0x00AE)
        self.assertEqual(0x2A2C, address)
        self.assertEqual(0x0116, stage.terrain_code(0x01EA, 0x00AE))

    def test_stage_event_4400_matches_mame_terrain_at_frame_4500(self) -> None:
        scroll = M72Scroll()
        tilemaps = M72Tilemaps()
        terrain = M72TerrainModifier(tilemaps.rom)
        while scroll.vblank < 4462:
            scroll.advance()
            tilemaps.advance(scroll)
            terrain.update(scroll, tilemaps)

        self.assertEqual(0x0D4C, scroll.progression)
        self.assertEqual(0x02B9, terrain.x)
        self.assertEqual(0x0001, terrain.timer)
        self.assertEqual(0x0000, terrain.tilemap_origin)
        # Snapshot 4462 precedes the `$6C20/$6C25` writes.  Their resulting
        # object state and tilemap origin are visible in snapshot 4463.
        scroll.advance()
        tilemaps.advance(scroll)
        terrain.update(scroll, tilemaps)
        self.assertEqual(0x02B8, terrain.x)
        self.assertEqual(0x0000, terrain.timer)
        self.assertEqual(0x1580, terrain.tilemap_origin)
        while scroll.vblank < 4500:
            scroll.advance()
            tilemaps.advance(scroll)
            terrain.update(scroll, tilemaps)
        reference = (
            ROOT / "Build" / "Arcade" / "MAME" / "stage1_vram_pc_4500_inv"
            / "frame_004500_vram0.bin"
        ).read_bytes()
        first = 16 * 64 * 4
        last = 48 * 64 * 4
        self.assertEqual(reference[first:last], tilemaps.vram[0][first:last])


if __name__ == "__main__":
    unittest.main()
