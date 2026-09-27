"""ROM-level checks for the standalone Stage 1 enemy dispatcher."""
from __future__ import annotations

import sys
import struct
import unittest
from collections import Counter
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]
PYTHON = ROOT / "Source" / "Python"
if str(PYTHON) not in sys.path:
    sys.path.insert(0, str(PYTHON))

from rtype_port.enemies import (
    Child8D85,
    AttachedAC4C, DebrisAEFB,
    BackgroundParticleE5CD,
    BossB7FBController, BossB7FBCore, BossB7FBCoreChild, BossB7FBMissile,
    BossB7FBMissileSpawner,
    BossB7FBRandomChild, BossB7FBRandomSpawner, BossB7FBSegment,
    DobkeratopsArenaAnchor, DobkeratopsBack, DobkeratopsBody,
    DobkeratopsDebrisE700, DobkeratopsOrb, DobkeratopsOrbTrail,
    DobkeratopsRoot,
    DobkeratopsTentacle, ExplosionE7BE, ExplosionEffect,
    Enemy, Enemy5CEA, Enemy5EED, Enemy6F89, Enemy7182, Enemy7294, Enemy7D68,
    Enemy8469, Enemy8561,
    Enemy8F5E, EnemyProjectile, FixedLarge6E9B, Projectile7435,
    FinalProjectile9660,
    FinalSpawner9660,
    Formation78F8Child, Formation78F8Parent,
    Handler5CEAShot, Handler60BA, Handler60BAChild, Handler60BAProjectile,
    LargeTerrain74B4,
    Multipart915BChild, Multipart915BParent, Radial95F1,
    MultipartA71DBody, MultipartA71DController,
    FormationChild, FormationParent, GroundWalker,
    InvulnerabilityTimerF44E, M72EnemyWorld,
    M72ResourceManager, M72Rng, PlayerTargeting80E3,
    RedFlyer, STAGE_EVENT_RANGES, StageEvent, StageObject8C12,
    Spawner875D, Spawner875DChild, TerrainBound55E9,
    Targeting80E3AttackFlash, Targeting80E3Projectile, TerrainAware897E,
    TerrainEnemy696E, TerrainModifierChild6C37, TerrainModifierParent6ACB,
    TerrainModifierProjectile6E27,
    Animated86A6, StageTransitionF1BF, TimedControlF3C1,
)
from rtype_port.stage import M72Scroll, M72Tilemaps, Stage


class ResourceManagerTest(unittest.TestCase):
    def test_rom_search_prefers_lowest_free_slot(self) -> None:
        manager = M72ResourceManager()
        self.assertEqual([0x02, 0x09, 0x57, 0x59, 0x5A, 0x5C],
                         manager.types[:6])
        self.assertEqual(6, manager.acquire(0x0D))
        self.assertEqual(6, manager.acquire(0x0D))
        self.assertEqual(2, manager.refs[6])
        manager.release(6)
        manager.release(6)
        self.assertEqual(0xFF, manager.types[6])


class WeaponCollisionDispatcherTest(unittest.TestCase):
    @staticmethod
    def _overlapping_enemies(world: M72EnemyWorld,
                             hit_points: tuple[int, ...]) -> list[Enemy]:
        result = []
        for index, hp in enumerate(hit_points):
            enemy = Enemy(f"target_{index}", 0x0200, 0x0100,
                          0xFF, 0, hp=hp, collision_table=0x2912)
            result.append(enemy)
        world.enemies = result
        return result

    def test_f493_persistent_force_hits_every_overlapping_enemy(self) -> None:
        world = M72EnemyWorld()
        enemies = self._overlapping_enemies(world, (2, 3))
        rect = enemies[0].hitbox(world.rom)
        # Force and both Bits are alternatives inside `$F493`: duplicate
        # overlap must still contribute only one point to each enemy.
        self.assertEqual(0, world.damage_force_at(
            (rect, rect, rect), cadence_tick=False))
        self.assertEqual(2, world.damage_force_at(
            (rect, rect, rect), cadence_tick=True))
        self.assertEqual((1, 2), tuple(enemy.hp for enemy in enemies))

    def test_f694_one_hit_object_reacts_to_force_without_cadence(self) -> None:
        world = M72EnemyWorld()
        enemy = self._overlapping_enemies(world, (1,))[0]
        rect = enemy.hitbox(world.rom)
        self.assertEqual(1, world.damage_force_at((rect,), cadence_tick=False))
        self.assertFalse(enemy.alive)

    def test_weapon_dispatchers_skip_object_at_or_beyond_x_02b4(self) -> None:
        world = M72EnemyWorld()
        enemy = Enemy("right_edge_target", 0x02B4, 0x0100,
                      0xFF, 0, hp=3, collision_table=0x2912)
        world.enemies = [enemy]
        rect = enemy.hitbox(world.rom)
        self.assertFalse(world.damage_at(rect))
        self.assertEqual(0, world.damage_wave_at(rect, 20))
        self.assertEqual(0, world.damage_force_at((rect,), cadence_tick=True))
        self.assertEqual(3, enemy.hp)

    def test_5e8e_weapon_death_reuses_its_pool_slot_for_e7be(self) -> None:
        world = M72EnemyWorld()
        parent = FormationParent(world, 0)
        enemy = FormationChild(world, parent, 0)
        slot = world.object_pool.take()
        self.assertIsNotNone(slot)
        world.object_pool.bind(enemy, slot)
        world.enemies = [enemy]
        enemy.take_damage(world, 1)
        world.update(0, 0, 0, lambda _x, _y: 0x0FFF)
        self.assertEqual(1, len(world.enemies))
        explosion = world.enemies[0]
        self.assertEqual("explosion_e7be", explosion.kind)
        self.assertEqual(slot, explosion.object_slot)
        self.assertIn(slot, world.object_pool.allocated)
        self.assertEqual(1, explosion.sequence_timer)
        self.assertEqual([0x50], world.sound_commands)

    def test_in_place_e7xx_preserves_q8_residue_for_next_slot_owner(self) -> None:
        world = M72EnemyWorld()
        enemy = Enemy("fractional_target", 0x0200, 0x0100,
                      0xFF, 0, death_effect="e7be")
        enemy.x_fraction = 0x12
        enemy.y_fraction = 0x80
        slot = world.object_pool.take()
        self.assertIsNotNone(slot)
        world.object_pool.bind(enemy, slot)
        world.enemies = [enemy]
        enemy.take_damage(world, 1)

        world.update(0, 0, 0, lambda _x, _y: 0x0FFF)
        explosion = world.enemies[0]
        self.assertEqual((0x12, 0x80),
                         (explosion.x_fraction, explosion.y_fraction))
        while explosion.alive:
            world.update(0, 0, 0, lambda _x, _y: 0x0FFF)
        self.assertEqual((0x12, 0x80), world.object_pool.residue[slot])

    def test_f578_target_left_touching_shot_right_does_not_overlap(self) -> None:
        world = M72EnemyWorld()
        enemy = Enemy("touching_target", 0x0206, 0x0100,
                      0xFF, 0, collision_table=0x34A6)
        world.enemies = [enemy]
        # Shot right=$0202; target left=$0202. ROM CMP intervals only touch.
        self.assertFalse(world.damage_shot_native(
            (0x01E4, 0x0202, 0x00FC, 0x0104)))
        self.assertTrue(enemy.alive)

    def test_f578_target_upper_touching_shot_lower_does_overlap(self) -> None:
        world = M72EnemyWorld()
        enemy = Enemy("touching_target", 0x01D4, 0x0100,
                      0xFF, 0, collision_table=0x3C56)
        world.enemies = [enemy]
        # `$F5AA`: $0100 + upper extent $000C == shot lower $010C;
        # the following JAE enters the collision path.
        self.assertTrue(world.damage_shot_native(
            (0x01D4, 0x01F2, 0x010C, 0x0114)))
        self.assertFalse(enemy.alive)

    def test_f493_force_left_touching_target_right_does_overlap(self) -> None:
        world = M72EnemyWorld()
        enemy = Enemy("force_edge_target", 0x01B2, 0x00B0,
                      0xFF, 0, hp=2, collision_table=0x3426)
        world.enemies = [enemy]
        # Target right=$01BE and Force left=$01BE.  `$F594` uses JAE for
        # this side, so the equality is a hit rather than pygame's empty
        # edge-only intersection.
        self.assertEqual(1, world.damage_force_native(
            ((0x01BE, 0x01C6, 0x00BA, 0x00C2),), cadence_tick=True))
        self.assertEqual(1, enemy.hp)

    def test_f548_uses_dynamic_scheduler_order_for_competing_targets(self) -> None:
        world = M72EnemyWorld()
        older = Enemy("older", 0x0200, 0x0100,
                      0xFF, 0, collision_table=0x2912,
                      scheduler_priority=0xC000, scheduler_serial=1)
        newer = Enemy("newer", 0x0200, 0x0100,
                      0xFF, 0, collision_table=0x2912,
                      scheduler_priority=0xC000, scheduler_serial=2)
        world.enemies = [older, newer]
        self.assertTrue(world.damage_shot_native(
            (0x01F0, 0x0210, 0x00F0, 0x0110)))
        self.assertTrue(older.alive)
        self.assertFalse(newer.alive)

    def test_f703_wave_hits_all_and_returns_remaining_hp_cost(self) -> None:
        world = M72EnemyWorld()
        enemies = self._overlapping_enemies(world, (1, 6))
        rect = enemies[0].hitbox(world.rom)
        self.assertEqual(7, world.damage_wave_at(rect, 4))
        self.assertEqual((-3, 2), tuple(enemy.hp for enemy in enemies))
        self.assertEqual((False, True),
                         tuple(enemy.alive for enemy in enemies))

    def test_e601_common_projectile_is_force_only(self) -> None:
        world = M72EnemyWorld()
        source = Enemy("source", 0x0200, 0x0100, 0xFF, 0)
        projectile = EnemyProjectile(world, source, 0x8F90)
        world.enemies = [projectile]
        rect = projectile.hitbox(world.rom)
        self.assertEqual(0, world.damage_wave_at(rect, 20))
        self.assertEqual(1, world.damage_force_at(
            (rect,), cadence_tick=False))
        self.assertEqual(0x0A, projectile.burst_timer)

    def test_e601_tilemap_and_bounds_checks_run_only_on_even_vblank(self) -> None:
        world = M72EnemyWorld()
        source = Enemy("source", 0x0200, 0x0100, 0xFF, 0)
        projectile = EnemyProjectile(world, source, 0x8F90)
        world._collision_codes = lambda _x, _y: (0x0FFF, 0x0700)
        # `frame_counter` is the pre-IRQ snapshot; `$E659` sees `+1`.
        world.frame_counter = 2
        projectile.update(world, 0)
        self.assertEqual(0, projectile.burst_timer)
        world.frame_counter = 1
        projectile.update(world, 0)
        self.assertEqual(0x0A, projectile.burst_timer)

    def test_e8bd_uses_all_sixteen_rom_packed_bcd_increments(self) -> None:
        expected = (4, 100, 200, 300, 400, 500, 600, 700,
                    800, 1000, 1500, 2000, 5000, 8000, 10000, 15000)
        for index, points in enumerate(expected):
            world = M72EnemyWorld()
            pointer = 0x86E4 + index * 4
            world.award_score_pointer(pointer)
            self.assertEqual(points, world.score, f"ES:${pointer:04X}")
            self.assertEqual(points, world.stage_score)
            self.assertEqual([pointer], world.score_awards)

    def test_destroyed_enemy_awards_score_but_natural_cleanup_does_not(self) -> None:
        world = M72EnemyWorld()
        world.event_pointer = world.event_last + 1
        killed = Enemy("score_target", 0x0200, 0x0100, 0xFF, 0,
                       score_pointer=0x86EC)
        killed.take_damage(world, 1)
        escaped = Enemy("escaped", 0x0200, 0x0100, 0xFF, 0,
                        score_pointer=0x8720)
        escaped.alive = False
        world.enemies = [killed, escaped]
        world.update(0, 0, 0)
        self.assertEqual(200, world.score)
        self.assertEqual([0x86EC], world.score_awards)

    def test_e8bd_clamps_to_seven_digit_rom_maximum(self) -> None:
        world = M72EnemyWorld()
        world.score_bcd[:] = bytes((0x90, 0x99, 0x99, 0x09))
        world.award_score_pointer(0x8720)
        self.assertEqual(bytes((0x99, 0x99, 0x99, 0x09)),
                         bytes(world.score_bcd))
        self.assertEqual(9_999_999, world.score)


