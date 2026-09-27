"""Проверка перенесённого счётчика наклона R-9 по трассе MAME."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PYTHON = ROOT / "Source" / "Python"
if str(PYTHON) not in sys.path:
    sys.path.insert(0, str(PYTHON))

from rtype_port.game import (
    CHARGE_FIRST_VISIBLE, Q8, SHOT_LIMIT, WAVE_MAX_CHARGE, WAVE_MIN_CHARGE,
    STAGE_EXIT_VELOCITIES, Shot, StageExitAutopilot, Wave,
    advance_pitch, advance_wave_charge, beam_animation_phase,
    beam_native_width, build_launch_frames, shot_collision_rect,
    p1_label_visible, score_tile_codes, wave_collision_rect, wave_power,
    wave_power_tier,
)
from rtype_port.enemies import M72ResourceManager, M72Rom
from rtype_port.bits import PlayerBits
from rtype_port.force import Force, ForceInput
from rtype_port.stage import M72CollisionSnapshot


class PlayerPitchTest(unittest.TestCase):
    def test_down_and_return(self) -> None:
        pitch = 20
        codes = []
        for _ in range(20):
            pitch = advance_pitch(pitch, False, True)
            codes.append(0x20 + (pitch >> 3))
        self.assertEqual(39, pitch)
        self.assertEqual(0x23, codes[3])
        self.assertEqual(0x24, codes[11])
        for _ in range(19):
            pitch = advance_pitch(pitch, False, False)
        self.assertEqual(20, pitch)
        self.assertEqual(0x22, 0x20 + (pitch >> 3))

    def test_up_and_return(self) -> None:
        pitch = 20
        codes = []
        for _ in range(20):
            pitch = advance_pitch(pitch, True, False)
            codes.append(0x20 + (pitch >> 3))
        self.assertEqual(0, pitch)
        self.assertEqual(0x21, codes[4])
        self.assertEqual(0x20, codes[12])
        for _ in range(20):
            pitch = advance_pitch(pitch, False, False)
        self.assertEqual(20, pitch)


class StageExitAutopilotTest(unittest.TestCase):
    def test_speed_zero_table_is_literal_rom_11ba(self) -> None:
        rom = M72Rom()
        table = rom.word(0x11B0)
        self.assertEqual(0x11BA, table)
        actual = []
        for direction in range(16):
            x = rom.word(table + direction * 4)
            y = rom.word(table + direction * 4 + 2)
            actual.append((x - 0x10000 if x & 0x8000 else x,
                           y - 0x10000 if y & 0x8000 else y))
        self.assertEqual(list(STAGE_EXIT_VELOCITIES), actual)

    def test_ff_latch_matches_no_fire_mame_exit_coordinates(self) -> None:
        player = StageExitAutopilot(0x01CB00, 0x011000)
        self.assertEqual((0x01CC, 0x010E), player.advance())  # frame 13041
        for _ in range(31):
            player.advance()
        self.assertEqual((0x01F7, 0x00E8), player.native)    # frame 13072
        for _ in range(4):
            player.advance()
        self.assertEqual((0x01FC, 0x00E3), player.native)    # frame 13076
        self.assertEqual((0x01FE, 0x00E3), player.advance()) # frame 13077
        self.assertEqual((0x01FE, 0x00E3), player.advance())


class HudScoreTest(unittest.TestCase):
    def test_191b_blanks_only_six_leading_zeroes(self) -> None:
        self.assertEqual((0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x30),
                         score_tile_codes(0))
        self.assertEqual((0x11, 0x11, 0x11, 0x32, 0x36, 0x30, 0x30),
                         score_tile_codes(2600))
        self.assertEqual((0x39, 0x39, 0x39, 0x39, 0x39, 0x39, 0x39),
                         score_tile_codes(9_999_999))

    def test_1125_default_dsw_label_phase_matches_mame_snapshots(self) -> None:
        self.assertTrue(p1_label_visible(0x02C1))   # MAME frame 898
        self.assertFalse(p1_label_visible(0x051B))  # MAME frame 1500
        self.assertTrue(p1_label_visible(0x0903))   # MAME frame 2500
        self.assertFalse(p1_label_visible(0x14B4))  # MAME frame 5500


class BeamChargeTest(unittest.TestCase):
    def test_all_reachable_meter_states_are_offline_assets(self) -> None:
        manifest = json.loads((
            ROOT / "Assets" / "Converted" / "Arcade" / "Player" /
            "r9_pitch.json").read_text(encoding="utf-8"))
        records = [record for record in manifest["records"]
                   if record["kind"] == "beam_meter"]
        self.assertEqual(list(range(0, 0x81, 2)),
                         [record["charge"] for record in records])
        self.assertTrue(all((ROOT / "Assets" / "Converted" / "Arcade" /
                            "Player" / record["png"]).is_file()
                            for record in records))

    def test_rom_2430_sound_threshold_is_charge_0f(self) -> None:
        self.assertEqual(0x0F, CHARGE_FIRST_VISIBLE)
        charge = 0
        crossings = 0
        for _ in range(80):
            previous = charge
            charge = advance_wave_charge(charge)
            crossings += previous < CHARGE_FIRST_VISIBLE <= charge
        self.assertEqual(1, crossings)

    def test_original_meter_progression(self) -> None:
        self.assertEqual(0, beam_native_width(0))
        self.assertEqual(0, beam_native_width(4))
        self.assertEqual(1, beam_native_width(5))
        self.assertEqual(64, beam_native_width(68))
        self.assertEqual(120, beam_native_width(124))
        self.assertEqual(124, beam_native_width(128))

    def test_rom_23ea_charge_levels_and_188c_power_table(self) -> None:
        self.assertEqual(0x18, WAVE_MIN_CHARGE)
        self.assertEqual(0x80, WAVE_MAX_CHARGE)
        boundaries = {
            0x00: 0, 0x17: 0,
            0x18: 4, 0x2F: 4,
            0x30: 8, 0x47: 8,
            0x48: 12, 0x4F: 12,
            0x50: 16, 0x67: 16,
            0x68: 20, 0x80: 20,
        }
        self.assertEqual(boundaries,
                         {charge: wave_power(charge) for charge in boundaries})
        self.assertEqual(0x18, self._charge_frames(12))
        self.assertEqual(0x80, advance_wave_charge(0x7E))
        self.assertEqual(0x80, advance_wave_charge(0x80))

    @staticmethod
    def _charge_frames(count: int) -> int:
        charge = 0
        for _ in range(count):
            charge = advance_wave_charge(charge)
        return charge

    def test_animation_uses_free_running_rom_counter(self) -> None:
        phases = [beam_animation_phase(frame) for frame in range(64)]
        self.assertEqual(
            [phase for phase in range(8) for _ in range(4)] * 2,
            phases,
        )
        # Величина заряда может стоять на пределе; фазу всё равно меняет $2EB6.
        self.assertNotEqual(beam_animation_phase(120),
                            beam_animation_phase(124))


class OrdinaryShotCollisionTest(unittest.TestCase):
    def test_rom_f548_record_from_mame_frame_1253(self) -> None:
        # Cropped sprite top-left is logical (258,204). The active record in
        # DS:$04D6 maps to logical [247,297) x [203,218).
        rect = shot_collision_rect(Shot(258 * Q8, 204 * Q8))
        self.assertEqual((247, 203, 50, 15),
                         (rect.x, rect.y, rect.width, rect.height))
        self.assertEqual(3, SHOT_LIMIT)

    def test_rom_f4aa_wave_record_from_mame_frame_1319(self) -> None:
        # Composite Wave top-left is logical (232,195). DS:$00F6 contains
        # native bounds mapping to logical [242,272) x [195,225).
        rect = wave_collision_rect(Wave(232 * Q8, 195 * Q8,
                                        0, 0, power=4, delay=0))
        self.assertEqual((242, 195, 30, 30),
                         (rect.x, rect.y, rect.width, rect.height))

    def test_rom_f4aa_uses_all_five_power_dependent_hitboxes(self) -> None:
        expected = {
            4: (242, 195, 30, 30),
            8: (225, 195, 57, 30),
            12: (225, 195, 67, 30),
            16: (225, 195, 54, 30),
            20: (225, 195, 70, 30),
        }
        for power, bounds in expected.items():
            with self.subTest(power=power):
                rect = wave_collision_rect(Wave(
                    232 * Q8, 195 * Q8, 0, 0, power=power, delay=0))
                self.assertEqual(bounds,
                                 (rect.x, rect.y, rect.width, rect.height))

    def test_rom_31e3_buckets_depleted_wave_power(self) -> None:
        self.assertEqual(
            [4, 4, 8, 8, 12, 12, 16, 16, 20, 20],
            [wave_power_tier(power)
             for power in (1, 4, 5, 8, 9, 12, 13, 16, 17, 20)],
        )
        self.assertEqual(0, wave_power_tier(0))

        wave = Wave(232 * Q8, 195 * Q8, 0, 0, power=19, delay=0)
        rect = wave_collision_rect(wave)
        self.assertEqual((225, 195, 70, 30),
                         (rect.x, rect.y, rect.width, rect.height))


class LaunchLogicTest(unittest.TestCase):
    def test_rom_scenario_key_frames(self) -> None:
        events = build_launch_frames()
        self.assertEqual(226, len(events))
        self.assertEqual((-44, 102, 4, 3),
                         (events[0].player_x, events[0].player_y,
                          events[0].body_index, events[0].effect_kind))
        # Кадр 900, лежавший в основе v002, находится внутри полного вылета.
        self.assertEqual((148, 102, 2, 1),
                         (events[48].player_x, events[48].player_y,
                          events[48].body_index, events[48].effect_kind))
        self.assertEqual((123, 102, 2, 0),
                         (events[-1].player_x, events[-1].player_y,
                          events[-1].body_index, events[-1].effect_kind))

    def test_rom_logic_matches_complete_mame_reference(self) -> None:
        import struct

        reference = list(struct.iter_unpack(
            "<hhBBhh",
            (ROOT / "Assets" / "Converted" / "Arcade" / "Player"
             / "R9_LAUNCH_EVENTS.bin").read_bytes(),
        ))
        actual = [(item.player_x, item.player_y, item.body_index,
                   item.effect_kind, item.effect_x, item.effect_y)
                  for item in build_launch_frames()]
        self.assertEqual(reference, actual)


class ForceStateMachineTest(unittest.TestCase):
    @staticmethod
    def _empty_collision(_x: int, _y: int) -> tuple[int, int]:
        return 0x0FA0, 0x07D0

    def setUp(self) -> None:
        self.rom = M72Rom()
        self.resources = M72ResourceManager(stage1_checkpoint=False)
        self.force = Force(self.rom)

    def _level(self, level: int) -> None:
        self.force.sync_level(level, self.resources.acquire,
                              self.resources.release)

    @staticmethod
    def _dobkeratops_collision_snapshot() -> M72CollisionSnapshot:
        """Exact World VRAM at MAME VBlank 9500, integer scroll `$8A/$0B`."""
        capture = (ROOT / "Build" / "Arcade" / "MAME" /
                   "boss_no_fire_probe")
        return M72CollisionSnapshot(
            0x008A, 0x000B,
            (capture / "frame_009500_vram0.bin").read_bytes(),
            (capture / "frame_009500_vram1.bin").read_bytes())

    def _run_detached_boss_probe(
            self, native_y: int, count: int
            ) -> list[tuple[int, int, str, int]]:
        snapshot = self._dobkeratops_collision_snapshot()
        self.force.level = 3
        self.force.resource_slot = 0
        self.force.state = "detached"
        self.force.x_q8 = 0x01E0 * 0x100
        self.force.y_q8 = native_y * 0x100
        self.force.velocity_x = 0x0900
        player = (0x01CB, 0x0110)
        history = (player,) * 16
        result = []
        for index in range(count):
            self.force.update(
                player, history, ForceInput(), 0x2000 + index,
                snapshot.collision_codes,
                snapshot.terrain_address, snapshot.foreground_cell, None,
                0, None, snapshot.background_address,
                snapshot.background_cell)
            result.append((self.force.x, self.force.y, self.force.state,
                           self.force.velocity_y & 0xFFFF))
        return result

    def test_level_table_1430_and_resource_56(self) -> None:
        self.assertEqual((0x2682, 0x26AD, 0x26D0, 0x26E9),
                         tuple(self.rom.word(0x1430 + 2 * i)
                               for i in range(4)))
        self._level(1)
        self.assertEqual((1, "return", 0x0100, 0x56),
                         (self.force.level, self.force.state, self.force.y,
                          self.resources.types[self.force.resource_slot]))
        self._level(3)
        self.assertEqual(3, self.force.level)
        self.assertEqual(1, sum(count for count in self.resources.refs if count))
        self._level(0)
        self.assertFalse(self.force.visible)
        self.assertEqual((0x0080, 0x0020), (self.force.x, self.force.y))

    def test_return_attach_and_detach_are_rom_states(self) -> None:
        self._level(1)
        self.force.x_q8 = 0x01EA * 0x100
        self.force.y_q8 = 0x0100 * 0x100
        history = ((0x01F0, 0x0100),) * 16
        sounds: list[str] = []
        self.force.update((0x01F0, 0x0100), history, ForceInput(), 4,
                          self._empty_collision, play_sfx=sounds.append)
        self.assertEqual("attached", self.force.state)
        self.assertTrue(self.force.behind)
        self.assertEqual([0x37], sounds)

        self.force.update((0x01F0, 0x0100), history,
                          ForceInput(action_edge=True), 5,
                          self._empty_collision, play_sfx=sounds.append)
        self.assertEqual("detached", self.force.state)
        self.assertEqual(-0x0900, self.force.velocity_x)
        self.assertEqual([0x37, 0x36], sounds)

    def test_boss_centre_wall_and_return_jitter_match_mame_rom(self) -> None:
        trace = self._run_detached_boss_probe(0x0100, 25)
        # Direct MAME probe frames 9481..9504.  `$2614` detects the foreground
        # wall while looking one X step ahead, then `$2AB4` follows its exact
        # two-native-pixel terrain-avoidance oscillation `$00F6/$00F8`.
        expected_tail = [
            (0x0255, 0x0100, "return", 0x0000),
            (0x0255, 0x00FE, "return", 0xFE00),
            (0x0253, 0x00FC, "return", 0xFE00),
            (0x0252, 0x00FA, "return", 0xFE00),
            (0x0251, 0x00F8, "return", 0xFE00),
            (0x0250, 0x00F6, "return", 0xFE00),
            (0x024E, 0x00F8, "return", 0x0200),
            (0x024D, 0x00F6, "return", 0xFE00),
            (0x024C, 0x00F8, "return", 0x0200),
            (0x024B, 0x00F6, "return", 0xFE00),
            (0x0249, 0x00F8, "return", 0x0200),
            (0x0248, 0x00F6, "return", 0xFE00),
            (0x0247, 0x00F8, "return", 0x0200),
        ]
        self.assertEqual(expected_tail, trace[12:])

    def test_boss_upper_corridor_reaches_head_like_mame_rom(self) -> None:
        trace = self._run_detached_boss_probe(0x00F8, 17)
        # The static VBlank-9500 VRAM snapshot has already received an arena
        # writer update which the live MAME frame-9497 probe had not.  The
        # exact live transition to `$24CE` is therefore kept in the CSV
        # oracle; this unit regression proves the invariant needed here:
        # Force reaches the vulnerable native bounds through this corridor.
        self.assertEqual((0x0279, 0x00F8, "detached", 0), trace[-1])
        # Dobkeratops `$4526` body endpoints at X=$026E,Y=$0100 are
        # `$0264..$0278,$00F6..$010A`; Force level 3 uses radius 12.
        force_left, force_right, force_lower, force_upper = (
            self.force.collision_bounds())
        self.assertTrue(force_left <= 0x0278 and force_right > 0x0264)
        self.assertTrue(force_lower <= 0x010A and force_upper > 0x00F6)

    def test_2ce4_scroll_delta_is_an_integer_native_pixel(self) -> None:
        self._level(1)
        self.force.x_q8 = 0x0237 * 0x100
        self.force.y_q8 = 0x00C0 * 0x100

        def solid(_x: int, _y: int) -> tuple[int, int]:
            return 0x03E8, 0x0F8F

        self.force._horizontal_return(0x0238, solid, 0xFFFF)
        self.assertEqual(0x0236 * 0x100, self.force.x_q8)

    def test_2702_erases_only_four_09f6_cells(self) -> None:
        self._level(1)
        self.force.x_q8 = 0x0180 * 0x100
        cells = {0x1000: (0x09F6, 0x88), 0x1004: (0x09F6, 0x88),
                 0x1104: (0x09F6, 0x88), 0x1100: (0x09F6, 0x88)}
        writes: list[tuple[int, int, int]] = []
        self.force.update(
            (0x02F0, 0x0100), ((0x02F0, 0x0100),) * 16,
            ForceInput(), 1, self._empty_collision,
            terrain_address=lambda _x, _y: 0x1000,
            terrain_cell=lambda address: cells[address],
            replace_terrain=lambda address, code, attr:
                writes.append((address, code, attr)),
        )
        self.assertEqual(
            [(0x1000, 0x0FA0, 0), (0x1004, 0x0FA0, 0),
             (0x1104, 0x0FA0, 0), (0x1100, 0x0FA0, 0)],
            writes,
        )

    def test_unattached_weapon_matrix_uses_literal_slot_callbacks(self) -> None:
        expected = {
            1: ({1}, {(0x0D00, 0x0000, 0x203C)}),
            2: ({5, 9}, {(0x0C00, 0x0240, 0x2036),
                         (0x0C00, -0x0240, 0x2042)}),
            3: ({5, 9, 13, 17}, {(0x0C00, 0x0240, 0x2036),
                                 (0x0C00, -0x0240, 0x2042),
                                 (0x0000, 0x0A00, 0x2030),
                                 (0x0000, -0x0A00, 0x2048)}),
        }
        for level, (slots, setups) in expected.items():
            with self.subTest(level=level):
                force = Force(self.rom)
                resources = M72ResourceManager(stage1_checkpoint=False)
                force.sync_level(level, resources.acquire, resources.release)
                count = force.fire_unattached_matrix(0, resources.acquire)
                self.assertEqual(len(slots), count)
                self.assertEqual(slots, set(force.projectiles))
                self.assertEqual(
                    setups,
                    {(item.velocity_x, item.velocity_y, item.descriptor)
                     for item in force.projectiles.values()},
                )

    def test_common_3ec4_projectile_integrates_q8_and_releases_slot(self) -> None:
        self._level(1)
        self.force.x_q8 = 0x0180 * 0x100
        self.force.y_q8 = 0x0100 * 0x100
        self.force.fire_unattached_matrix(0, self.resources.acquire)
        projectile = self.force.projectiles[1]
        palette = projectile.resource_slot
        self.force.update_projectiles(
            self._empty_collision, lambda _rect, _damage: False,
            self.resources.release)
        self.assertEqual(0x018D, projectile.x)
        self.assertIn(1, self.force.projectiles)
        self.force.update_projectiles(
            self._empty_collision, lambda _rect, _damage: True,
            self.resources.release)
        self.assertNotIn(1, self.force.projectiles)
        # Force itself still owns type $56; the projectile's type-$02 ref ended.
        self.assertEqual(0, self.resources.refs[palette])

    def test_attached_type_zero_matrix_builds_rom_segment_chains(self) -> None:
        for level, expected_count in ((2, 6), (3, 24)):
            with self.subTest(level=level):
                force = Force(self.rom)
                resources = M72ResourceManager(stage1_checkpoint=False)
                force.sync_level(level, resources.acquire, resources.release)
                force.attached = True
                force.state = "attached"
                count = force.fire_matrix(0, resources.acquire)
                self.assertEqual(expected_count, count)
                self.assertEqual(expected_count, len(force.ray_segments))
                self.assertEqual((1, 3),
                                 (force.ray_segments[0].delay,
                                  force.ray_segments[1].delay))
                self.assertEqual((2, 0),
                                 (force.ray_segments[0].power,
                                  force.ray_segments[1].power))
                self.assertTrue(force.ray_segments[16].mirrored)

    def test_42dd_delay_acquires_type_3d_then_4311_uses_rom_vector(self) -> None:
        self._level(2)
        self.force.attached = True
        self.force.state = "attached"
        self.force.x_q8 = 0x0180 * 0x100
        self.force.y_q8 = 0x0100 * 0x100
        self.force.fire_matrix(0, self.resources.acquire)
        root = self.force.ray_segments[0]
        self.force.update_ray_segments(
            0, self._empty_collision, lambda _rect, _damage: False,
            self.resources.acquire, self.resources.release)
        self.assertEqual("active", root.state)
        self.assertEqual(0x3D, self.resources.types[root.resource_slot])
        start = (root.x, root.y)
        self.force.update_ray_segments(
            0, self._empty_collision, lambda _rect, _damage: False,
            self.resources.acquire, self.resources.release)
        self.assertEqual(
            (start[0] + 8, start[1] + 8), (root.x, root.y))
        self.assertEqual(self.rom.word(0x209A), root.descriptor)

    def test_attached_type_two_and_four_build_literal_grid_chains(self) -> None:
        for level, expected_count, expected_power in ((2, 6, 2), (3, 12, 4)):
            for weapon_type in (2, 4):
                with self.subTest(level=level, weapon_type=weapon_type):
                    force = Force(self.rom)
                    resources = M72ResourceManager(stage1_checkpoint=False)
                    force.sync_level(level, resources.acquire, resources.release)
                    force.attached = True
                    force.state = "attached"
                    count = force.fire_matrix(weapon_type, resources.acquire)
                    self.assertEqual(expected_count, count)
                    self.assertEqual((1, 2, 4),
                                     tuple(force.grid_segments[i].delay
                                           for i in range(3)))
                    self.assertEqual(expected_power,
                                     force.grid_segments[0].power)
                    self.assertEqual((4, 2),
                                     (force.grid_segments[8].direction,
                                      force.grid_segments[8].orientation))

    def test_47c9_grid_root_and_link_use_rom_motion_and_history(self) -> None:
        self._level(2)
        self.force.attached = True
        self.force.state = "attached"
        self.force.x_q8 = 0x0180 * 0x100
        self.force.y_q8 = 0x0100 * 0x100
        self.force.fire_matrix(2, self.resources.acquire)
        root = self.force.grid_segments[0]
        linked = self.force.grid_segments[1]
        self.force.update_grid_segments(
            0, 0, 0, self._empty_collision,
            lambda _rect, _damage: False,
            self.resources.acquire, self.resources.release)
        self.assertEqual("active", root.state)
        # Slot 1 still has one delay tick after the root acquired `$3D`.
        self.assertEqual("delay", linked.state)
        start = (root.x, root.y)
        self.force.update_grid_segments(
            2, 0, 0, self._empty_collision,
            lambda _rect, _damage: False,
            self.resources.acquire, self.resources.release)
        self.assertEqual((start[0], start[1] - 8), (root.x, root.y))
        self.assertEqual(self.rom.word(0x2130) & 6, root.direction)
        self.assertEqual(0x218C + 6, root.descriptor)
        self.assertEqual("active", linked.state)

        linked_start = (linked.x, linked.y)
        self.force.update_grid_segments(
            4, 0, 0, self._empty_collision,
            lambda _rect, _damage: False,
            self.resources.acquire, self.resources.release)
        self.assertEqual(linked_start, (linked.x, linked.y))
        self.assertEqual((root.x, root.y),
                         (linked.history_x2, linked.history_y2))

    def test_attached_type_six_uses_level_specific_rom_callbacks(self) -> None:
        self._level(2)
        self.force.attached = True
        self.force.state = "attached"
        self.force.x_q8 = 0x0180 * 0x100
        self.force.y_q8 = 0x0100 * 0x100
        count = self.force.fire_matrix(
            6, self.resources.acquire, (0x0190, 0x0100), None)
        self.assertEqual(3, count)
        self.assertEqual({1, 3, 4}, set(self.force.darts))
        self.assertFalse(self.force.beams)

        force = Force(self.rom)
        resources = M72ResourceManager(stage1_checkpoint=False)
        force.sync_level(3, resources.acquire, resources.release)
        force.attached = True
        force.state = "attached"
        force.x_q8 = 0x0180 * 0x100
        force.y_q8 = 0x0100 * 0x100
        count = force.fire_matrix(6, resources.acquire)
        self.assertEqual(1, count)
        self.assertEqual({0}, set(force.beams))
        self.assertEqual(0x3D, resources.types[force.beams[0].resource_slot])

    def test_49cf_beam_expands_sixteen_frames_then_flies(self) -> None:
        self._level(3)
        self.force.attached = True
        self.force.state = "attached"
        self.force.x_q8 = 0x0180 * 0x100
        self.force.y_q8 = 0x0100 * 0x100
        self.force.fire_matrix(6, self.resources.acquire)
        for frame in range(16):
            self.force.update_type6(
                frame, self._empty_collision,
                lambda _rect, _damage: False,
                self.resources.acquire, self.resources.release)
        beam = self.force.beams[0]
        self.assertEqual("flight", beam.state)
        self.assertEqual(0x01E0, beam.x)
        self.assertEqual(0, beam.frame)
        self.force.update_type6(
            16, self._empty_collision, lambda _rect, _damage: False,
            self.resources.acquire, self.resources.release)
        self.assertEqual(0x01E8, beam.x)
        self.assertEqual(tuple(0x235C + part * 6 for part in range(4)),
                         beam.descriptors)


class PlayerBitsStateMachineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.rom = M72Rom()
        self.resources = M72ResourceManager(stage1_checkpoint=False)
        self.bits = PlayerBits(self.rom)

    def test_2ce5_2ea6_activation_uses_two_private_history_rings(self) -> None:
        player = (0x0180, 0x0100)
        self.bits.sync_and_update(
            2, player, 0, 1,
            self.resources.acquire, self.resources.release)
        self.assertEqual({0, 1}, set(self.bits.objects))
        upper, lower = self.bits.objects[0], self.bits.objects[1]
        self.assertEqual([0x0110] * 15, upper.history_y[:1] +
                         upper.history_y[2:])
        self.assertEqual([0x00F0] * 15, lower.history_y[:1] +
                         lower.history_y[2:])
        self.assertEqual((0x0104, 0x00FC), (upper.y, lower.y))
        self.assertEqual((0x56, 0x56),
                         (self.resources.types[upper.resource_slot],
                          self.resources.types[lower.resource_slot]))

    def test_2d50_uses_rom_offset_speed_and_descriptor_tables(self) -> None:
        player = (0x0180, 0x0100)
        self.bits.sync_and_update(
            1, player, 1, 4,
            self.resources.acquire, self.resources.release)
        bit = self.bits.objects[0]
        self.assertEqual(4, bit.strength)
        # Direction 1, strength group 0: `ES:$15E2=(-16,0)`.
        self.assertEqual(0x0170, bit.history_x[1])
        self.assertEqual(0x0100 + 0x20, bit.history_y[1])
        self.assertEqual(0x1764, bit.descriptor)

    def test_active_second_bit_releases_only_when_count_reaches_zero(self) -> None:
        player = (0x0180, 0x0100)
        self.bits.sync_and_update(
            2, player, 0, 1,
            self.resources.acquire, self.resources.release)
        self.bits.sync_and_update(
            1, player, 0, 2,
            self.resources.acquire, self.resources.release)
        self.assertEqual({0, 1}, set(self.bits.objects))
        slots = [bit.resource_slot for bit in self.bits.objects.values()]
        self.bits.sync_and_update(
            0, player, 0, 3,
            self.resources.acquire, self.resources.release)
        self.assertFalse(self.bits.objects)
        self.assertTrue(all(self.resources.refs[slot] == 0 for slot in slots))


if __name__ == "__main__":
    unittest.main()
