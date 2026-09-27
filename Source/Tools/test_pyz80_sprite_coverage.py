#!/usr/bin/env python3
"""Focused fail-closed tests for active-Python sprite coverage."""

from __future__ import annotations

import ast
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from pyz80_compiler import sprite_coverage as coverage
from pyz80_compiler.sprite_coverage import (
    EXPECTED_COMMON_PAIR_COUNT,
    SpriteCoverageError,
    analyze_sprite_coverage,
    resolve_python_bank,
)


ROOT = Path(__file__).resolve().parents[2]


class SpriteCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = analyze_sprite_coverage(ROOT)

    @staticmethod
    def _stage_from_enemy_source(source: str, stage: int):
        tree = ast.parse(source)
        rom = coverage._WorldRom((
            ROOT / "Assets" / "Converted" / "Arcade" /
            "RTYPE_MAINCPU_REGION.bin").read_bytes())
        return coverage._stage_domains(ROOT, tree, rom, (stage,))

    def test_active_graph_owns_every_draw_sink_and_309_common_pairs(self) -> None:
        report = self.report
        self.assertEqual(report.root_module, "rtype_port.app")
        self.assertNotIn("rtype_port.full_runtime", report.reachable_modules)
        self.assertEqual(len(report.owned_sink_ids), 25)
        self.assertEqual(len(set(report.owned_sink_ids)), 25)
        self.assertEqual(len(report.pairs), EXPECTED_COMMON_PAIR_COUNT)
        self.assertEqual(dict(report.domain_counts), {
            "fixed_shot_visual": 1,
            "force_beams": 192,
            "force_body": 31,
            "force_darts": 15,
            "force_grids": 11,
            "force_projectiles": 5,
            "force_rays": 16,
            "player_bits": 24,
            "player_death": 8,
            "terminal_shots": 6,
        })
        self.assertEqual(report.unresolved_domains, ())
        self.assertEqual(
            {name: len(pairs) for name, pairs in report.common_domain_pairs},
            dict(report.domain_counts))
        self.assertEqual(
            {item.domain for item in report.common_provenance},
            set(dict(report.domain_counts)))
        self.assertTrue(all(item.source_symbols
                            for item in report.common_provenance))
        self.assertTrue(all(item.owned_sink_ids
                            for item in report.common_provenance))
        self.assertTrue(all(item.bank_keys
                            for item in report.common_provenance))
        self.assertIn("run_python.cmd", dict(report.source_hashes))
        self.assertIn("rtype_port.enemies", dict(report.source_hashes))
        self.assertEqual(len(report.rom_sha256), 64)

    def test_all_788_stage_events_have_closed_pair_and_handler_ownership(self) -> None:
        report = self.report
        self.assertEqual([stage for stage, _pairs in report.per_stage_pairs],
                         list(range(1, 9)))
        self.assertEqual(
            [len(pairs) for _stage, pairs in report.per_stage_pairs],
            [423, 320, 69, 273, 265, 157, 346, 97])
        self.assertEqual(
            [item.cell_count for item in report.stage_provenance],
            [1581, 11988, 235, 2765, 7435, 2588, 5835, 2350])
        self.assertEqual(
            [item.event_count for item in report.stage_provenance],
            [161, 43, 15, 140, 79, 123, 177, 50])
        self.assertEqual(
            sum(item.event_count for item in report.stage_provenance), 788)
        for item in report.stage_provenance:
            self.assertEqual(item.pair_count,
                             len(dict(report.per_stage_pairs)[item.stage]))
            self.assertEqual(
                {handler for handler, _count in item.handler_counts},
                {handler for handler, _classes in item.handler_classes})
            self.assertEqual(len(item.event_sha256), 64)
            self.assertTrue(item.owned_descriptor_sinks)
            self.assertEqual(len(item.events), item.event_count)
            handler_classes = dict(item.handler_classes)
            self.assertTrue(all(
                event.classes == handler_classes[event.handler]
                for event in item.events))
            self.assertEqual(
                set(dict(report.per_stage_pairs)[item.stage]),
                {pair for entry in item.class_coverage
                 for pair in entry.pairs})
            self.assertTrue(all(entry.selector_sources
                                for entry in item.class_coverage))
            expected_banks = {}
            for pair in dict(report.per_stage_pairs)[item.stage]:
                expected_banks.setdefault(pair.resource_type, set()).update(
                    pair.bank_keys)
            self.assertEqual(
                dict(item.resource_bank_domains),
                {resource: tuple(sorted(keys))
                 for resource, keys in expected_banks.items()})

    def test_ray_seeds_and_terminal_defaults_come_from_active_python(self) -> None:
        facts = dict(self.report.selector_facts)
        self.assertEqual(facts["force_ray_turning_seed_phases"], (0, 2))
        self.assertEqual(facts["force_ray_mirrored_seed_phases"], (0,))
        self.assertEqual(facts["force_ray_terminal_initial"], (0x18,))
        self.assertEqual(facts["force_grid_terminal_initial"], (0x18,))
        self.assertEqual(facts["force_dart_terminal_initial"], (0x30,))
        addresses = {
            pair.descriptor.address for pair in self.report.pairs
            if pair.resource_type == 0x3D
        }
        # Odd mirrored phases used to decode these misaligned ROM words as
        # bogus descriptor addresses; none is constructor-reachable.
        self.assertTrue({0x0008, 0x089A, 0x9AF4, 0xEE20,
                         0xF4FC, 0xFC20}.isdisjoint(addresses))

    def test_changed_ray_terminal_default_fails_closed(self) -> None:
        path = ROOT / "Source" / "Python" / "rtype_port" / "force.py"
        source = path.read_text(encoding="utf-8")
        old = "class ForceRaySegment:\n"
        start = source.index(old)
        default = "    terminal_offset: int = 0x18\n"
        at = source.index(default, start)
        mutated = source[:at] + source[at:].replace(
            default, "    terminal_offset: int = 0x30\n", 1)
        with self.assertRaisesRegex(
                SpriteCoverageError, "Force ray domain|common sprite domains"):
            analyze_sprite_coverage(
                ROOT, source_overrides={"rtype_port.force": mutated})

    def test_descriptor_ref_keeps_address_and_decoded_rom_geometry(self) -> None:
        death = next(
            pair for pair in self.report.pairs
            if pair.resource_type == 0x09 and pair.descriptor.address == 0x1338)
        self.assertEqual(death.descriptor.address, 0x1338)
        self.assertIn(death.descriptor.width, (1, 2, 4, 8))
        self.assertIn(death.descriptor.height, (1, 2, 4, 8))
        self.assertEqual(
            death.descriptor.flip_x,
            bool(death.descriptor.attribute & 0x0800))

    def test_bank_key_matches_typed_and_palette_fallback_python_paths(self) -> None:
        self.assertEqual(
            resolve_python_bank(ROOT, 7, 0x56).kind,
            "typed-resource")
        self.assertEqual(
            resolve_python_bank(ROOT, 7, 0x56).value,
            0x56)
        self.assertEqual(
            resolve_python_bank(ROOT, 7, 0x3D).kind,
            "palette-fallback")
        self.assertEqual(
            resolve_python_bank(ROOT, 7, 0x3D).value,
            7)
        ray = next(
            pair for pair in self.report.pairs
            if pair.resource_type == 0x3D)
        self.assertEqual(len(ray.bank_keys), 16)

    def test_added_unknown_atlas_sink_fails_closed(self) -> None:
        path = ROOT / "Source" / "Python" / "rtype_port" / "force.py"
        source = path.read_text(encoding="utf-8")
        marker = (
            "        for projectile in self.projectiles.values():\n"
            "            atlas.draw(target, "
            "read_descriptor(self.rom, projectile.descriptor),\n"
        )
        self.assertIn(marker, source)
        added = (
            "        atlas.draw(target, read_descriptor(self.rom, self.descriptor),\n"
            "                   self.resource_slot, 0x56, self.x, self.y)\n"
        )
        mutated = source.replace(marker, added + marker, 1)
        with self.assertRaisesRegex(
                SpriteCoverageError, "unknown/new M72SpriteAtlas.draw sink"):
            analyze_sprite_coverage(
                ROOT, source_overrides={"rtype_port.force": mutated})

    def test_changed_known_sink_shape_fails_closed(self) -> None:
        path = ROOT / "Source" / "Python" / "rtype_port" / "force.py"
        source = path.read_text(encoding="utf-8")
        old = "projectile.resource_slot, 0x02,"
        self.assertIn(old, source)
        mutated = source.replace(old, "projectile.resource_slot, 0x03,", 1)
        with self.assertRaisesRegex(
                SpriteCoverageError, "changed sink shape"):
            analyze_sprite_coverage(
                ROOT, source_overrides={"rtype_port.force": mutated})

    def test_removed_active_event_handler_fails_closed(self) -> None:
        path = ROOT / "Source" / "Python" / "rtype_port" / "enemies.py"
        source = path.read_text(encoding="utf-8")
        entry = '        0x596D: "red_flyer",\n'
        self.assertIn(entry, source)
        mutated = source.replace(entry, "", 1)
        with self.assertRaisesRegex(SpriteCoverageError,
                                    "unknown handlers: \\$596D"):
            analyze_sprite_coverage(
                ROOT, source_overrides={"rtype_port.enemies": mutated})

    def test_unknown_stage_descriptor_selector_fails_closed(self) -> None:
        path = ROOT / "Source" / "Python" / "rtype_port" / "enemies.py"
        source = path.read_text(encoding="utf-8")
        expression = "self.descriptor = world.rom.word(table + offset)"
        self.assertIn(expression, source)
        mutated = source.replace(
            expression,
            "self.descriptor = world.dynamic_descriptor(table, offset)", 1)
        with self.assertRaisesRegex(SpriteCoverageError,
                                    "unresolved dynamic sprite domains"):
            analyze_sprite_coverage(
                ROOT, source_overrides={"rtype_port.enemies": mutated})

    def test_resource_epoch_relation_is_not_a_cartesian_product(self) -> None:
        base_stage = self.report.stage_provenance[0]
        base = next(item for item in base_stage.class_coverage
                    if item.class_name == "Handler60BAChild")
        normal = {
            pair.descriptor.address for pair in base.pairs
            if pair.resource_type == 0x3C
        }
        transitioned = {
            pair.descriptor.address for pair in base.pairs
            if pair.resource_type == 0x01
        }
        self.assertTrue(normal)
        self.assertTrue(transitioned)
        self.assertTrue(normal.isdisjoint(transitioned))
        self.assertEqual(len(base.pairs), len(normal) + len(transitioned))

        path = ROOT / "Source" / "Python" / "rtype_port" / "enemies.py"
        source = path.read_text(encoding="utf-8")
        first = source.index("class Handler60BAChild")
        last = source.index("\nclass ", first + 1)
        body = source[first:last]
        old = "self.palette = world.resources.acquire(0x01)"
        self.assertEqual(body.count(old), 1)
        mutated_body = body.replace(
            old, "self.palette = world.resources.acquire(0x02)", 1)
        mutated_source = source[:first] + mutated_body + source[last:]
        _pairs, provenance = self._stage_from_enemy_source(mutated_source, 1)
        changed = next(item for item in provenance[0].class_coverage
                       if item.class_name == "Handler60BAChild")
        changed_transition = {
            pair.descriptor.address for pair in changed.pairs
            if pair.resource_type == 0x02
        }
        changed_normal = {
            pair.descriptor.address for pair in changed.pairs
            if pair.resource_type == 0x3C
        }
        self.assertEqual(changed_transition, transitioned)
        self.assertEqual(changed_normal, normal)
        changed_keys = {
            (pair.descriptor.address, pair.resource_type)
            for pair in changed.pairs
        }
        self.assertTrue(all((address, 0x02) not in changed_keys
                            for address in normal))
        self.assertTrue(all((address, 0x3C) not in changed_keys
                            for address in transitioned))

    def test_collision_assignment_is_not_a_draw_descriptor_but_render_is(self) -> None:
        path = ROOT / "Source" / "Python" / "rtype_port" / "enemies.py"
        source = path.read_text(encoding="utf-8")
        base_stage_pairs = dict(self.report.per_stage_pairs)[2]
        base_class = next(
            item for item in self.report.stage_provenance[1].class_coverage
            if item.class_name == "Multipart915BChild")

        collision = "self.collision_table = 0x427C"
        self.assertEqual(source.count(collision), 1)
        collision_source = source.replace(
            collision, "self.collision_table = 0x42C0", 1)
        collision_pairs, collision_provenance = self._stage_from_enemy_source(
            collision_source, 2)
        collision_class = next(
            item for item in collision_provenance[0].class_coverage
            if item.class_name == "Multipart915BChild")
        self.assertEqual(collision_pairs[0][1], base_stage_pairs)
        self.assertEqual(collision_class.pairs, base_class.pairs)

        render = "self.descriptor = base + phase * 6"
        self.assertEqual(source.count(render), 1)
        render_source = source.replace(
            render, "self.descriptor = base + phase * 12", 1)
        render_pairs, render_provenance = self._stage_from_enemy_source(
            render_source, 2)
        render_class = next(
            item for item in render_provenance[0].class_coverage
            if item.class_name == "Multipart915BChild")
        self.assertNotEqual(render_pairs[0][1], base_stage_pairs)
        self.assertNotEqual(render_class.pairs, base_class.pairs)

        base_stage5_pairs = dict(self.report.per_stage_pairs)[5]
        base_formation = next(
            item for item in self.report.stage_provenance[4].class_coverage
            if item.class_name == "Formation78F8Child")
        first = source.index("class Formation78F8Child")
        last = source.index("\nclass ", first + 1)
        formation = source[first:last]
        collision = "self.collision_table = collision"
        self.assertEqual(formation.count(collision), 2)
        collision_formation = formation.replace(
            collision, "self.collision_table = _u16(collision + 2)")
        collision_source = source[:first] + collision_formation + source[last:]
        stage5_pairs, stage5_provenance = self._stage_from_enemy_source(
            collision_source, 5)
        changed_formation = next(
            item for item in stage5_provenance[0].class_coverage
            if item.class_name == "Formation78F8Child")
        self.assertEqual(stage5_pairs[0][1], base_stage5_pairs)
        self.assertEqual(changed_formation.pairs, base_formation.pairs)

        render = "self.descriptor = base + self.motion.phase * stride"
        self.assertEqual(formation.count(render), 1)
        render_formation = formation.replace(
            render,
            "self.descriptor = base + self.motion.phase * (stride + 6)", 1)
        render_source = source[:first] + render_formation + source[last:]
        stage5_pairs, stage5_provenance = self._stage_from_enemy_source(
            render_source, 5)
        changed_formation = next(
            item for item in stage5_provenance[0].class_coverage
            if item.class_name == "Formation78F8Child")
        self.assertNotEqual(stage5_pairs[0][1], base_stage5_pairs)
        self.assertNotEqual(changed_formation.pairs, base_formation.pairs)

    def test_correlated_constructor_and_turn_selectors_exclude_false_rom_reads(
            self) -> None:
        stage1 = self.report.stage_provenance[0]
        tentacle = next(item for item in stage1.class_coverage
                        if item.class_name == "DobkeratopsTentacle")
        self.assertEqual(tentacle.relation_kind,
                         "constructor-call-record-tip-correlation")
        self.assertEqual(len(tentacle.pairs), 13)
        self.assertNotIn(
            0x5E8B, {pair.descriptor.address for pair in tentacle.pairs})

        stage4 = self.report.stage_provenance[3]
        turning = next(item for item in stage4.class_coverage
                       if item.class_name == "Enemy8F5E")
        self.assertEqual(turning.relation_kind,
                         "direction-transition-rom-table-correlation")
        self.assertEqual(len(turning.pairs), 20)
        self.assertTrue({0x2A46, 0x1775}.isdisjoint(
            pair.descriptor.address for pair in turning.pairs))

    def test_constructor_domains_survive_the_immutable_report_boundary(self) -> None:
        expected = {
            2: (0x9246, 0x92C3, 0x933C, 0x9477, 0x94E1),
            5: (0x799C, 0x7A1E, 0x7AD9),
        }
        names = {2: "Multipart915BChild", 5: "Formation78F8Child"}
        for stage, initializer_values in expected.items():
            provenance = self.report.stage_provenance[stage - 1]
            item = next(entry for entry in provenance.class_coverage
                        if entry.class_name == names[stage])
            parameters = dict(item.constructor_parameters)
            self.assertIsInstance(item.constructor_parameters, tuple)
            self.assertIsInstance(parameters["initializer"], tuple)
            self.assertEqual(parameters["initializer"], initializer_values)
            self.assertEqual(parameters["initializer"], tuple(sorted(
                parameters["initializer"], key=repr)))
            with self.assertRaises(FrozenInstanceError):
                item.relation_kind = "mutated"  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