class RngTest(unittest.TestCase):
    def test_edd9_ede9_sequence(self) -> None:
        rng = M72Rng()
        self.assertEqual(0x0304, rng.next())
        self.assertEqual(0x0106, rng.next())
        self.assertEqual(0x0509, rng.next())

    def test_stage1_checkpoint_e568_matches_vblank_852_trace(self) -> None:
        world = M72EnemyWorld()
        self.assertEqual((0xB9, 0xB3, 0xDF),
                         (world.rng.a, world.rng.b, world.rng.c))
        self.assertEqual(1, len(world.resource_owners))
        owner = world.resource_owners[0]
        self.assertEqual((0x00E8, 0, 6, 0x836C),
                         (owner.remaining, owner.spawn_counter,
                          owner.cadence, owner.velocity_table))
        particle = world.enemies[0]
        self.assertIsInstance(particle, BackgroundParticleE5CD)
        self.assertFalse(particle.initialized)

        world.update(0, 0, 0x0293)

        # MAME object `DS:$1280`, VBlank 852:
        # +$30=$FE80, +$34=$8472, +$06=3, +$08=$00BF, +$04=$02AC.
        self.assertEqual((0x4B, 0x6C, 0x92),
                         (world.rng.a, world.rng.b, world.rng.c))
        self.assertEqual((-0x0180, 0x8472, 3, 0x00BF, 0x02AC),
                         (particle.x_velocity, particle.descriptor,
                          particle.palette, particle.y, particle.x))
        self.assertTrue(particle.initialized)
        self.assertFalse(particle.render_ready)
        self.assertEqual((0x00E7, 1),
                         (owner.remaining, owner.spawn_counter))

        world.update(0, 0, 0x0294)
        self.assertEqual((0x02AA, 0x80),
                         (particle.x, particle.x_fraction))
        self.assertTrue(particle.render_ready)

    def test_stage1_checkpoint_rng_and_controller_match_vblank_898(self) -> None:
        world = M72EnemyWorld()
        for frame in range(852, 899):
            world.update(0, 0, (0x0292 + frame - 851) & 0xFFFF)
        owner = world.resource_owners[0]
        self.assertEqual((0x00B9, 5),
                         (owner.remaining, owner.spawn_counter))
        self.assertEqual((0xA1, 0x26, 0x5C),
                         (world.rng.a, world.rng.b, world.rng.c))

    def test_stage1_rng_stream_matches_mame_through_first_miniboss(self) -> None:
        """Regression for all 1110 traced `$EDE9` calls, VBlank 852..2511."""
        scroll = M72Scroll()
        world = M72EnemyWorld()
        miniboss = None
        for frame in range(852, 2512):
            scroll.advance()
            world.update(
                scroll.dispatch_progression, scroll.foreground_delta,
                (0x0292 + frame - 851) & 0xFFFF,
                player_native=(0x01CB, 0x0110),
                background_delta=scroll.background_delta)
            candidates = [enemy for enemy in world.enemies
                          if isinstance(enemy, PlayerTargeting80E3)]
            if candidates:
                miniboss = candidates[0]
        self.assertIsNotNone(miniboss)
        self.assertEqual(3, miniboss.attack_delay)
        self.assertEqual((0x43, 0x97, 0x52),
                         (world.rng.a, world.rng.b, world.rng.c))


class EventDispatcherTest(unittest.TestCase):
    def test_all_eight_rom_event_streams_have_exact_closed_bounds(self) -> None:
        expected_counts = (161, 43, 15, 140, 79, 123, 177, 50)
        for stage, expected_count in enumerate(expected_counts, 1):
            with self.subTest(stage=stage):
                world = M72EnemyWorld(stage, full_event_stream=True)
                addresses = []
                while (event := world.current_event()) is not None:
                    addresses.append(event.address)
                    world.event_pointer += 4
                first, last = STAGE_EVENT_RANGES[stage]
                self.assertEqual(first, addresses[0])
                self.assertEqual(last, addresses[-1])
                self.assertEqual(expected_count, len(addresses))

    def test_all_stage_event_implementation_ledger_is_exact(self) -> None:
        world = M72EnemyWorld()
        counts = Counter()
        for first, last in STAGE_EVENT_RANGES.values():
            for address in range(first, last + 1, 4):
                command = world.rom.word(address + 2)
                handler = world.rom.word(0xB92D + ((command >> 9) & 0x7E))
                counts[handler] += 1
        implemented = set(world.HANDLERS) | {0xE430}
        missing = {handler: count for handler, count in counts.items()
                   if handler not in implemented | world.DELEGATED_HANDLERS}
        self.assertEqual(748, sum(counts[item] for item in implemented))
        self.assertEqual(40, sum(counts[item]
                                  for item in world.DELEGATED_HANDLERS))
        self.assertEqual({}, missing)

    def test_all_eight_event_streams_survive_long_headless_replay(self) -> None:
        for stage in range(1, 9):
            with self.subTest(stage=stage):
                world = M72EnemyWorld(stage, full_event_stream=True)
                for frame in range(1500):
                    world.update(
                        0xFFFF, -1, frame,
                        terrain_code=lambda _x, _y: 0x0FFF,
                        collision_codes=lambda _x, _y: (0x0FFF, 0x0FFF),
                        player_native=(0x01CB, 0x0110),
                        terrain_address=lambda _x, _y: 0x1002,
                        erase_terrain=lambda _address: None,
                        replace_terrain=lambda _address, _code, _attr: None,
                        terrain_cell=lambda _address: (0x0FFF, 0))
                self.assertIsNone(world.current_event())
                self.assertEqual([], world.unsupported_events)

    def test_delegated_and_missing_enemy_handlers_are_not_conflated(self) -> None:
        world = M72EnemyWorld(stage=3, full_event_stream=True)
        scroll_event = StageEvent(0xBCF3, 0x2000, 0x5C00, 0xC46E)
        missing_enemy = StageEvent(0xBC00, 0, 0, 0xDEAD)
        world._dispatch(scroll_event)
        world._dispatch(missing_enemy)
        self.assertEqual([scroll_event], world.delegated_events)
        self.assertEqual([missing_enemy], world.unsupported_events)

    def test_f366_first_call_allocates_literal_delayed_sound_record(self) -> None:
        world = M72EnemyWorld()
        event = StageEvent(0xBBFF, 0x1318, 0x9C00, 0xF366)

        world._dispatch(event)

        self.assertEqual([1, 0], world.stage_transition_flags)
        self.assertEqual([0x21], world.sound_commands)
        self.assertEqual(1, len(world.pending))
        control = world.pending[0]
        self.assertIsInstance(control, TimedControlF3C1)
        self.assertEqual((0x1000, 0x0180, 0x20),
                         (control.scheduler_priority, control.timer,
                          control.sound_command))
        for _ in range(0x017F):
            control.update(world, 0)
        self.assertTrue(control.alive)
        control.update(world, 0)
        self.assertFalse(control.alive)
        self.assertEqual([0x21, 0x20], world.sound_commands)

    def test_f130_sets_cleanup_scroll_reset_and_allocates_f1bf(self) -> None:
        world = M72EnemyWorld()
        event = StageEvent(0xBC0F, 0x14FE, 0xA000, 0xF130)

        world._dispatch(event)

        self.assertTrue(world.cleanup_active)
        self.assertTrue(world.take_scroll_reset_command())
        self.assertEqual((0, 0), world.take_scroll_velocity_commands())
        self.assertEqual(1, len(world.pending))
        self.assertIsInstance(world.pending[0], StageTransitionF1BF)
        self.assertEqual(0xFF00, world.pending[0].scheduler_priority)

    def test_f1bf_literal_five_jobs_e0_reveal_and_20_tail(self) -> None:
        world = M72EnemyWorld()
        transition = StageTransitionF1BF()
        world.stage_score_bcd[:] = bytes((0x34, 0x12, 0x00, 0x00))

        for _ in range(4):
            transition.update(world, 0)
            self.assertEqual("f1bf", transition.state)
        transition.update(world, 0)
        self.assertEqual(("f260", 0x00E0),
                         (transition.state, transition.timer))
        self.assertEqual([0, 0xFF, 0xFF, 0xFF, 1, 2, 3, 4],
                         transition.result_digits)

        for _ in range(0x00DF):
            transition.update(world, 0)
        self.assertEqual(("f260", 1),
                         (transition.state, transition.timer))
        transition.update(world, 0)
        self.assertEqual(("f34d", 0x20),
                         (transition.state, transition.timer))
        for _ in range(0x1F):
            transition.update(world, 0)
            self.assertTrue(transition.alive)
        transition.update(world, 0)
        self.assertFalse(transition.alive)
        self.assertEqual(0x0080, world.foreground_velocity_command)

    def test_f01b_command_6404_enters_stage2_and_allocates_f44e(self) -> None:
        world = M72EnemyWorld()
        world.stage_transition_flags[0] = 1
        event = StageEvent(0xBC13, 0x1500, 0x6404, 0xF01B)

        world._dispatch(event)

        self.assertEqual(2, world.stage)
        self.assertEqual(STAGE_EVENT_RANGES[2],
                         (world.event_pointer, world.event_last))
        self.assertEqual((0x1500, 0x0080, 0x0040),
                         world.take_stage_init_scroll_command())
        self.assertEqual([0x04], world.sound_commands)
        timer = world.pending[0]
        self.assertIsInstance(timer, InvulnerabilityTimerF44E)
        self.assertEqual((0xFFFE, 0x0080),
                         (timer.scheduler_priority, timer.timer))

    def test_6788_mirrors_child_velocity_and_sector_left_of_player(self) -> None:
        world = M72EnemyWorld()
        source = Handler60BA(world, 0)
        source.x = 0x01C9
        world.player_native = (0x01CB, 0x0110)

        left_arc = Handler60BAChild(world, source, 0x2CA4)
        right_arc = Handler60BAChild(world, source, 0x2CAC)

        self.assertEqual((0x00C0, 0x01C0, 1),
                         (left_arc.x_velocity, left_arc.y_velocity,
                          left_arc.direction))
        self.assertEqual((-0x00C0, 0x01C0, 0x0F),
                         (right_arc.x_velocity, right_arc.y_velocity,
                          right_arc.direction))

    def test_696e_initializer_is_read_directly_from_rom_tables(self) -> None:
        world = M72EnemyWorld(stage=4, full_event_stream=True)
        enemy = TerrainEnemy696E(world, 0x3845)
        self.assertEqual((0x02C8, 0x0114, 0x9E4E, 3, 3),
                         (enemy.x, enemy.y, enemy.motion.script,
                          enemy.motion.commands, enemy.hp))
        self.assertEqual((0x2A, 0x55),
                         (world.resources.types[enemy.palette],
                          world.resources.types[enemy.flash_palette]))

    def test_696e_direction_selects_descriptor_and_exact_tile_replacement(self) -> None:
        world = M72EnemyWorld(stage=4, full_event_stream=True)
        enemy = TerrainEnemy696E(world, 0x3845)
        enemy.motion = SimpleNamespace(
            phase=4, update=lambda _rom, _owner: False)
        writes = []
        world._terrain_code = lambda x, y: (
            0x0FA0 if (x, y) == (0x02C7, 0x0120) else 0x0FFF)
        world._terrain_address = lambda _x, _y: 0x1234
        world._replace_terrain = lambda address, code, attr: writes.append(
            (address, code, attr))
        enemy.update(world, -1)
        self.assertEqual(0x2DE8, enemy.descriptor)
        self.assertEqual([(0x1234, 0x09F6, 0x0082)], writes)

    def test_5cea_parent_and_e6ab_projectile_use_rom_difficulty_zero(self) -> None:
        world = M72EnemyWorld(stage=5, full_event_stream=True)
        enemy = Enemy5CEA(world, 0x4C0A)
        self.assertEqual((0x02C8, 0x00E0, -0x0200, -0x0600, 0x30, 0x34),
                         (enemy.x, enemy.y, enemy.x_velocity,
                          enemy.shot_velocity, enemy.fire_reload,
                          enemy.random_delay))
        for _ in range(0x30):
            enemy.update(world, 0)
        self.assertEqual(1, world.projectile_spawns)
        self.assertEqual(1, len(world.pending))
        shot = world.pending[0]
        self.assertIsInstance(shot, Handler5CEAShot)
        self.assertEqual((0x0268, 0x00E0, -0x0600),
                         (shot.x, shot.y, shot.x_velocity))

    def test_9660_spawner_builds_exact_aimed_child(self) -> None:
        world = M72EnemyWorld(stage=8, full_event_stream=True)
        spawner = FinalSpawner9660(world, 0xAC12)
        self.assertEqual((0x02C0, 0x009C, 0x0110, 0x0104),
                         (spawner.x, spawner.y, spawner.period, spawner.timer))
        spawner.timer = 1
        spawner.update(world, 0)
        self.assertEqual(1, world.projectile_spawns)
        child = world.pending[0]
        self.assertIsInstance(child, FinalProjectile9660)
        self.assertEqual((-0x0250, 0x0100, 0x4348),
                         (child.x_velocity, child.y_velocity,
                          child.descriptor_base))
        world.frame_counter = 8
        child.update(world, 0)
        self.assertEqual((0x02BD, 0xB0, 0x009D, 0, 0x434E),
                         (child.x, child.x_fraction, child.y,
                          child.y_fraction, child.descriptor))

    def test_9660_child_uses_resource_6b_explosion_path(self) -> None:
        world = M72EnemyWorld(stage=8, full_event_stream=True)
        child = FinalProjectile9660(world, 0x0200, 0x0100,
                                    0, 0, 0x42AC)
        world.enemies = [child]
        child.take_damage(world, 1)
        world.update(0, 0, 0)
        explosion = world.enemies[0]
        self.assertIsInstance(explosion, ExplosionEffect)
        self.assertEqual("e7d4_6b", explosion.effect)
        self.assertEqual(0x6B, world.resources.types[explosion.palette])

    def test_8469_rom_fire_table_and_wall_bounce(self) -> None:
        world = M72EnemyWorld(stage=7, full_event_stream=True)
        enemy = Enemy8469(world, 0x483A)
        self.assertEqual((0x02C8, 0x00E0, 0x0080, 0x00C0, 0x9010,
                          0x0010),
                         (enemy.x, enemy.y, enemy.fire_a, enemy.fire_b,
                          enemy.projectile_script, enemy.fire_counter))
        world.frame_counter = 0
        world._terrain_code = lambda _x, _y: 0x0001
        enemy.update(world, 0)
        self.assertEqual((0x02C6, 0, -0x0100, 8),
                         (enemy.x, enemy.x_velocity,
                          enemy.y_velocity, enemy.pause_timer))
        world._terrain_code = lambda _x, _y: 0x0FFF
        enemy.update(world, 0)
        self.assertEqual((0x02C6, 0x00DF, 0, -0x0100, 7),
                         (enemy.x, enemy.y, enemy.x_velocity,
                          enemy.y_velocity, enemy.pause_timer))

    def test_8561_composite_shooter_and_e817_resource(self) -> None:
        world = M72EnemyWorld(stage=5, full_event_stream=True)
        enemy = Enemy8561(world, 0xB40D)
        self.assertEqual((0x02C8, 0x00C8, -0x02C0, 0x36, 0x1E),
                         (enemy.x, enemy.y, enemy.shot_velocity,
                          enemy.fire_reload, enemy.hp))
        for _ in range(0x36):
            enemy.update(world, 0)
        shot = world.pending[0]
        self.assertIsInstance(shot, Handler5CEAShot)
        self.assertEqual((0x0282, 0x00C8, -0x02C0),
                         (shot.x, shot.y, shot.x_velocity))

        enemy.hp = 1
        world.enemies = [enemy]
        world.pending.clear()
        enemy.take_damage(world, 1)
        world.update(0, 0, 0)
        explosion = world.enemies[0]
        self.assertEqual("e817", explosion.effect)
        self.assertEqual(0x01, world.resources.types[explosion.palette])

    def test_8f5e_motion_turn_and_four_cell_mutator(self) -> None:
        world = M72EnemyWorld(stage=4, full_event_stream=True)
        enemy = Enemy8F5E(world, 0x5000)
        self.assertEqual((0x0198, 0x0188, 3),
                         (enemy.x, enemy.y, enemy.direction))
        world.frame_counter = 0
        world.player_native = (0, 0)
        world._terrain_address = lambda _x, _y: 0x12FE
        world._terrain_cell = lambda _address: (0x09F6, 0x0082)
        writes = []
        world._replace_terrain = lambda address, code, attr: writes.append(
            (address, code, attr))
        enemy.update(world, -1)
        self.assertEqual((0x0197, 0x0187, 0x404E),
                         (enemy.x, enemy.y, enemy.descriptor))
        self.assertEqual([
            (0x12FE, 0x0FA0, 0), (0x1202, 0x0FA0, 0),
            (0x1302, 0x0FA0, 0), (0x13FE, 0x0FA0, 0),
        ], writes)

        enemy = Enemy8F5E(world, 0x5000)
        world.player_native = (0x0200, 0x018B)
        enemy.update(world, -1)
        self.assertEqual((0x0196, 0x0187, 3, 0, 0x1E, 0x4072),
                         (enemy.x, enemy.y, enemy.direction,
                          enemy.next_direction, enemy.turn_timer,
                          enemy.descriptor))

    def test_6f89_wait_motion_and_hit_freeze_follow_rom_fields(self) -> None:
        world = M72EnemyWorld(stage=2, full_event_stream=True)
        enemy = Enemy6F89(world, 0x340A)
        self.assertEqual((0x02D0, 0x0098, 0x0180, 0x0200,
                          0x0060, 0x0080, 0x309E, 0x0180, 10),
                         (enemy.x, enemy.y, enemy.primary_x, enemy.primary_y,
                          enemy.secondary_x, enemy.secondary_y,
                          enemy.descriptor_table, enemy.wait_value, enemy.hp))
        enemy.update(world, -1)
        self.assertEqual((0x02CF, 0x017F, 0x313A),
                         (enemy.x, enemy.wait_value, enemy.descriptor))
        enemy.wait_value = 1
        enemy.update(world, -1)
        self.assertEqual("moving", enemy.state)
        world._terrain_code = lambda _x, _y: 0x0FA0
        enemy.update(world, -1)
        self.assertEqual((0x02CE, 0x80, 0x009A, 0, 0x316A),
                         (enemy.x, enemy.x_fraction, enemy.y,
                          enemy.y_fraction, enemy.descriptor))

        enemy.take_damage(world, 1)
        enemy.update(world, -1)
        self.assertEqual((9, 0x16, 0x02CD, 0x310A, False),
                         (enemy.hp, enemy.flash_timer, enemy.x,
                          enemy.descriptor, enemy.flash_visible))

    def test_7182_turns_one_sector_then_uses_rom_velocity(self) -> None:
        world = M72EnemyWorld(stage=5, full_event_stream=True)
        enemy = Enemy7182(world, 0x7852)
        self.assertEqual((0x0278, 0x0188, 8, 0x10, 0x0280,
                          0x0040, 0x0060, 0x9050),
                         (enemy.x, enemy.y, enemy.direction,
                          enemy.turn_reload, enemy.active_timer,
                          enemy.fire_a, enemy.fire_b,
                          enemy.projectile_script))
        enemy.update(world, 0)
        self.assertEqual((9, -0x00C0, -0x01C0,
                          0x0277, 0x40, 0x0186, 0x40, 0x324C),
                         (enemy.direction, enemy.x_velocity,
                          enemy.y_velocity, enemy.x, enemy.x_fraction,
                          enemy.y, enemy.y_fraction, enemy.descriptor))

    def test_7294_direction_motion_reflection_and_special_shot(self) -> None:
        world = M72EnemyWorld(stage=6, full_event_stream=True)
        enemy = Enemy7294(world, 0x7D41)
        self.assertEqual((0x02C8, 0x0150, 2, 0x0040, 0x0080, 0x9050),
                         (enemy.x, enemy.y, enemy.direction,
                          enemy.fire_a, enemy.fire_b,
                          enemy.projectile_script))
        world.frame_counter = 0
        world._terrain_code = lambda _x, _y: 0x0FFF
        enemy.update(world, -1)
        self.assertEqual((0x02C7, 0x0150, 0xE0, 3, 6, 0x3326),
                         (enemy.x, enemy.y, enemy.y_fraction,
                          enemy.direction, enemy.animation,
                          enemy.descriptor))

        enemy.direction = 2
        enemy.fire_counter = enemy.fire_a - 1
        world._terrain_code = lambda _x, _y: 0x0001
        enemy.update(world, 0)
        self.assertEqual(1, world.projectile_spawns)
        self.assertIsInstance(world.pending[0], Projectile7435)
        self.assertEqual(8, world.pending[0].terrain_delay)

    def test_5eed_position_direction_motion_and_three_cell_ray(self) -> None:
        world = M72EnemyWorld(stage=6, full_event_stream=True)
        enemy = Enemy5EED(world, 0x2022)
        self.assertEqual((0x02C8, 0x0108, 2, False, False, 0x20, 10),
                         (enemy.x, enemy.y, enemy.direction,
                          enemy.turn_clockwise, enemy.mirrored,
                          enemy.speed_offset, enemy.hp))
        world.frame_counter = 0
        world._terrain_code = lambda _x, _y: 0x0FFF
        enemy.update(world, -1)
        self.assertEqual((0x02C5, 0x0108, 0, 2, 0x2AC0),
                         (enemy.x, enemy.y, enemy.y_fraction,
                          enemy.direction, enemy.descriptor))

        # A solid first ray sample rotates counter-clockwise: 2 -> 1.
        world._terrain_code = lambda _x, _y: 0x0001
        enemy.update(world, 0)
        self.assertEqual(1, enemy.direction)

        mirrored = Enemy5EED(world, 0x216F)
        self.assertTrue(mirrored.turn_clockwise)
        self.assertTrue(mirrored.mirrored)
        self.assertEqual(1, mirrored.direction)
        mirrored.update(world, 0)
        self.assertEqual(2, mirrored.direction)

    def test_8c12_exact_blast_timing_and_bytewise_terrain_path(self) -> None:
        world = M72EnemyWorld(stage=7, full_event_stream=True)
        control = StageObject8C12(world, 0x4000)
        self.assertEqual((0x02C0, 0x009C, 0x3C5E, 8),
                         (control.x, control.y,
                          control.terrain_path, control.timer))
        for _ in range(8):
            control.update(world, -1)
        self.assertEqual((1, 0x10, 1),
                         (control.phase, control.timer, len(world.pending)))
        blast = world.pending[0]
        self.assertEqual((0x02B4, 0x00AA, "e7be"),
                         (blast.x, blast.y, blast.effect))

        world._terrain_address = lambda _x, _y: 0x1200
        writes = []
        world._replace_terrain = lambda address, code, attr: writes.append(
            (address, code, attr))
        control._apply_terrain_path(world)
        self.assertEqual([
            (0x0F00, 0x0556, 0x000A),
            (0x0F04, 0x0560, 0x000A),
            (0x0F08, 0x056A, 0x000A),
        ], writes[:3])

    def test_6acb_ordinal_four_preserves_rom_bx_lifetime_quirk(self) -> None:
        world = M72EnemyWorld()
        world.rng = SimpleNamespace(next=lambda: 3)
        parent = TerrainModifierParent6ACB()
        record = 0x2E46 + 3 * 8
        child = TerrainModifierChild6C37(world, parent, record, 4)
        # `$6B13…$6B2C` leaves BX at zero after the difficulty-zero HP
        # lookup, so `$F8A7` receives ES:$0004=$5E8B (row 8), not the zero
        # command at record+$04.  MAME writes these fields on VBlank 4931.
        self.assertEqual((0x0040, 0x0140, 0x8F90, 0x000C),
                         (child.fire_a, child.fire_b,
                          child.projectile_script, child.fire_counter))

    def test_6c37_rotating_snake_uses_both_rom_descriptor_rings(self) -> None:
        world = M72EnemyWorld()
        parent = TerrainModifierParent6ACB()
        ordinary = TerrainModifierChild6C37(world, parent, 0x2E46, 1)
        core = TerrainModifierChild6C37(world, parent, 0x2E5E, 4)
        ordinary.motion.phase = 7
        core.motion.phase = 12
        ordinary.motion.update = lambda _rom, _enemy: None
        core.motion.update = lambda _rom, _enemy: None

        ordinary.update(world, 0)
        core.update(world, 0)

        self.assertTrue(ordinary.render_ready)
        self.assertTrue(core.render_ready)
        self.assertEqual(0x2F0E + 7 * 6, ordinary.descriptor)
        self.assertEqual(0x2F6E + 12 * 6, core.descriptor)

    def test_6e27_projectile_uses_slot_phased_rom_animation(self) -> None:
        world = M72EnemyWorld()
        parent = TerrainModifierParent6ACB()
        source = TerrainModifierChild6C37(world, parent, 0x2E46, 1)
        source.projectile_script = 0x8F90
        source.motion.phase = 0
        projectile = TerrainModifierProjectile6E27(world, source, parent)
        projectile.object_slot = 0x0640
        projectile.x_velocity = projectile.y_velocity = 0
        parent.x = 0
        world.frame_counter = 8
        world._terrain_code = lambda _x, _y: 0x0FFF

        projectile.update(world, 0)

        self.assertTrue(projectile.render_ready)
        self.assertEqual(0x2EFA, projectile.descriptor)

    def test_6c61_protected_child_consumes_hit_without_damage(self) -> None:
        world = M72EnemyWorld()
        parent = TerrainModifierParent6ACB()
        parent.child_count = 1
        child = TerrainModifierChild6C37(world, parent, 0x2E46, 1)
        world.player_native = (0x01CB, 0x0110)
        parent.x = 0x0200
        child.take_damage(world, 1)
        self.assertTrue(child.alive)
        self.assertEqual(1, child.hp)

        parent.x = 0x01CA
        child.take_damage(world, 1)
        self.assertTrue(child.alive)
        self.assertEqual("death_6d15", child.state)
        self.assertEqual(1, parent.child_count)
        self.assertEqual(0x14, world.resources.types[child.palette])
        self.assertEqual((200, [0x86EC]),
                         (world.score, world.score_awards))
        self.assertEqual([0x52], world.sound_commands)
        blasts = [item for item in world.pending
                  if isinstance(item, ExplosionEffect)]
        self.assertEqual(1, len(blasts))
        self.assertEqual(0xE000, blasts[0].scheduler_priority)

        child.x = 0x00DF
        child.update(world, 0)
        self.assertFalse(child.alive)
        self.assertEqual(0, parent.child_count)

    def test_86a6_uses_rom_8020_scheduler_priority(self) -> None:
        world = M72EnemyWorld()
        enemy = Animated86A6(world, 0)
        # `$86B0` passes CX=$8020 to `$03A6`; MAME slot $1140 exposes the
        # same word at +$18 on VBlank 6415.
        self.assertEqual(0x8020, enemy.scheduler_priority)

    def test_5a02_uses_rom_8020_scheduler_priority(self) -> None:
        world = M72EnemyWorld()
        enemy = GroundWalker(world, 0x1408)
        # `$5A02` requests CX=$8020; MAME slot $0A40 retains that word at
        # +$18 for the walker allocated on VBlank 6933.
        self.assertEqual(0x8020, enemy.scheduler_priority)

    def test_60ba_family_uses_rom_scheduler_priorities(self) -> None:
        world = M72EnemyWorld()
        parent = Handler60BA(world, 0)
        projectile = Handler60BAProjectile(world, parent)
        child = Handler60BAChild(world, parent, 0x2CE4)
        # `$60C4`, `$6657` and `$6723` pass these exact CX values to
        # allocator `$03A6`; the same words are visible in MAME at +$18.
        self.assertEqual((0x8020, 0x6000, 0x5000),
                         (parent.scheduler_priority,
                          projectile.scheduler_priority,
                          child.scheduler_priority))

        slot = world.object_pool.take()
        self.assertIsNotNone(slot)
        world.object_pool.residue[slot] = (0x81, 0xFE)
        world.object_pool.bind(projectile, slot)
        self.assertEqual(0x81, projectile.x_fraction)

    def test_6243_integrates_x_not_y(self) -> None:
        world = M72EnemyWorld()
        parent = Handler60BA(world, 0)
        parent.state = "6243"
        parent.timer = 2
        parent.x = 0x0200
        parent.y = 0x00B8
        parent.x_fraction = parent.y_fraction = 0
        world._scheduler_foreground_delta = 0
        parent.update(world, 0)
        self.assertEqual((0x01FF, 0x00B8, 0, 0),
                         (parent.x, parent.y,
                          parent.x_fraction, parent.y_fraction))

    def test_657c_spawns_children_before_foreground_scroll(self) -> None:
        world = M72EnemyWorld()
        parent = Handler60BA(world, 0)
        parent.state = "657c"
        parent.x = 0x0209
        parent.y = 0x00B8
        world.frame_counter = 0x007F

        parent.update(world, -1)

        children = [item for item in world.pending
                    if isinstance(item, Handler60BAChild)]
        self.assertEqual(4, len(children))
        self.assertEqual((0x0209,) * 4,
                         tuple(child.x for child in children))
        self.assertEqual(0x0208, parent.x)

    def test_6b4f_build_and_erase_walk_the_exact_same_rom_path(self) -> None:
        world = M72EnemyWorld()
        writes = []
        world._terrain_address = lambda _x, _y: 0x1580
        world._replace_terrain = (
            lambda address, code, attribute:
            writes.append((address, code, attribute)))
        parent = TerrainModifierParent6ACB()
        parent.state = "active"
        parent.child_count = 1
        parent.timer = 1
        world.frame_counter = 0
        parent.update(world, -1)
        initial = tuple(address for address, _code, _attribute in writes)
        self.assertEqual((20, 0x1580, 0x2880),
                         (len(initial), initial[0], initial[-1]))
        self.assertTrue(all(code == 0x03E8 and attribute == 0x0081
                            for _address, code, attribute in writes))

        parent.build_path = 1
        parent.erase_path = 1
        for step in range(20):
            world.frame_counter = 7 + step * 8
            parent.update(world, 0)
        incremental = writes[len(initial):]
        self.assertEqual(initial,
                         tuple(item[0] for item in incremental[0::2]))
        self.assertEqual(initial,
                         tuple(item[0] for item in incremental[1::2]))
        self.assertTrue(all(item[1:] == (0x03E8, 0x0081)
                            for item in incremental[0::2]))
        self.assertTrue(all(item[1:] == (0x0FA0, 0x0081)
                            for item in incremental[1::2]))
        self.assertEqual((0, 0), (parent.build_path, parent.erase_path))

    def test_6e9b_motion_gate_and_overlapping_debris_pairs(self) -> None:
        world = M72EnemyWorld(stage=7, full_event_stream=True)
        enemy = FixedLarge6E9B(world)
        world._collision_codes = lambda _x, _y: (0x0FFF, 0x07D0)
        enemy.update(world, -1)
        self.assertEqual((0x010F, 0xC0, 0xC8),
                         (enemy.x, enemy.x_fraction, enemy.hp))
        world._collision_codes = lambda _x, _y: (0x0001, 0x07D0)
        enemy.update(world, -1)
        self.assertEqual((0x010E, 0xC0), (enemy.x, enemy.x_fraction))

        enemy.take_damage(world, 0xC8)
        debris = [item for item in world.pending
                  if isinstance(item, ExplosionEffect)]
        self.assertEqual(18, len(debris))
        self.assertTrue(all(item.effect == "e7b6" for item in debris))

    def test_875d_parameter_script_and_first_child(self) -> None:
        world = M72EnemyWorld(stage=2, full_event_stream=True)
        parent = Spawner875D(world)
        for _ in range(51):
            parent.update(world, 0)
        self.assertEqual((0x3B06, 51, 0x24, 0xD0, 1),
                         (parent.script_pointer, parent.counter,
                          parent.spawn_reload, parent.target_y,
                          len(world.pending)))
        child = world.pending[0]
        self.assertIsInstance(child, Spawner875DChild)
        self.assertEqual((0x02C0, 0x0104, 0, -0x0180),
                         (child.x, child.y, child.delay,
                          child.x_velocity))
        child.update(world, -1)
        self.assertEqual((0x02BD, 0x80, 0x0104, 0x30, 0x3BB2),
                         (child.x, child.x_fraction, child.y,
                          child.y_fraction, child.descriptor))

    def test_7d68_six_states_and_8d85_child_use_rom_tables(self) -> None:
        world = M72EnemyWorld(stage=2, full_event_stream=True)
        enemy = Enemy7D68(world, 0x9001)
        self.assertEqual((1, 0x02D0, 0x00A0, 0x37F2, 0x384E, 0x28),
                         (enemy.variant, enemy.x, enemy.y, enemy.descriptor,
                          enemy.collision_table, enemy.hp))
        self.assertEqual((0x29, 0x55),
                         (world.resources.types[enemy.palette],
                          world.resources.types[enemy.flash_palette]))

        for _ in range(97):
            enemy.update(world, -1)
        self.assertEqual(("rise", 8, 0x026F, 0x00A0),
                         (enemy.state, enemy.timer, enemy.x, enemy.y))
        for _ in range(8):
            enemy.update(world, -1)
        self.assertEqual(("open", 0x3F, 0x00B0),
                         (enemy.state, enemy.timer, enemy.y))

        enemy.state = "hold"
        enemy.timer = 0xC0
        enemy.update(world, 0)
        self.assertEqual((0x383A, 0xBF, 1),
                         (enemy.descriptor, enemy.timer,
                          len(world.pending)))
        child = world.pending[0]
        self.assertIsInstance(child, Child8D85)
        self.assertEqual((0xA484, 3, -0x20, -0x28, 0x3F26, 0x3F6E),
                         (child.motion.script, child.motion.commands,
                          child.x_velocity, child.y_velocity,
                          child.descriptor, child.collision_table))
        self.assertEqual((0x3E, 0x55),
                         (world.resources.types[child.palette],
                          world.resources.types[child.flash_palette]))

    def test_7d68_and_8d85_are_two_record_composites(self) -> None:
        class RecordingAtlas:
            def __init__(self) -> None:
                self.codes = []

            def draw(self, _target, descriptor, _palette, _resource_type,
                     _anchor_x, _anchor_y) -> None:
                self.codes.append(descriptor.code)

        world = M72EnemyWorld(stage=2, full_event_stream=True)
        parent = Enemy7D68(world, 0)
        child = Child8D85(world, parent, 0xA434, -0x20, -0x28)
        world.enemies = [parent, child]
        recorder = RecordingAtlas()
        world.atlas = recorder
        world.draw(None)
        self.assertEqual(4, len(recorder.codes))
        self.assertEqual(world.rom.word(parent.descriptor + 2),
                         recorder.codes[0])
        self.assertEqual(world.rom.word(parent.descriptor + 8),
                         recorder.codes[1])
        self.assertEqual(world.rom.word(child.descriptor + 2),
                         recorder.codes[2])
        self.assertEqual(world.rom.word(child.descriptor + 8),
                         recorder.codes[3])

    def test_78f8_parent_spawns_both_exact_rom_formation_lengths(self) -> None:
        cases = ((0x1C26, 0x4400, 0x34B6, 0xA112, 11),
                 (0x1E1A, 0x4200, 0x34E2, 0xA0EA, 17))
        for command, priority, sequence, motion_root, count in cases:
            with self.subTest(command=hex(command)):
                world = M72EnemyWorld(stage=5, full_event_stream=True)
                parent = Formation78F8Parent(world, command)
                self.assertEqual((priority, sequence, motion_root, 1),
                                 (parent.priority, parent.sequence,
                                  parent.motion_root, parent.timer))
                spawned = []
                while parent.alive:
                    parent.update(world, 0)
                    spawned.extend(world.pending)
                    world.pending.clear()
                self.assertEqual(count, len(spawned))
                self.assertIsInstance(spawned[0], Formation78F8Child)
                self.assertEqual(("first", 0x0E, 0x25, priority),
                                 (spawned[0].state, spawned[0].hp,
                                  world.resources.types[spawned[0].palette],
                                  spawned[0].priority))
                self.assertEqual(("terminal", 6, 0x25),
                                 (spawned[-1].state, spawned[-1].hp,
                                  world.resources.types[spawned[-1].palette]))
                self.assertTrue(all(
                    item.previous is spawned[index - 1]
                    for index, item in enumerate(spawned[1:], 1)))

    def test_78f8_link_propagation_and_escape_velocity_are_literal(self) -> None:
        world = M72EnemyWorld(stage=5, full_event_stream=True)
        parent = Formation78F8Parent(world, 0x1C26)
        parent.update(world, 0)
        first = world.pending.pop()
        for _ in range(10):
            parent.update(world, 0)
        second = world.pending.pop()
        first.state_flag = 2
        first.delay = 7
        world.frame_counter = 0
        second.update(world, 0)
        self.assertEqual((2, 11, 3),
                         (second.state_flag, second.delay,
                          second.motion.commands))

        second.state_flag = 0
        second.delay = 0
        first.state_flag = 1
        second.update(world, 0)
        self.assertEqual(("escape", 1, -0x00D0, 0x0200),
                         (second.state, second.state_flag,
                          second.x_velocity, second.y_velocity))
        x_before, y_before = second.x, second.y
        second.update(world, 0)
        self.assertEqual((x_before - 1, 0x30, y_before + 2, 0),
                         (second.x, second.x_fraction,
                          second.y, second.y_fraction))

    def test_915b_parent_builds_exact_twenty_two_part_rom_chain(self) -> None:
        world = M72EnemyWorld(stage=2, full_event_stream=True)
        parent = Multipart915BParent(world, 0x7404)
        self.assertEqual((0xA652, 0x02C8, 0x0130, 0x00C0,
                          0x40C6, 0x201F, 2),
                         (parent.motion_root, parent.x, parent.y,
                          parent.base_timer, parent.sequence,
                          parent.priority, parent.cleanup_ordinal))
        spawned = []
        while parent.alive:
            parent.update(world, 0)
            spawned.extend(world.pending)
            world.pending.clear()
        self.assertEqual(22, len(spawned))
        self.assertEqual(
            ["first", "second"] + ["main"] * 18 + ["terminal", "late"],
            [child.state for child in spawned])
        self.assertEqual((0x201E, 2, 0x2009, 44),
                         (spawned[0].priority, spawned[0].cleanup_counter,
                          spawned[-1].priority,
                          spawned[-1].cleanup_counter))
        self.assertEqual((0x40, 0x40, 0x3F, 0x40),
                         tuple(world.resources.types[item.palette]
                               for item in (spawned[0], spawned[1],
                                            spawned[2], spawned[-1])))
        self.assertTrue(all(
            item.previous is spawned[index - 1]
            for index, item in enumerate(spawned[1:], 1)))

    def test_915b_pulse_radial_children_flash_and_cleanup_follow_rom(self) -> None:
        world = M72EnemyWorld(stage=2, full_event_stream=True)
        parent = Multipart915BParent(world, 0x7404)
        children = []
        while len(children) < 3:
            parent.update(world, 0)
            children.extend(world.pending)
            world.pending.clear()
        first, second, main = children
        first.pulse_timer = 1
        first.update(world, 0)
        self.assertEqual((0x00C0, 1),
                         (first.pulse_timer, first.pulse))
        second.update(world, 0)
        self.assertEqual(1, second.pulse)

        world.player_native = (0x0100, 0x0080)
        main.update(world, 0)
        radial = [item for item in world.pending
                  if isinstance(item, Radial95F1)]
        self.assertEqual(8, len(radial))
        self.assertEqual((0, 0x01E0, 0x3F, 0x4196),
                         (radial[0].x_velocity, radial[0].y_velocity,
                          world.resources.types[radial[0].palette],
                          radial[0].collision_table))

        world.stage_controller_handler = 0xA3B3
        world.frame_counter = 1
        main.update(world, 0)
        self.assertEqual(main.flash_palette, main.active_palette)
        world.frame_counter = 2
        main.update(world, 0)
        self.assertEqual(main.palette, main.active_palette)

        world.stage_controller_handler = 0xA523
        first.cleanup_counter = 2
        first.update(world, 0)
        self.assertTrue(first.alive)
        first.update(world, 0)
        self.assertFalse(first.alive)
        self.assertTrue(first.destroyed)

    def test_a71d_initializer_builds_three_rom_routed_bodies_and_attachments(self) -> None:
        world = M72EnemyWorld(stage=5, full_event_stream=True)
        controller = MultipartA71DController(world)
        self.assertEqual(0x38, controller.selector)
        controller.update(world, 0)
        bodies = [item for item in world.pending
                  if isinstance(item, MultipartA71DBody)]
        attachments = [item for item in world.pending
                       if isinstance(item, AttachedAC4C)]
        self.assertEqual(["upper", "middle", "lower"],
                         [item.body_kind for item in bodies])
        self.assertEqual(3, len(attachments))
        self.assertEqual((0x5B0E, 0x5B2C, 0x5B4A),
                         tuple(item.route_list for item in bodies))
        self.assertEqual((0x5B54, 0x5B54, 0x5B54),
                         tuple(item.motion_pointer for item in bodies))
        self.assertTrue(all((item.x, item.y) == (0x0100, 0x0108)
                            for item in bodies))
        self.assertEqual((0x41, 0x53),
                         (world.resources.types[bodies[0].palette],
                          world.resources.types[bodies[0].alt_palette]))
        self.assertEqual((0x42, 0x53),
                         (world.resources.types[attachments[0].palette],
                          world.resources.types[attachments[0].alt_palette]))

    def test_a71d_motion_sync_fire_damage_and_debris_are_rom_driven(self) -> None:
        world = M72EnemyWorld(stage=5, full_event_stream=True)
        controller = MultipartA71DController(world)
        controller.update(world, 0)
        upper, middle, lower = [
            item for item in world.pending
            if isinstance(item, MultipartA71DBody)]
        world.pending.clear()
        self.assertEqual((0x0100, 0, 0x0160),
                         (upper.x_velocity, upper.y_velocity,
                          upper.motion_timer))
        upper.update(world, 0)
        self.assertEqual((0x0101, 0, 0x0108, 0, 0x015F),
                         (upper.x, upper.x_fraction, upper.y,
                          upper.y_fraction, upper.motion_timer))

        upper.motion_timer = middle.motion_timer = lower.motion_timer = 0
        upper.update(world, 0)
        middle.update(world, 0)
        lower.update(world, 0)
        self.assertEqual(7, controller.arrived_mask)
        controller.update(world, 0)
        self.assertTrue(controller.advance_signal)
        upper.update(world, 0)
        self.assertEqual((0x5DCC, -0x0180, 0, 0x0080),
                         (upper.motion_pointer, upper.x_velocity,
                          upper.y_velocity, upper.motion_timer))

        upper.fire_timer = 1
        world.player_native = (0x0200, upper.y)
        upper.update(world, 0)
        shots = [item for item in world.pending
                 if isinstance(item, Handler5CEAShot)]
        self.assertEqual(1, len(shots))
        self.assertEqual(0x0300, shots[0].x_velocity)
        self.assertIn((shots[0].y - upper.y) & 0xFFFF,
                      tuple(world.rom.word(0x5850 + index * 2)
                            for index in range(8)))

        upper.take_damage(world, 0x28)
        self.assertEqual(("debris", 1, 0x40, 0xFF),
                         (upper.state, controller.completed_mask,
                          upper.debris_timer, upper.palette))
        world.frame_counter = 2
        upper.update(world, 0)
        self.assertIsInstance(world.pending[-1], ExplosionEffect)

        lower.y = 0x00A0
        lower.pair_timer = 0x0F
        lower.update(world, 0)
        pair = [item for item in world.pending
                if isinstance(item, DebrisAEFB)]
        self.assertEqual(2, len(pair))
        self.assertEqual((0x58CE, 0x58D4),
                         tuple(item.descriptor + item.phase_offset
                               for item in pair))

    def test_b7fb_root_constructs_exact_five_segments_and_three_controllers(self) -> None:
        world = M72EnemyWorld(stage=7, full_event_stream=True)
        root = BossB7FBController(world)
        segments = [item for item in world.pending
                    if isinstance(item, BossB7FBSegment)]
        self.assertEqual(5, len(segments))
        self.assertEqual((0x02D0, 0x0310, 0x0350, 0x0390, 0x03D0),
                         tuple(item.x for item in segments))
        self.assertEqual((0x03C0, 0x03A0, 0x0380, 0x0360, 0x0340),
                         tuple(item.threshold for item in segments))
        self.assertEqual((0x0160,) * 5, tuple(item.y for item in segments))
        self.assertEqual(1, sum(isinstance(item, BossB7FBRandomSpawner)
                                for item in world.pending))
        self.assertEqual(1, sum(isinstance(item, BossB7FBMissileSpawner)
                                for item in world.pending))
        self.assertEqual(1, sum(isinstance(item, BossB7FBCore)
                                for item in world.pending))

    def test_b7fb_root_terrain_segment_spawners_and_core_tables(self) -> None:
        world = M72EnemyWorld(stage=7, full_event_stream=True)
        writes = []
        world._terrain_cell = lambda address: (address & 0x0FFF, 3)
        world._replace_terrain = lambda address, code, attr: writes.append(
            (address, code, attr))
        root = BossB7FBController(world)
        world.pending.clear()
        root.timer = 0x02FF
        root.update(world, 0)
        self.assertEqual(0x80, len(writes))
        self.assertEqual((0x1002, 2, 0x83), writes[0])
        self.assertEqual((0x11FE, 0x1FE, 0x83), writes[-1])

        segment = BossB7FBSegment(world, root, 0x02D0, 0x03C0)
        segment.timer = 0x03CE
        segment.update(world, -1)
        self.assertEqual((0x02CF, 0x60F2),
                         (segment.x, segment.descriptor))
        segment.timer = 0x03DE
        segment.update(world, 0)
        self.assertEqual(0x60FE, segment.descriptor)
        segment.take_damage(world, 0x200)
        self.assertEqual(0xA0, segment.damage_accumulator)
        self.assertTrue(segment.alive)
        self.assertFalse(root.defeated)

        spawner = BossB7FBRandomSpawner(world, root)
        spawner.timer = 0x035F
        spawner.reload = 1
        spawner.update(world, 0)
        child = world.pending[-1]
        self.assertIsInstance(child, BossB7FBRandomChild)
        self.assertEqual((0x01E0, 0x0168, -0x0200),
                         (child.x, child.y, child.y_velocity))

        core = BossB7FBCore(world, root)
        core.timer = 0x04FF
        core.update(world, 0)
        self.assertIsInstance(world.pending[-1], BossB7FBCoreChild)
        self.assertEqual((0xA7FC, 1, 0x5F, 0x6244),
                         (world.pending[-1].motion.script,
                          world.pending[-1].motion.commands,
                          world.resources.types[world.pending[-1].palette],
                          world.pending[-1].collision_table))
        index = (core.phase & 0xF8) >> 2
        self.assertEqual(world.rom.word(0x633A + index), core.descriptor)
        self.assertEqual(world.rom.word(0x637C + index),
                         core.collision_table)
        writes.clear()
        core.take_damage(world, 0x55)
        self.assertTrue(root.defeated)
        self.assertEqual(0x800, len(writes))
        self.assertTrue(all(attribute == 3
                            for _address, _code, attribute in writes))

    def test_one_event_per_vblank(self) -> None:
        world = M72EnemyWorld()
        self.assertEqual(0xB9B3, world.current_event().address)
        world.update(0x06BF, 0xFFFF, 10)
        self.assertEqual(0xB9B3, world.current_event().address)
        world.update(0x06C0, 0xFFFF, 11)
        self.assertEqual(0xB9B7, world.current_event().address)
        world.update(0x06C0, 0xFFFF, 12)
        self.assertEqual(0xB9BB, world.current_event().address)

    def test_first_enemy_is_spawned_from_rom_event(self) -> None:
        world = M72EnemyWorld()
        while world.current_event().address != 0xB9D7:
            world.update(0xFFFF, 0xFFFF, 10)
        world.update(0x06FC, 0xFFFF, 10)
        red = next(enemy for enemy in world.enemies
                   if isinstance(enemy, RedFlyer))
        self.assertEqual(0x0140, red.y)  # command $6C04 -> ES:$8DB8
        self.assertEqual(0x02C8, red.x)  # runtime handler begins next pass
        self.assertEqual(0x0D, world.resources.types[red.palette])

    def test_red_object_state_matches_mame_frame_1500(self) -> None:
        world = M72EnemyWorld()
        scroll = M72Scroll()
        counter = 0x0292
        while scroll.vblank < 1500:
            scroll.advance()
            counter = (counter + 1) & 0xFFFF
            world.update(scroll.progression, scroll.foreground_delta, counter)
        red = sorted((enemy for enemy in world.enemies
                      if isinstance(enemy, RedFlyer)), key=lambda item: item.x)
        actual = [(enemy.x, enemy.y, enemy.motion.script,
                   enemy.motion.pointer, enemy.motion.phase)
                  for enemy in red]
        self.assertEqual([
            (0x011F, 0x00DD, 0x9AEE, 0xB13E, 0x06),
            (0x014C, 0x00D5, 0x9AEA, 0xB3A0, 0x08),
            (0x016F, 0x00EC, 0x9AE8, 0xB382, 0x09),
            (0x019C, 0x00E9, 0x9AE4, 0xB188, 0x09),
        ], actual)

    def test_first_ground_walker_matches_mame_frames_1471_to_1810(self) -> None:
        world = M72EnemyWorld()
        scroll = M72Scroll()
        tilemaps = M72Tilemaps()
        stage = Stage.__new__(Stage)
        stage.m72_scroll = scroll
        stage.tilemaps = tilemaps
        counter = 0x0292
        expected = {
            # `$1BA7` sees the later same-VBlank progression, so allocation is
            # already present in the end-of-frame 1471 object trace.
            1471: (0x02C8, 0x00B8, "falling", 0x0000, 0, 0x00),
            1472: (0x02C7, 0x00B5, "falling", 0x0000, 0, 0x00),
            1473: (0x02C7, 0x00B2, "falling", 0x0000, 0, 0x00),
            1474: (0x02C6, 0x00B0, "landing", 0x292A, 4, 0x00),
            1475: (0x02C6, 0x00B0, "landing", 0x292A, 3, 0x00),
            1487: (0x02BF, 0x00B0, "walking", 0x2930, 4, 0x40),
            1500: (0x02AE, 0x00B0, "walking", 0x2930, 4, 0x80),
            1800: (0x0137, 0x00B0, "walking", 0x2930, 4, 0x80),
            1809: (0x012C, 0x00B0, "walking", 0x2930, 4, 0xC0),
            1810: None,
        }
        while scroll.vblank < max(expected):
            scroll.advance()
            tilemaps.advance(scroll)
            counter = (counter + 1) & 0xFFFF
            world.update(scroll.dispatch_progression,
                         scroll.dispatch_foreground_delta, counter,
                         stage.terrain_code, stage.collision_codes,
                         background_delta=scroll.dispatch_background_delta)
            if scroll.vblank not in expected:
                continue
            walkers = [enemy for enemy in world.enemies
                       if isinstance(enemy, GroundWalker)]
            if expected[scroll.vblank] is None:
                self.assertEqual([], walkers)
                continue
            self.assertEqual(1, len(walkers))
            enemy = walkers[0]
            self.assertEqual(
                expected[scroll.vblank],
                (enemy.x, enemy.y, enemy.state, enemy.animation_pointer,
                 enemy.animation_timer, enemy.x_fraction),
                f"MAME frame {scroll.vblank}",
            )

    def test_ground_walker_f8a7_parameters_and_f63a_projectile(self) -> None:
        world = M72EnemyWorld()
        world.rng.reset()
        walker = GroundWalker(world, 0x1488)
        # CL=$88 selects row 8 of ES:$8E10.  Fresh `$EDE9` yields $0304;
        # `$F8E5` shifts it twice and masks it with first_counter-1.
        self.assertEqual((0x0040, 0x0140, 0x8F90, 0x0010),
                         (walker.fire_a, walker.fire_b,
                          walker.projectile_script, walker.fire_counter))
        for _ in range(0x30):
            walker.update(world, 0)
        self.assertEqual(0x0040, walker.fire_counter)
        self.assertEqual(1, world.projectile_spawns)
        self.assertEqual(1, len(world.pending))
        projectile = world.pending[0]
        self.assertIsInstance(projectile, EnemyProjectile)
        # During those $30 falling updates Y changes $00B8->$0028.  `$1D89`
        # therefore selects sector $38 and the pair at `$8FC8/$8FCA`.
        self.assertEqual((-0x0160, 0x0160),
                         (projectile.x_velocity, projectile.y_velocity))

        world.pending.clear()
        for _ in range(0x0100):
            walker.update(world, 0)
        self.assertEqual(0, walker.fire_counter)
        self.assertEqual(2, world.projectile_spawns)
        self.assertEqual(1, len(world.pending))

    def test_ground_walker_zero_f8a7_record_does_not_fire(self) -> None:
        world = M72EnemyWorld()
        walker = GroundWalker(world, 0x1408)
        self.assertEqual((0, 0, 0),
                         (walker.fire_a, walker.fire_b,
                          walker.projectile_script))
        for _ in range(0x80):
            walker.update(world, 0)
        self.assertEqual(0, world.projectile_spawns)
        self.assertEqual([], world.pending)

    def test_ground_walker_rom_probes_select_turn_walk_or_edge(self) -> None:
        def ready() -> tuple[M72EnemyWorld, GroundWalker]:
            world = M72EnemyWorld()
            walker = GroundWalker(world, 0x1408)
            walker.state = "walking"
            walker.x = 0x0200
            walker.y = 0x0100
            walker.x_fraction = 0
            world.frame_counter = 0
            return world, walker

        # `$5A7D…$5AE3`: no terrain twenty units below/ahead enters the
        # three-frame, four-VBlank-per-frame turning descriptor stream.
        world, walker = ready()
        probes: list[tuple[int, int]] = []
        world._terrain_code = lambda x, y: (
            probes.append((x, y)) or 0x0FFF)
        walker.update(world, 0)
        self.assertEqual("turning", walker.state)
        self.assertEqual((0x292A, 4),
                         (walker.animation_pointer, walker.animation_timer))
        self.assertEqual([(0x01EF, 0x00EC)], probes)

        # A solid first and empty second probe means the surface continues;
        # handler `$5A2B` remains installed and walking must continue.
        world, walker = ready()
        codes = iter((0x0001, 0x0FFF))
        world._terrain_code = lambda _x, _y: next(codes)
        walker.update(world, 0)
        self.assertEqual("walking", walker.state)

        # Both probes solid select `$5CA6`: the object stays attached to the
        # scrolling edge instead of keeping its old Y and floating in space.
        world, walker = ready()
        world._terrain_code = lambda _x, _y: 0x0001
        walker.update(world, 0)
        self.assertEqual("edge", walker.state)
        world.player_native = (walker.x - 2, 0)
        walker.update(world, -1)
        self.assertEqual(0x293A, walker.descriptor)
        world.player_native = (walker.x + 1, 0)
        walker.update(world, -1)
        self.assertEqual(0x295E, walker.descriptor)

    def test_ground_walker_turning_and_scripted_states_reach_fall(self) -> None:
        world = M72EnemyWorld()
        walker = GroundWalker(world, 0x1408)
        walker.state = "turning"
        walker.x = 0x0200
        walker.y = 0x0100
        walker.animation_pointer = 0x292A
        walker.animation_timer = 4
        world._terrain_code = lambda _x, _y: 0x0FFF

        for _ in range(12):
            walker.update(world, 0)
        self.assertEqual("scripted", walker.state)
        self.assertIsNotNone(walker.motion)
        self.assertEqual(world.resources.types[walker.secondary_palette],
                         world.resources.types[walker.active_palette])

        for _ in range(256):
            walker.update(world, 0)
            if walker.state == "falling":
                break
        self.assertEqual("falling", walker.state)
        self.assertLess(walker.y, 0x0100)

    def test_ground_walker_edge_records_match_mame_frame_3500(self) -> None:
        world = M72EnemyWorld()
        scroll = M72Scroll()
        tilemaps = M72Tilemaps()
        stage = Stage.__new__(Stage)
        stage.m72_scroll = scroll
        stage.tilemaps = tilemaps
        counter = 0x0292
        while scroll.vblank < 3500:
            scroll.advance()
            tilemaps.advance(scroll)
            # The MAME frame callback dumps work RAM before this VBlank's
            # `$0467` main pass.  Snapshot 3500 therefore contains object
            # state produced by pass 3499.
            if scroll.vblank == 3500:
                break
            counter = (counter + 1) & 0xFFFF
            world.update(scroll.dispatch_progression,
                         scroll.dispatch_foreground_delta, counter,
                         stage.terrain_code, stage.collision_codes)
        edge = sorted(
            (enemy.x, enemy.y, enemy.direction)
            for enemy in world.enemies
            if isinstance(enemy, GroundWalker) and enemy.state == "edge")
        self.assertEqual([
            (0x0142, 0x00B0, 1),
            (0x0143, 0x00B0, 1),
            (0x01A5, 0x00B0, 0),
        ], edge)

    def test_dobkeratops_state_matches_mame_frame_8500(self) -> None:
        world = M72EnemyWorld()
        scroll = M72Scroll()
        counter = 0x0292
        while scroll.vblank < 8500:
            scroll.advance()
            counter = (counter + 1) & 0xFFFF
            world.update(scroll.progression, scroll.foreground_delta, counter,
                         background_delta=scroll.background_delta)
        body = next(enemy for enemy in world.enemies
                    if isinstance(enemy, DobkeratopsBody))
        self.assertEqual(("active", 0x026E, 0x0100, 0x0066),
                         (body.state, body.x, body.y, body.timer))
        tip = next(enemy for enemy in world.enemies
                   if isinstance(enemy, DobkeratopsTentacle) and enemy.tip)
        self.assertEqual((0x01FD, 0x010F, 0x4C88, 0x0007),
                         (tip.x, tip.y, tip.script_pointer, tip.step_timer))

        # Все 18 звеньев и наконечник сверяются с живыми 64-байтными
        # object records MAME, включая неочищаемые `$03EC` Q8 fractions.
        snapshot = (ROOT / "Build" / "Arcade" / "MAME" /
                    "stage1_invincible_trace" /
                    "frame_008500_workram.bin").read_bytes()
        arcade = {}
        for offset in range(0x0540, 0x2054, 0x40):
            handler = struct.unpack_from("<H", snapshot, offset)[0]
            if handler not in (0xA08B, 0xA1A3):
                continue
            script_start = struct.unpack_from("<H", snapshot,
                                              offset + 0x24)[0]
            arcade[script_start] = (
                struct.unpack_from("<H", snapshot, offset + 4)[0],
                snapshot[offset + 3],
                struct.unpack_from("<H", snapshot, offset + 8)[0],
                snapshot[offset + 7],
                struct.unpack_from("<H", snapshot, offset + 0x22)[0],
                struct.unpack_from("<H", snapshot, offset + 0x14)[0],
            )
        python = {
            enemy.script_start: (
                enemy.x, enemy.x_fraction, enemy.y, enemy.y_fraction,
                enemy.script_pointer, enemy.step_timer)
            for enemy in world.enemies
            if isinstance(enemy, DobkeratopsTentacle)
        }
        self.assertEqual(19, len(arcade))
        self.assertEqual(set(arcade), set(python))
        # This snapshot was captured with a different player/object-pool
        # history.  `$03A6` deliberately leaves Q8 bytes `+$03/+$07`
        # uncleared, so comparing those residues across two playthroughs is
        # invalid.  Script phase is identical and integer anchors may differ
        # by at most the carry generated by that legitimate residue.
        for script_start, expected in arcade.items():
            actual = python[script_start]
            self.assertLessEqual(abs(actual[0] - expected[0]), 1)
            self.assertLessEqual(abs(actual[2] - expected[2]), 1)
            self.assertEqual(expected[4:], actual[4:])

    def test_dobkeratops_tip_fire_and_collision_mask_follow_rom(self) -> None:
        world = M72EnemyWorld(difficulty=0)
        root = SimpleNamespace(body_destroyed=False)
        tip = DobkeratopsTentacle(world, root, 0, tip=True)
        tip.intro_timer = 1
        tip.update(world, 0)
        table = 0x8E10 + 3 * 6
        self.assertEqual(
            (world.rom.word(table), world.rom.word(table + 2), 0),
            (tip.fire_a, tip.fire_b, tip.projectile_script))

        even = DobkeratopsTentacle(world, root, 0x43AC)
        odd = DobkeratopsTentacle(world, root, 0x43AC + 10)
        for link in (even, odd):
            link.state = "active"
            link.intro_timer = 0
            link.step_timer = 2
            link.x_velocity = link.y_velocity = 0
        world.frame_counter = 0
        even.update(world, 0)
        odd.update(world, 0)
        self.assertFalse(even.shootable)
        self.assertTrue(odd.shootable)
        world.frame_counter = 1
        odd.update(world, 0)
        self.assertFalse(odd.shootable)

    def test_dobkeratops_body_runs_all_62_rom_debris_records(self) -> None:
        world = M72EnemyWorld()
        root = SimpleNamespace(defeated=False, body_destroyed=False)
        body = DobkeratopsBody(world, root)
        body.state = "active"
        body.shootable = True
        body.hp = 1
        body.take_damage(world, 1)
        self.assertTrue(root.body_destroyed)
        self.assertEqual(("death", 1, 0x454E, False),
                         (body.state, body.timer, body.death_pointer,
                          body.render_ready))

        world._scheduler_cursor_priority = body.scheduler_priority
        while body.alive:
            body.update(world, 0)
        world._scheduler_cursor_priority = None
        self.assertEqual(0x46C2, body.death_pointer)
        self.assertEqual(62, len(world.pending))
        handlers = Counter(
            0xE700 if isinstance(child, DobkeratopsDebrisE700)
            else {"e7b6": 0xE7B6, "e7be": 0xE7BE,
                  "e817": 0xE817}[child.effect]
            for child in world.pending)
        expected = Counter(world.rom.word(pointer + 4)
                           for pointer in range(0x454E, 0x46C2, 6))
        self.assertEqual(expected, handlers)

    def test_dobkeratops_body_death_does_not_raise_global_cleanup(self) -> None:
        world = M72EnemyWorld()
        root = DobkeratopsRoot(world)
        root.initialized = True
        root.body_destroyed = True
        root.update(world, 0)
        self.assertTrue(root.cleanup)
        self.assertFalse(world.cleanup_active)
        self.assertEqual([0x1B], world.sound_commands)

    def test_a107_plays_full_e7be_in_same_tentacle_slot(self) -> None:
        world = M72EnemyWorld()
        root = SimpleNamespace(body_destroyed=True)
        link = DobkeratopsTentacle(world, root, 0x43AC)
        link.state = "cleanup_wait"
        link.cleanup_timer = 1
        old_slot = link.object_slot = 0x0800
        link.update(world, 0)
        self.assertEqual(("cleanup_explosion", 0xFF, True),
                         (link.state, link.palette, link.alive))

        link.update(world, -1)
        self.assertEqual(("cleanup_explosion_active", old_slot, 0x01),
                         (link.state, link.object_slot,
                          world.resources.types[link.palette]))
        self.assertTrue(link.alive)
        passes = 1
        while link.alive:
            link.update(world, -1)
            passes += 1
        self.assertGreater(passes, 1)

    def test_e700_cuts_literal_sixteen_cell_auxiliary_path(self) -> None:
        world = M72EnemyWorld()
        writes = []
        world._terrain_address = lambda _x, _y: 0x1234
        world._terrain_cell = lambda address: (0x0555, address & 0x0F)
        world._replace_terrain = (
            lambda address, code, attribute:
            writes.append((address, code, attribute)))
        debris = DobkeratopsDebrisE700(world, 0x0200, 0x0100)
        debris.update(world, 0)  # `$E700` initializer only.
        self.assertFalse(debris.render_ready)
        for _ in range(16):
            debris.update(world, 0)
        self.assertEqual(16, len(writes))
        self.assertEqual((0x1234, 0x0FA0, 4), writes[0])
        self.assertTrue(all(code == 0x0FA0 for _address, code, _attr in writes))

    def test_dobkeratops_hit_flash_uses_rom_counter_bit_2(self) -> None:
        world = M72EnemyWorld()
        body = DobkeratopsBody(world, SimpleNamespace(defeated=False))
        body.state = "active"
        body.timer = 0x70
        body.shootable = True
        body.take_damage(world, 1)
        world.background_delta = 0

        world.frame_counter = 0
        body.update(world, 0)
        self.assertEqual(0x0F, body.flash_timer)
        self.assertTrue(body.flash_visible)

        world.frame_counter = 4
        body.update(world, 0)
        self.assertFalse(body.flash_visible)

    def test_9ce1_body_marks_root_and_exits_below_x_0120(self) -> None:
        world = M72EnemyWorld()
        root = SimpleNamespace(defeated=False)
        body = DobkeratopsBody(world, root)
        body.state = "active"
        body.timer = 0x40
        body.x = 0x0120
        world.background_delta = -1

        body.update(world, 0)

        self.assertEqual(0x011F, body.x)
        self.assertFalse(body.alive)
        self.assertTrue(root.defeated)

    def test_66f4_projectile_converts_to_e7ae_in_same_slot(self) -> None:
        world = M72EnemyWorld()
        source = SimpleNamespace(x=0x0200, y=0x0100, facing_right=True)
        projectile = Handler60BAProjectile(world, source)
        projectile.object_slot = 0x0D00
        world._terrain_code = lambda _x, _y: 0

        projectile.update(world, 0)

        self.assertTrue(projectile.alive)
        self.assertEqual("explosion", projectile.state)
        self.assertEqual(0x0D00, projectile.object_slot)
        self.assertEqual([0x50], world.sound_commands)

        world._terrain_code = None
        for _ in range(23):
            projectile.update(world, 0)
            self.assertTrue(projectile.alive)
        projectile.update(world, 0)
        self.assertFalse(projectile.alive)

    def test_9bb9_spawns_four_f280_intro_explosions(self) -> None:
        world = M72EnemyWorld()
        root = SimpleNamespace(cleanup=False, defeated=False)
        body = DobkeratopsBody(world, root)
        body.timer = 0x0061
        values = iter(range(8))
        world.rng = SimpleNamespace(next=lambda: next(values))

        body.update(world, 0)

        effects = [item for item in world.pending
                   if isinstance(item, ExplosionEffect)]
        self.assertEqual(4, len(effects))
        self.assertEqual((0xF280,) * 4,
                         tuple(item.scheduler_priority for item in effects))
        self.assertEqual(
            ((0x0348, 0x00F1), (0x034A, 0x00F3),
             (0x034C, 0x00F5), (0x034E, 0x00F7)),
            tuple((item.x, item.y) for item in effects))

    def test_9fae_anchor_erase_spawns_fe00_explosion_sound_and_score(self) -> None:
        world = M72EnemyWorld()
        root = SimpleNamespace(
            cleanup=False, anchors_remaining=4,
            body=SimpleNamespace(hp=0x1E))
        anchor = DobkeratopsArenaAnchor(world, root, 0x4394)
        anchor.state = "active"
        anchor.shootable = True
        anchor.timeout = 1
        anchor.x, anchor.y = 0x01FA, 0x015C
        world._terrain_address = lambda _x, _y: 0x1234

        anchor.update(world, 0)

        self.assertEqual(("erase", False, 0x1234),
                         (anchor.state, anchor.shootable,
                          anchor.tile_offset))
        self.assertEqual(1, len(world.pending))
        effect = world.pending[0]
        self.assertIsInstance(effect, ExplosionEffect)
        self.assertEqual(("e7b6", 0xFE00, 0x01FE, 0x0158),
                         (effect.effect, effect.scheduler_priority,
                          effect.x, effect.y))
        self.assertEqual([0x52], world.sound_commands)
        self.assertEqual([0x86F0], world.score_awards)

    def test_9e07_emits_equal_priority_trail_every_four_updates(self) -> None:
        world = M72EnemyWorld()
        body = SimpleNamespace(x=0x026E, y=0x0100)
        orb = DobkeratopsOrb(world, body)
        world._scheduler_cursor_priority = 0xF000

        for _ in range(4):
            orb.update(world, 0)

        self.assertEqual((0xF000, 0x003C, 0x0256),
                         (orb.scheduler_priority, orb.trail_timer, orb.x))
        self.assertEqual(1, len(world.pending))
        trail = world.pending[0]
        self.assertIsInstance(trail, DobkeratopsOrbTrail)
        self.assertEqual((0xF000, 0x0266, 0x00F4, 0x003C, 0x20),
                         (trail.scheduler_priority, trail.x, trail.y,
                          trail.phase_offset, trail.straight_timer))

    def test_80e3_tracking_enters_rom_attack_state(self) -> None:
        world = M72EnemyWorld(difficulty=0)
        enemy = PlayerTargeting80E3(world, 0x9405)
        world.player_native = (0x0180, enemy.y)
        world._collision_codes = lambda _x, _y: (0x0FFF, 0x0FFF)
        enemy.attack_delay = 1
        enemy.activation_timer = 0x01C0

        enemy.update(world, 0)

        self.assertEqual(("attack", 0x1F, 0x20, 0x01BF),
                         (enemy.state, enemy.attack_timer,
                          enemy.attack_delay, enemy.activation_timer))
        self.assertEqual(0x86F8, enemy.score_pointer)

    def test_80e3_expired_activation_forces_rom_left_velocity(self) -> None:
        world = M72EnemyWorld(difficulty=0)
        enemy = PlayerTargeting80E3(world, 0x9405)
        enemy.x = 0x0200
        enemy.y = 0x0110
        enemy.x_fraction = 0
        enemy.y_fraction = 0
        enemy.retarget_counter = 0xFFFF
        enemy.activation_timer = 0
        world.player_native = (0x0300, enemy.y)
        world._collision_codes = lambda _x, _y: (0x0FFF, 0x0FFF)

        enemy.update(world, 0)

        self.assertEqual(-0x0100, enemy.x_velocity)
        self.assertEqual((0x01FF, 0), (enemy.x, enemy.x_fraction))

    def test_80e3_expired_activation_cannot_cross_rom_wall_probe(self) -> None:
        world = M72EnemyWorld(difficulty=0)
        enemy = PlayerTargeting80E3(world, 0x9405)
        enemy.x = 0x0200
        enemy.y = 0x0110
        enemy.x_fraction = 0
        enemy.retarget_counter = 1
        enemy.activation_timer = 0
        world.player_native = (0x0300, enemy.y)

        def collision(x: int, _y: int) -> tuple[int, int]:
            if x == 0x01D0:
                return 0x0000, 0x0000
            return 0x0FFF, 0x0FFF

        world._collision_codes = collision

        enemy.update(world, 0)

        self.assertEqual(-0x0100, enemy.x_velocity)
        self.assertEqual(0x0200, enemy.x)

    def test_80e3_attack_emits_both_literal_children(self) -> None:
        world = M72EnemyWorld(difficulty=0)
        enemy = PlayerTargeting80E3(world, 0x9405)
        enemy.x = 0x0200
        enemy.y = 0x0110
        enemy.x_fraction = 0
        enemy.state = "attack"
        enemy.attack_timer = 0x1F
        world.player_native = (0x0180, 0x0110)

        for _ in range(0x10):
            enemy.update(world, 0)

        self.assertEqual(0x0F, enemy.attack_timer)
        self.assertEqual(2, len(world.pending))
        projectile, flash = world.pending
        self.assertIsInstance(projectile, Targeting80E3Projectile)
        self.assertIsInstance(flash, Targeting80E3AttackFlash)
        self.assertEqual((0x01D0, 0x0110, -0x0400, 0x395E),
                         (projectile.x, projectile.y,
                          projectile.x_velocity, projectile.collision_table))
        self.assertEqual((0x01DA, 0x0110, 0x390E, 0x0F, 4),
                         (flash.x, flash.y, flash.descriptor_root,
                          flash.sequence_timer, flash.sequence_delay))
        self.assertEqual((0x09, 0x09),
                         (world.resources.types[projectile.palette],
                          world.resources.types[flash.palette]))
        self.assertEqual((0xA000, 0x2000, 0x1F00),
                         (enemy.scheduler_priority,
                          projectile.scheduler_priority,
                          flash.scheduler_priority))

        for _ in range(0x0F):
            enemy.update(world, 0)
        self.assertEqual(("tracking", 0, 0x0206, 0xC0),
                         (enemy.state, enemy.attack_timer,
                          enemy.x, enemy.x_fraction))

    def test_842c_projectile_and_83df_flash_follow_rom_timing(self) -> None:
        world = M72EnemyWorld(difficulty=0)
        parent = PlayerTargeting80E3(world, 0x9405)
        parent.x = 0x0200
        parent.y = 0x0110
        world.player_native = (0x0180, 0x0110)
        projectile = Targeting80E3Projectile(world, parent)
        flash = Targeting80E3AttackFlash(world, parent)

        world.frame_counter = 0
        projectile.update(world, 0)
        self.assertEqual((0x01CC, 0, 0x393E),
                         (projectile.x, projectile.x_fraction,
                          projectile.descriptor))
        for _ in range(3):
            flash.update(world, 0)
        self.assertFalse(flash.visible)
        flash.update(world, 0)
        self.assertEqual((True, 0x0E, 1, 0x3920),
                         (flash.visible, flash.sequence_timer,
                          flash.sequence_delay, flash.descriptor))

    def test_897e_uses_rom_priority_and_recycled_q8_fraction(self) -> None:
        world = M72EnemyWorld()
        slot = world.object_pool.take()
        self.assertEqual(0x12C0, slot)
        world.object_pool.residue[slot] = (0x80, 0x40)
        enemy = TerrainAware897E(world, 0)
        world.object_pool.bind(enemy, slot)
        self.assertEqual((0x8030, 0x80, 0x40),
                         (enemy.scheduler_priority,
                          enemy.x_fraction, enemy.y_fraction))

    def test_rom_f6da_hit_flash_counters(self) -> None:
        cases = (
            (LargeTerrain74B4, 0x5408, 0x0C),
            (PlayerTargeting80E3, 0x9405, 0x10),
            (Handler60BA, 0x2C07, 0x0C),
        )
        for enemy_type, command, reload in cases:
            with self.subTest(enemy=enemy_type.__name__):
                world = M72EnemyWorld()
                enemy = enemy_type(world, command)
                normal = enemy.palette
                flash = enemy.flash_palette
                enemy.take_damage(world, 1)
                self.assertEqual(reload, enemy.flash_timer)
                self.assertEqual(normal, enemy.active_palette)
                for _ in range(4):
                    enemy.update(world, 0)
                self.assertEqual(reload - 4, enemy.flash_timer)
                self.assertTrue(enemy.flash_visible)
                self.assertEqual(flash, enemy.active_palette)

    def test_first_mini_boss_draws_both_rom_descriptor_halves(self) -> None:
        class RecordingAtlas:
            def __init__(self) -> None:
                self.descriptors = []

            def draw(self, _target, descriptor, _palette, _resource_type,
                     _anchor_x, _anchor_y) -> None:
                self.descriptors.append(descriptor)

        world = M72EnemyWorld()
        enemy = PlayerTargeting80E3(world, 0x9405)
        world.enemies = [enemy]
        recorder = RecordingAtlas()
        world.atlas = recorder
        world.draw(None)
        self.assertEqual((0x01D0, 0x01D4),
                         tuple(item.code for item in recorder.descriptors))
        self.assertEqual((0x6000, 0x6000),
                         tuple(item.attr for item in recorder.descriptors))

    def test_60ba_mini_boss_draws_both_rom_descriptor_halves(self) -> None:
        class RecordingAtlas:
            def __init__(self) -> None:
                self.descriptors = []

            def draw(self, _target, descriptor, _palette, _resource_type,
                     _anchor_x, _anchor_y) -> None:
                self.descriptors.append(descriptor)

        world = M72EnemyWorld()
        enemy = Handler60BA(world, 0x2C07)
        world.enemies = [enemy]
        recorder = RecordingAtlas()
        world.atlas = recorder
        world.draw(None)
        self.assertEqual((-32, 0),
                         tuple(item.dx for item in recorder.descriptors))
        self.assertEqual((0x0380, 0x0384),
                         tuple(item.code for item in recorder.descriptors))
        self.assertEqual((0x6000, 0x6000),
                         tuple(item.attr for item in recorder.descriptors))

    def test_weapon_kill_installs_rom_explosion_handler(self) -> None:
        cases = (
            (RedFlyer, 0x6C04, "e7be", 0x8530, 0x0240),
            # `$E817` sets timer 1 and falls through `$E82D`, so its first
            # pass displays `$85FA` but leaves the pointer at `$85FE`.
            (PlayerTargeting80E3, 0x9405, "e817", 0x85FE, 0x05D4),
        )
        for enemy_type, command, effect, sequence, code in cases:
            with self.subTest(enemy=enemy_type.__name__):
                world = M72EnemyWorld()
                enemy = enemy_type(world, command)
                enemy.hp = 1
                world.enemies = [enemy]
                enemy.take_damage(world, 1)
                world.update(0, 0, 0)
                self.assertEqual(1, len(world.enemies))
                explosion = world.enemies[0]
                self.assertIsInstance(explosion, ExplosionEffect)
                self.assertEqual(effect, explosion.effect)
                self.assertEqual(sequence, explosion.sequence_pointer)
                self.assertEqual(code,
                                 world.rom.word(explosion.descriptor + 2))

    def test_e817_big_explosion_draws_both_1c1b_records(self) -> None:
        class RecordingAtlas:
            def __init__(self) -> None:
                self.descriptors = []

            def draw(self, _target, descriptor, _palette, _resource_type,
                     _anchor_x, _anchor_y) -> None:
                self.descriptors.append(descriptor)

        world = M72EnemyWorld()
        explosion = ExplosionEffect(world, 0x0200, 0x0100, "e817")
        world.enemies = [explosion]
        recorder = RecordingAtlas()
        world.atlas = recorder
        world.draw(None)
        self.assertEqual((-32, 0),
                         tuple(item.dx for item in recorder.descriptors))
        self.assertEqual((0x05D4, 0x05D4),
                         tuple(item.code for item in recorder.descriptors))
        self.assertEqual((0x6000, 0x6800),
                         tuple(item.attr for item in recorder.descriptors))


class WeaponPickupTest(unittest.TestCase):
    def test_pickup_left_touching_player_right_waits_one_more_pixel(self) -> None:
        player = (0x01CB, 0x0110)
        self.assertFalse(TerrainBound55E9._overlaps_player(
            0x01E3, 0x011A, *player))
        self.assertTrue(TerrainBound55E9._overlaps_player(
            0x01E2, 0x011A, *player))

    def test_first_carrier_matches_mame_frames_2139_to_2350(self) -> None:
        world = M72EnemyWorld()
        scroll = M72Scroll()
        tilemaps = M72Tilemaps()
        stage = Stage.__new__(Stage)
        stage.m72_scroll = scroll
        stage.tilemaps = tilemaps
        counter = 0x0292
        expected = {
            2139: None,
            2160: ("script", 0x0296, 0x00F4, 0),
            2180: ("script", 0x0264, 0x00CE, 0),
            2200: ("script", 0x0232, 0x00C4, 0),
            2220: ("land", 0x0212, 0x00D0, 22),
            2250: ("walk", 0x01FB, 0x00D0, 0),
            2280: ("walk", 0x01CE, 0x00D0, 0),
            2300: ("turn", 0x01BB, 0x00D0, 20),
            2320: ("script", 0x01B1, 0x00D4, 0),
            2350: ("script", 0x0166, 0x00F4, 0),
        }
        while scroll.vblank < max(expected):
            scroll.advance()
            tilemaps.advance(scroll)
            counter = (counter + 1) & 0xFFFF
            world.update(scroll.progression, scroll.foreground_delta, counter,
                         stage.terrain_code, stage.collision_codes)
            if scroll.vblank not in expected:
                continue
            carriers = [enemy for enemy in world.enemies
                        if isinstance(enemy, TerrainBound55E9)]
            if expected[scroll.vblank] is None:
                self.assertEqual([], carriers)
                continue
            self.assertEqual(1, len(carriers))
            carrier = carriers[0]
            timer = carrier.timer if carrier.state in ("land", "turn") else 0
            self.assertEqual(expected[scroll.vblank],
                             (carrier.state, carrier.x, carrier.y, timer),
                             f"MAME frame {scroll.vblank}")

    def test_rom_27fe_resource_and_pickup_type_table(self) -> None:
        expected = (
            ((0x0A, 0x00), (0x0A, 0x00)),
            ((0x0A, 0x02), (0x0A, 0x02)),
            ((0x0A, 0x04), (0x0A, 0x04)),
            ((0x0A, 0x0A), (0x0A, 0x0A)),
            ((0x0A, 0x06), (0x0A, 0x06)),
            ((0x56, 0x08), (0x56, 0x08)),
            ((0x0A, 0x0A), (0x0A, 0x00)),
            ((0x0A, 0x0C), (0x0A, 0x0C)),
        )
        for index, phases in enumerate(expected):
            for phase, (resource_type, pickup_type) in zip((0, 2), phases):
                with self.subTest(index=index, phase=phase):
                    world = M72EnemyWorld()
                    carrier = TerrainBound55E9(world, index << 4)
                    world.frame_counter = phase
                    carrier.take_damage(world, 1)
                    self.assertEqual("pickup", carrier.state)
                    self.assertEqual(pickup_type, carrier.pickup_type)
                    self.assertEqual(resource_type,
                                     world.resources.types[carrier.palette])
                    self.assertIsInstance(world.pending[-1], ExplosionE7BE)

    def test_type_zero_pickup_matches_force_state_snapshot_2348(self) -> None:
        world = M72EnemyWorld()
        carrier = TerrainBound55E9(world, 0x1006)
        world.frame_counter = 0
        carrier.take_damage(world, 1)
        self.assertEqual(0, carrier.pickup_type)
        self.assertEqual((200, [0x86EC]),
                         (world.score, world.score_awards))
        world.player_native = (carrier.x, carrier.y)
        carrier.update(world, 0)
        self.assertFalse(carrier.alive)
        self.assertEqual(1, world.weapon_pickups)
        self.assertEqual(0, world.weapon_type)
        self.assertEqual(0, world.force_level)
        self.assertTrue(world.consume_weapon_pickup())
        self.assertEqual(0, world.weapon_pickups)
        self.assertEqual(1, world.force_level)
        self.assertEqual((600, [0x86EC, 0x86F4]),
                         (world.score, world.score_awards))

    def test_speed_pickup_reuses_record_for_exact_5914_lifetime(self) -> None:
        world = M72EnemyWorld()
        carrier = TerrainBound55E9(world, 0x0030)
        world.frame_counter = 0
        carrier.take_damage(world, 1)
        self.assertEqual(0x0A, carrier.pickup_type)
        world.player_native = (carrier.x, carrier.y)
        indicator_position = ((carrier.x - 0x1F) & 0xFFFF, carrier.y)

        carrier.update(world, 0)
        self.assertTrue(carrier.alive)
        self.assertEqual("speed_indicator", carrier.state)
        self.assertEqual(indicator_position, (carrier.x, carrier.y))
        self.assertEqual(0x0F, carrier.timer)
        self.assertEqual(0x28C2, carrier.descriptor)
        self.assertEqual(0x09, world.resources.types[carrier.palette])
        self.assertEqual([0x3A], world.sound_commands)

        for _ in range(14):
            carrier.update(world, 0)
        self.assertTrue(carrier.alive)
        self.assertEqual(1, carrier.timer)
        carrier.update(world, 0)
        self.assertFalse(carrier.alive)
        self.assertEqual(0, carrier.timer)

    def test_shot_death_runs_higher_priority_carrier_explosion_same_pass(self) -> None:
        world = M72EnemyWorld()
        carrier = TerrainBound55E9(world, 0)
        carrier.x = 0x0200
        carrier.y = 0x0100
        slot = world.object_pool.take()
        self.assertIsNotNone(slot)
        world.object_pool.bind(carrier, slot)
        world.enemies = [carrier]

        self.assertTrue(world.damage_shot_native(
            (0x01F0, 0x0210, 0x00F0, 0x0110)))
        explosions = [enemy for enemy in world.enemies
                      if isinstance(enemy, ExplosionE7BE)]
        self.assertEqual(1, len(explosions))
        self.assertEqual([], world.pending)
        self.assertEqual(1, explosions[0].sequence_timer)


if __name__ == "__main__":
    unittest.main()
